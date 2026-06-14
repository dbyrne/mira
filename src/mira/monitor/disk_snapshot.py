"""Build a MonitorSnapshot from FITS frames on disk — the no-NINA path.

This is the "snapshot fallback" the monitoring plan reserved (phase 5):
instead of NINA's image-history, it measures the frames Mira (or Syncthing)
already wrote to disk, via ``fits_stats.compute_frame_quality``. So
``mira status`` works on any capture dir — live, post-hoc, or on a machine
that never touched NINA.

What this path owns: the capture-session summary, per-frame quality
(stars / HFR / sky / roundness), a **transparency-gated** assessment
(clouds vs focus — the 2026-06-14 lesson), and the sky/observability clock.
Device states (mount/camera/...) are left disconnected — that's the
Phase-2 NINA overlay (``snapshot.build_snapshot``), which can be merged in
later behind ``--nina-url``.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..fits_stats import compute_frame_quality
from ..observability import (
    altitude_deg,
    azimuth_deg,
    moon_altitude_deg,
    moon_illumination,
    sun_altitude_deg,
)
from .snapshot import (
    Anomaly,
    CameraState,
    FilterWheelState,
    FocuserState,
    FrameStat,
    GuiderState,
    MonitorSnapshot,
    MountState,
    SessionState,
    SkyState,
)

SIDECAR = "mira_capture.json"


def _read_sidecar(dest: Path) -> dict:
    p = dest / SIDECAR
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _frame_time(path: Path) -> datetime:
    """Frame capture time: FITS DATE-OBS if present, else file mtime
    (mtime gets clobbered by in-place solving, DATE-OBS doesn't)."""
    try:
        from astropy.io import fits
        raw = fits.getheader(path).get("DATE-OBS")
        if raw:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        pass
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _light_frames(dest: Path) -> list[Path]:
    """Top-level *.fit* in dest, oldest-first by mtime. Excludes the
    cull's _rejected/ subdir (those aren't part of the live session)."""
    paths = [p for p in dest.glob("*.fit*") if p.is_file()]
    paths.sort(key=lambda p: p.stat().st_mtime)
    return paths


def _interp_obstruction(points: list[tuple[float, float]], az: float) -> float:
    """Linear-interpolate the horizon-mask altitude at azimuth `az`.
    `points` is (az, alt) sorted by az."""
    az %= 360.0
    for i in range(len(points) - 1):
        a0, h0 = points[i]
        a1, h1 = points[i + 1]
        if a0 <= az <= a1:
            return h0 + (h1 - h0) * (az - a0) / (a1 - a0) if a1 > a0 else h0
    return points[-1][1] if points else 0.0


def _compute_sky(
    ra: float, dec: float, now: datetime, lat: float, lon: float,
    alt_floor: float, sun_max: float,
    horizon_points: list[tuple[float, float]] | None,
) -> SkyState:
    alt = altitude_deg(ra, dec, now, lat, lon)
    az = azimuth_deg(ra, dec, now, lat, lon)
    clear = None
    if horizon_points:
        clear = alt > _interp_obstruction(horizon_points, az)
    # Walk forward in 5-min steps: when it drops below the floor (sets) and,
    # if currently dark, when the rising sun crosses the window cap (dawn).
    sets_in: int | None
    if alt < alt_floor:
        sets_in = 0  # already below the floor (setting / not yet risen)
    else:
        sets_in = None
        for step in range(1, 8 * 12):  # up to 8h
            t = now + timedelta(minutes=5 * step)
            if altitude_deg(ra, dec, t, lat, lon) < alt_floor:
                sets_in = step * 5
                break
    dawn_in = None
    if sun_altitude_deg(now, lat, lon) < sun_max:
        for step in range(1, 8 * 12):
            t = now + timedelta(minutes=5 * step)
            if sun_altitude_deg(t, lat, lon) > sun_max:
                dawn_in = step * 5
                break
    return SkyState(
        altitude_deg=alt, azimuth_deg=az, clear_of_obstruction=clear,
        sets_in_min=sets_in, dawn_in_min=dawn_in,
        moon_alt_deg=moon_altitude_deg(now, lat, lon),
        moon_illum_frac=moon_illumination(now),
    )


def assess_quality(
    frames: list[FrameStat], now: datetime, *, baseline_n: int = 6,
) -> list[Anomaly]:
    """Focus / transparency / tracking flags from the recent frames.

    The load-bearing rule (2026-06-14): **transparency gates focus.** Soft
    HFR + a crashed star count look identical to defocus, but if the star
    count is *swinging* frame-to-frame the sky is the variable, not the
    focuser — so we flag clouds and DON'T cry defocus."""
    out: list[Anomaly] = []
    if len(frames) < 3:
        return out
    # frames are newest-first; baseline = the OLDEST few we have on hand.
    recent = frames[: max(3, baseline_n)]
    stars = [f.stars for f in recent if f.stars is not None]
    hfrs = [f.hfr for f in recent if f.hfr is not None]
    rnds = [f.roundness for f in recent if f.roundness is not None]

    # --- transparency: high frame-to-frame star-count variance = clouds ---
    transparency_varying = False
    if len(stars) >= 3 and statistics.mean(stars) > 0:
        cv = statistics.pstdev(stars) / statistics.mean(stars)
        zero_frac = sum(1 for s in stars if s <= 2) / len(stars)
        if cv > 0.45 or zero_frac >= 0.34:
            transparency_varying = True
            out.append(Anomaly(
                section="frame", severity="amber",
                message="transparency varying — clouds?",
                detail=(f"star count swinging (cv={cv:.2f}, "
                        f"{int(zero_frac*100)}% near-zero) — sky transparency, "
                        "not focus. Don't autofocus into this."),
                fired_at=now,
            ))

    # --- focus: only trust HFR when the sky is steady ---
    if hfrs and not transparency_varying:
        med = statistics.median(hfrs)
        # fits_stats HFR is on the 2x2-binned grid; >~1.3 px is clearly soft
        # for the S30, ~0.9 is in focus. Absolute, since baseline may be soft too.
        if med > 1.3:
            out.append(Anomaly(
                section="frame", severity="amber",
                message=f"stars soft (HFR {med:.2f})",
                detail="HFR elevated and the sky looks steady — check focus.",
                fired_at=now,
            ))

    # --- tracking: consistently elongated stars (roundness) ---
    if len(rnds) >= 3:
        rmed = statistics.median(rnds)
        if rmed > 0.6:
            out.append(Anomaly(
                section="frame", severity="amber",
                message=f"stars elongated (round {rmed:.2f})",
                detail="possible trailing — check dither settle / tracking.",
                fired_at=now,
            ))
    return out


def _disconnected():
    return (
        MountState(connected=False, at_park=False, tracking=False,
                   slewing=False, ra_deg=None, dec_deg=None),
        CameraState(connected=False),
        FilterWheelState(connected=False),
        FocuserState(connected=False),
        GuiderState(connected=False),
    )


def build_snapshot_from_disk(
    dest_dir,
    *,
    latitude_deg: float | None = None,
    longitude_deg: float | None = None,
    alt_floor_deg: float | None = None,
    sun_max_deg: float | None = None,
    horizon_points: list[tuple[float, float]] | None = None,
    recent_n: int = 15,
    live_gap_s: float | None = None,
    now_utc: datetime | None = None,
) -> MonitorSnapshot:
    """Measure the capture dir `dest_dir` into a MonitorSnapshot (mode='disk').

    `live_gap_s`: how stale the newest frame can be before the session reads
    as idle/done rather than live. Defaults to 2x exposure + 120s."""
    now = now_utc or datetime.now(timezone.utc)
    dest = Path(dest_dir)
    sc = _read_sidecar(dest)
    exposure = float(sc.get("exposure_s") or 0.0)
    gain = sc.get("gain")
    filt = sc.get("filter") or ""
    target = (sc.get("target_name") or "").strip()
    ra = sc.get("ra_deg")
    dec = sc.get("dec_deg")
    # The capture sidecar self-describes the session — pull site geometry
    # (lat/lon/floor/sun-cap) and dither cadence from its `config` block so
    # `mira status` needs no --config. Explicit args still override.
    cfg = sc.get("config") or {}
    lat = latitude_deg if latitude_deg is not None else cfg.get("lat_deg")
    lon = longitude_deg if longitude_deg is not None else cfg.get("lon_deg")
    floor = alt_floor_deg if alt_floor_deg is not None else float(cfg.get("alt_floor_deg", 30.0))
    sun_cap = sun_max_deg if sun_max_deg is not None else float(cfg.get("sun_max_deg", -15.0))
    dither_every = cfg.get("dither_every")

    all_paths = _light_frames(dest)
    total = len(all_paths)
    started = _frame_time(all_paths[0]) if all_paths else None
    frames: list[FrameStat] = []
    for p in all_paths[-recent_n:]:
        fq = compute_frame_quality(p, target_ra=ra, target_dec=dec)
        ts = fq.date_obs or datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        frames.append(FrameStat(
            filename=p.name, timestamp_utc=ts, exposure_s=exposure, gain=gain,
            filter_name=filt, stars=fq.stars, hfr=fq.hfr,
            mean=fq.sky_median, median=fq.sky_median, roundness=fq.roundness,
        ))
    frames.reverse()  # newest-first (snapshot convention)

    gap = live_gap_s if live_gap_s is not None else max(exposure * 2 + 120, 180)
    last_ts = frames[0].timestamp_utc if frames else None
    live = bool(last_ts and (now - last_ts).total_seconds() < gap)

    sky = None
    if lat is not None and lon is not None and ra is not None and dec is not None:
        sky = _compute_sky(float(ra), float(dec), now, float(lat),
                           float(lon), floor, sun_cap, horizon_points)

    session = SessionState(
        sequence_running=live, current_target=target, current_filter=filt,
        frame_in_filter=total, started_utc=started,
        target_sets_in_min=(sky.sets_in_min if sky else None),
        dither_every=dither_every,
    )
    mount, camera, wheel, focuser, guider = _disconnected()
    return MonitorSnapshot(
        generated_utc=now, mode="disk", nina_reachable=False, nina_error="",
        session=session, mount=mount, camera=camera, filter_wheel=wheel,
        focuser=focuser, guider=guider, recent_frames=tuple(frames),
        ledger_view=None, recent_events=(),
        anomalies=tuple(assess_quality(frames, now)), sky=sky,
    )


def _overlay_devices(disk_snap: MonitorSnapshot,
                     nina_snap: MonitorSnapshot) -> MonitorSnapshot:
    """Pure merge: live device-state from `nina_snap` onto the disk snapshot.

    The disk path keeps frame quality / sky / session / anomalies (measured
    from the FITS — better than NINA's image-history HFR); NINA contributes the
    device states + event log. An unreachable NINA only annotates the error."""
    import dataclasses
    if not nina_snap.nina_reachable:
        return dataclasses.replace(
            disk_snap, nina_reachable=False, nina_error=nina_snap.nina_error)
    return dataclasses.replace(
        disk_snap, mode="live", nina_reachable=True,
        nina_error=nina_snap.nina_error,
        mount=nina_snap.mount, camera=nina_snap.camera,
        filter_wheel=nina_snap.filter_wheel, focuser=nina_snap.focuser,
        guider=nina_snap.guider, recent_events=nina_snap.recent_events,
    )


def merge_nina_devices(disk_snap: MonitorSnapshot, nina_client) -> MonitorSnapshot:
    """Overlay LIVE NINA device-state onto a disk snapshot (Phase 2).
    Fail-soft: an unreachable / erroring NINA leaves the disk snapshot intact."""
    from .snapshot import build_snapshot
    try:
        nina = build_snapshot(nina_client)
    except Exception:  # noqa: BLE001 — monitoring must never raise
        return disk_snap
    return _overlay_devices(disk_snap, nina)
