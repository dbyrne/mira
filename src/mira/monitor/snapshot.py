"""MonitorSnapshot — the frozen aggregate the webapp renders at /monitor.

Frozen dataclasses + a pure ``build_snapshot`` aggregator. The builder
reads NINA via the existing NinaClient (already tolerant; methods return
empty dicts on failure) and the DSO ledger via the existing walk-
sidecars path. Anomalies are computed by the separate ``anomaly`` module
and attached.

No I/O state lives here. Each request to /monitor calls ``build_snapshot``
fresh. The cost is a handful of HTTP calls to NINA + a captures-dir walk;
on a healthy LAN this is sub-second.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import ScoutConfig
from ..dso.catalog import DsoCatalog, DsoTarget
from ..dso.ledger import Ledger, aggregate_ledger, walk_sidecars
from ..observability import evaluate_observability_at_coords


# ---------------------------------------------------------------------------
# Sub-state dataclasses. All frozen so /monitor/partial can render without
# worrying about mutation during a render cycle.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrameStat:
    """One row from NINA image-history, post-parsed.

    All numeric fields are Optional because the plugin doesn't always
    populate them — stars/HFR are missing on a plate-solve-only call,
    mean/median can be blank on early captures, etc."""
    filename: str
    timestamp_utc: datetime | None
    exposure_s: float
    gain: int | None
    filter_name: str
    stars: int | None
    hfr: float | None
    mean: float | None
    median: float | None


@dataclass(frozen=True)
class MountState:
    connected: bool
    at_park: bool
    tracking: bool
    slewing: bool
    ra_deg: float | None
    dec_deg: float | None
    pier_side: str = ""


@dataclass(frozen=True)
class CameraState:
    connected: bool
    state: str = ""          # "Idle" | "Exposing" | "Downloading" | ...
    temp_c: float | None = None
    setpoint_c: float | None = None
    cooler_power: float | None = None    # 0.0–1.0


@dataclass(frozen=True)
class FilterWheelState:
    connected: bool
    is_moving: bool = False
    selected_name: str = ""
    available: tuple[str, ...] = ()


@dataclass(frozen=True)
class FocuserState:
    connected: bool
    is_moving: bool = False
    position: int | None = None
    temperature_c: float | None = None
    last_af_utc: datetime | None = None
    last_af_hfr_before: float | None = None
    last_af_hfr_after: float | None = None
    last_af_position: int | None = None


@dataclass(frozen=True)
class GuiderState:
    connected: bool
    is_guiding: bool = False
    rms_total_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None
    last_dither_utc: datetime | None = None


@dataclass(frozen=True)
class SessionState:
    """Derived "what is the rig doing right now" view."""
    sequence_running: bool
    current_target: str = ""             # canonical name when matched
    current_target_common: str = ""      # common_name from catalog
    current_filter: str = ""
    # Frame counters: NINA doesn't always expose these cleanly. When unknown,
    # we leave them at zero and the UI shows "frame ?" rather than fabricating.
    frame_in_filter: int = 0
    frames_planned_in_filter: int = 0
    # Minutes until current target drops below the configured altitude floor
    # at the configured site, or None if unobserved/unknown.
    target_sets_in_min: int | None = None


@dataclass(frozen=True)
class TargetLedgerView:
    """Per-active-target ledger slice — the same numbers as
    ``mira dso status <target>`` but for the in-flight target only."""
    target_name: str
    common_name: str
    per_filter: tuple[tuple[str, float, int, float], ...]
    # tuple of (filter_name, captured_minutes, budget_minutes, pct_done)
    total_captured: float
    total_budget: float
    total_pct: float


@dataclass(frozen=True)
class EventEntry:
    timestamp_utc: datetime
    kind: str         # "af" | "dither" | "filter_change" | "plate_solve" | "error" | "info"
    summary: str


@dataclass(frozen=True)
class Anomaly:
    """A detected anomaly. Populated by the anomaly module; included here so
    /monitor/partial can iterate ``snapshot.anomalies`` directly."""
    section: str      # "frame" | "guiding" | "camera" | "filter" | "session" | "target"
    severity: str     # "amber" | "red"
    message: str      # short — fits in a badge
    detail: str       # longer — visible on tap/hover
    fired_at: datetime


@dataclass(frozen=True)
class MonitorSnapshot:
    """All the state /monitor needs in one frozen object.

    ``mode`` is a small string the UI shows at the top — "live" when the
    snapshot was built from a reachable NINA, "snapshot" when it came
    from a Syncthing-mirrored snapshot.json fallback, "demo" when this is
    canned data for UI verification."""
    generated_utc: datetime
    mode: str
    nina_reachable: bool
    nina_error: str
    session: SessionState
    mount: MountState
    camera: CameraState
    filter_wheel: FilterWheelState
    focuser: FocuserState
    guider: GuiderState
    recent_frames: tuple[FrameStat, ...]      # newest first, max ~50
    ledger_view: TargetLedgerView | None
    recent_events: tuple[EventEntry, ...]     # newest first, max ~20
    anomalies: tuple[Anomaly, ...] = ()       # populated by anomaly.detect_anomalies


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_snapshot(
    nina_client,
    *,
    catalog: DsoCatalog | None = None,
    config: ScoutConfig | None = None,
    captures_root: Path | None = None,
    now_utc: datetime | None = None,
) -> MonitorSnapshot:
    """Build a MonitorSnapshot from a live NinaClient.

    Catalog + config are optional so the same builder can produce a
    skeleton snapshot before they're loaded (e.g. for early app
    startup); if both are provided, the ledger view and "target sets
    in" are populated.

    Anomalies are NOT detected here — call ``anomaly.attach_anomalies``
    on the returned snapshot to fold them in. Separation keeps the
    builder pure and unit-testable in isolation."""
    now = now_utc or datetime.now(timezone.utc)

    status = nina_client.status()
    reachable = status.reachable
    nina_error = status.error or ""

    # NINA equipment info endpoints. Each call is wrapped to tolerate the
    # plugin returning shapes we don't expect.
    mount_raw = _safe_call(lambda: nina_client.mount_info()) or {}
    camera_raw = _safe_call(lambda: _camera_info(nina_client)) or {}
    wheel_raw = _safe_call(lambda: nina_client.filter_wheel_info()) or {}
    focuser_raw = _safe_call(lambda: _focuser_info(nina_client)) or {}
    last_af_raw = _safe_call(lambda: _last_af(nina_client)) or {}
    guider_raw = _safe_call(lambda: _guider_info(nina_client)) or {}
    image_history = _safe_call(lambda: nina_client.image_history(all_images=True)) or []

    mount = MountState(
        connected=bool(mount_raw.get("Connected", False)),
        at_park=bool(mount_raw.get("AtPark", False)),
        tracking=bool(mount_raw.get("TrackingEnabled") or mount_raw.get("Tracking")),
        slewing=bool(mount_raw.get("Slewing", False)),
        ra_deg=_radec_deg_from_mount(mount_raw),
        dec_deg=_as_float(mount_raw.get("Declination")),
        pier_side=str(mount_raw.get("SideOfPier") or mount_raw.get("PierSide") or ""),
    )
    camera = CameraState(
        connected=bool(camera_raw.get("Connected", False)),
        state=str(camera_raw.get("CameraState", "")),
        temp_c=_as_float(camera_raw.get("Temperature")),
        setpoint_c=_as_float(camera_raw.get("TemperatureSetPoint")
                             or camera_raw.get("SetPoint")),
        cooler_power=_cooler_power(camera_raw),
    )
    filter_wheel = FilterWheelState(
        connected=bool(wheel_raw.get("Connected", False)),
        is_moving=bool(wheel_raw.get("IsMoving", False)),
        selected_name=_selected_filter_name(wheel_raw),
        available=tuple(
            str(f.get("Name", "")) for f in (wheel_raw.get("AvailableFilters") or [])
            if isinstance(f, dict)
        ),
    )
    focuser = FocuserState(
        connected=bool(focuser_raw.get("Connected", False)),
        is_moving=bool(focuser_raw.get("IsMoving", False)),
        position=_as_int(focuser_raw.get("Position")),
        temperature_c=_as_float(focuser_raw.get("Temperature")),
        last_af_utc=_iso_to_dt(last_af_raw.get("Timestamp")
                               or last_af_raw.get("Time")
                               or last_af_raw.get("Date")),
        last_af_hfr_before=_as_float(last_af_raw.get("InitialHFR")
                                     or last_af_raw.get("HfrBefore")),
        last_af_hfr_after=_as_float(last_af_raw.get("CalculatedHFR")
                                    or last_af_raw.get("HfrAfter")),
        last_af_position=_as_int(last_af_raw.get("CalculatedPosition")
                                 or last_af_raw.get("FinalPosition")),
    )
    guider = GuiderState(
        connected=bool(guider_raw.get("Connected", False)),
        is_guiding=bool(guider_raw.get("IsGuiding") or guider_raw.get("Guiding")),
        rms_total_arcsec=_as_float(guider_raw.get("RMSError")
                                   or guider_raw.get("RMS")
                                   or guider_raw.get("TotalRMS")),
        rms_ra_arcsec=_as_float(guider_raw.get("RMSRA")
                                or guider_raw.get("RARMS")),
        rms_dec_arcsec=_as_float(guider_raw.get("RMSDec")
                                 or guider_raw.get("DecRMS")),
        last_dither_utc=_iso_to_dt(guider_raw.get("LastDither")
                                   or guider_raw.get("LastDitherTime")),
    )
    frames = _parse_image_history(image_history)
    session = _derive_session_state(
        status=status, camera=camera, filter_wheel=filter_wheel,
        frames=frames, catalog=catalog, config=config, now_utc=now,
    )
    ledger_view = _build_ledger_view(
        session=session, catalog=catalog, captures_root=captures_root,
    )
    events = _derive_events(
        frames=frames, focuser=focuser, filter_wheel=filter_wheel,
        guider=guider, status=status,
    )

    return MonitorSnapshot(
        generated_utc=now,
        mode="live" if reachable else "stale",
        nina_reachable=reachable,
        nina_error=nina_error,
        session=session,
        mount=mount,
        camera=camera,
        filter_wheel=filter_wheel,
        focuser=focuser,
        guider=guider,
        recent_frames=tuple(frames[:50]),
        ledger_view=ledger_view,
        recent_events=tuple(events[:20]),
        anomalies=(),
    )


# ---------------------------------------------------------------------------
# Private helpers — small parsers, kept here so the public surface stays
# tight and unit-tested via build_snapshot.
# ---------------------------------------------------------------------------

def _safe_call(fn):
    """Run a getter, return None on any exception. Mirrors the
    tolerate-and-degrade pattern NinaClient uses internally."""
    try:
        return fn()
    except Exception:
        return None


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _iso_to_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _camera_info(nina_client) -> dict[str, Any]:
    """Pull the raw camera info dict the way NinaClient does internally."""
    data = nina_client._get("/equipment/camera/info")  # type: ignore[attr-defined]
    if isinstance(data, dict):
        resp = data.get("Response", {})
        if isinstance(resp, dict):
            return resp
    return {}


def _focuser_info(nina_client) -> dict[str, Any]:
    # NinaClient adds a method for this in the Phase-1 commit; fall back
    # to a direct GET if we're on the older client.
    try:
        return nina_client.focuser_info()  # type: ignore[attr-defined]
    except AttributeError:
        data = nina_client._get("/equipment/focuser/info")  # type: ignore[attr-defined]
        if isinstance(data, dict):
            resp = data.get("Response", {})
            if isinstance(resp, dict):
                return resp
        return {}


def _last_af(nina_client) -> dict[str, Any]:
    try:
        return nina_client.last_af()  # type: ignore[attr-defined]
    except AttributeError:
        data = nina_client._get("/equipment/focuser/last-af")  # type: ignore[attr-defined]
        if isinstance(data, dict):
            resp = data.get("Response", {})
            if isinstance(resp, dict):
                return resp
        return {}


def _guider_info(nina_client) -> dict[str, Any]:
    try:
        return nina_client.guider_info()  # type: ignore[attr-defined]
    except AttributeError:
        try:
            data = nina_client._get("/equipment/guider/info")  # type: ignore[attr-defined]
        except Exception:
            return {}
        if isinstance(data, dict):
            resp = data.get("Response", {})
            if isinstance(resp, dict):
                return resp
        return {}


def _radec_deg_from_mount(mount_raw: dict[str, Any]) -> float | None:
    """RA from NINA's mount info is in HOURS. Convert to degrees so the
    UI doesn't have to remember the convention."""
    ra_h = _as_float(mount_raw.get("RightAscension"))
    if ra_h is None:
        return None
    return ra_h * 15.0


def _cooler_power(camera_raw: dict[str, Any]) -> float | None:
    """Cooler duty can be reported 0-1 or 0-100 depending on driver.
    Normalize to 0-1."""
    raw = _as_float(camera_raw.get("CoolerPower")
                    or camera_raw.get("CCDPower"))
    if raw is None:
        return None
    if raw > 1.5:
        return raw / 100.0
    return raw


def _selected_filter_name(wheel_raw: dict[str, Any]) -> str:
    """The selected-filter shape varies across NINA versions: sometimes
    {SelectedFilter: {Name: 'Ha', Id: 5}}, sometimes just {SelectedFilter: 'Ha'}.
    Walk the variants without raising."""
    sel = wheel_raw.get("SelectedFilter")
    if isinstance(sel, dict):
        name = sel.get("Name")
        if name:
            return str(name)
    if isinstance(sel, str):
        return sel
    # Fall back to looking up the position index in AvailableFilters.
    pos = _as_int(wheel_raw.get("Position"))
    avail = wheel_raw.get("AvailableFilters")
    if isinstance(pos, int) and isinstance(avail, list) and 0 <= pos < len(avail):
        item = avail[pos]
        if isinstance(item, dict):
            return str(item.get("Name", ""))
    return ""


def _parse_image_history(history: Iterable[dict[str, Any]]) -> list[FrameStat]:
    """NINA image-history is oldest-first; we reverse so newest-first
    survives downstream slicing. Skip entries missing a Filename — they're
    placeholders the plugin emits during a Take Sub Frame error."""
    frames: list[FrameStat] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        filename = str(entry.get("Filename") or "").strip()
        if not filename:
            continue
        frames.append(FrameStat(
            filename=filename,
            timestamp_utc=_iso_to_dt(entry.get("Date") or entry.get("Time")),
            exposure_s=float(entry.get("ExposureTime") or 0.0),
            gain=_as_int(entry.get("Gain")),
            filter_name=str(entry.get("Filter") or ""),
            stars=_as_int(entry.get("Stars")),
            hfr=_as_float(entry.get("HFR")),
            mean=_as_float(entry.get("Mean")),
            median=_as_float(entry.get("Median")),
        ))
    frames.reverse()
    return frames


def _derive_session_state(
    *,
    status: Any,
    camera: CameraState,
    filter_wheel: FilterWheelState,
    frames: list[FrameStat],
    catalog: DsoCatalog | None,
    config: ScoutConfig | None,
    now_utc: datetime,
) -> SessionState:
    """Best-effort session summary. NINA doesn't always tell you which
    target is active — we trust ``status.current_target`` when present,
    otherwise fall back to the most recent frame's target. Same for
    filter."""
    current_target_raw = getattr(status, "current_target", "") or ""
    if not current_target_raw and frames:
        # The plugin stores the target name on each frame as part of the
        # filename in some configurations; best we can do without it is
        # blank. UI shows "between targets" rather than hallucinating.
        current_target_raw = ""

    current_target = current_target_raw.strip()
    current_target_common = ""
    if catalog is not None and current_target:
        match = catalog.by_name(current_target)
        if match is not None:
            current_target = match.name
            current_target_common = match.common_name

    current_filter = filter_wheel.selected_name or (
        frames[0].filter_name if frames else ""
    )

    # Frame counter scoped to the current filter on this target. We
    # count frames in image-history whose filter matches current_filter
    # AND whose ExposureTime > 0 (skips flats / dark integration tests).
    frame_in_filter = 0
    if frames and current_filter:
        for f in frames:
            if f.filter_name == current_filter and f.exposure_s > 0:
                frame_in_filter += 1

    # NINA's Target Scheduler tracks "planned" frames per filter, but the
    # Advanced API doesn't expose it cleanly across versions. Phase 1
    # leaves frames_planned_in_filter=0 so the UI shows "frame N of ?".

    target_sets_in_min = _minutes_until_target_sets(
        catalog=catalog, target_name=current_target,
        config=config, now_utc=now_utc,
    )

    return SessionState(
        sequence_running=getattr(status, "sequence_running", False),
        current_target=current_target,
        current_target_common=current_target_common,
        current_filter=current_filter,
        frame_in_filter=frame_in_filter,
        frames_planned_in_filter=0,
        target_sets_in_min=target_sets_in_min,
    )


def _minutes_until_target_sets(
    *, catalog: DsoCatalog | None, target_name: str,
    config: ScoutConfig | None, now_utc: datetime,
) -> int | None:
    """Rough "minutes until target drops below the local altitude floor."
    Uses the existing observability evaluator at coarse 5-minute steps.
    Returns None if we can't determine (no catalog/config/match)."""
    if catalog is None or config is None or not target_name or not config.sites:
        return None
    target = catalog.by_name(target_name)
    if target is None:
        return None
    site = config.sites[0]
    # Walk forward in 5-minute steps; first step below the altitude floor
    # is the answer. Cap at 6 hours so we don't spin if the target is
    # circumpolar at this site.
    from datetime import timedelta
    from ..observability import altitude_deg
    floor = site.observing_window.min_altitude_deg
    for step in range(0, 6 * 12):    # 6h / 5min
        t = now_utc + timedelta(minutes=5 * step)
        alt = altitude_deg(
            target.ra_deg, target.dec_deg, t,
            site.observer.latitude_deg, site.observer.longitude_deg,
        )
        if alt < floor:
            return step * 5
    return None    # still up 6h from now


def _build_ledger_view(
    *, session: SessionState, catalog: DsoCatalog | None,
    captures_root: Path | None,
) -> TargetLedgerView | None:
    if catalog is None or captures_root is None or not session.current_target:
        return None
    target = catalog.by_name(session.current_target)
    if target is None:
        return None
    sessions = walk_sidecars(Path(captures_root))
    ledger = aggregate_ledger(sessions, catalog=catalog)
    per_filter: list[tuple[str, float, int, float]] = []
    total_cap = 0.0
    total_bud = 0
    for fname, budget in target.budget_minutes.items():
        ft = ledger.get(target.name, fname)
        captured = ft.total_minutes if ft else 0.0
        pct = (captured / budget * 100.0) if budget else 0.0
        per_filter.append((fname, captured, budget, pct))
        total_cap += min(float(budget), captured)
        total_bud += budget
    total_pct = (total_cap / total_bud * 100.0) if total_bud else 0.0
    return TargetLedgerView(
        target_name=target.name,
        common_name=target.common_name,
        per_filter=tuple(per_filter),
        total_captured=total_cap,
        total_budget=float(total_bud),
        total_pct=total_pct,
    )


def _derive_events(
    *, frames: list[FrameStat], focuser: FocuserState,
    filter_wheel: FilterWheelState, guider: GuiderState, status: Any,
) -> list[EventEntry]:
    """Best-effort event timeline from the state we already have.

    Phase 1 sources: last autofocus run, last dither, filter changes
    visible in the frame history. Phase 3 will add NINA's actual event
    log endpoint when we add that NinaClient method."""
    events: list[EventEntry] = []
    if focuser.last_af_utc is not None:
        before = focuser.last_af_hfr_before
        after = focuser.last_af_hfr_after
        if before is not None and after is not None:
            summary = f"autofocus  HFR {before:.2f} → {after:.2f}"
        else:
            summary = "autofocus complete"
        events.append(EventEntry(
            timestamp_utc=focuser.last_af_utc, kind="af", summary=summary,
        ))
    if guider.last_dither_utc is not None:
        events.append(EventEntry(
            timestamp_utc=guider.last_dither_utc, kind="dither",
            summary="dither",
        ))
    # Walk frames newest-to-oldest looking for filter changes — emit one
    # event per change. Skips runs of the same filter.
    last_filter = ""
    for f in frames:    # frames already newest-first
        if f.filter_name and f.filter_name != last_filter and last_filter:
            if f.timestamp_utc is not None:
                events.append(EventEntry(
                    timestamp_utc=f.timestamp_utc, kind="filter_change",
                    summary=f"filter → {last_filter}",
                ))
        if f.filter_name:
            last_filter = f.filter_name
    events.sort(key=lambda e: e.timestamp_utc, reverse=True)
    return events
