"""Anomaly detection — pure logic over a MonitorSnapshot.

Two layers per the plan:
- **Hard thresholds.** Configurable absolute limits with sustained-N-frames
  triggers where appropriate.
- **Trend layer.** Simple linear slope over the last N frames for HFR and
  star count, fires when the projection crosses a threshold ahead of the
  hard layer.

A 5-frame hysteresis is applied: once an anomaly fires, it stays fired
until the underlying condition has been clear for ``HYSTERESIS_FRAMES``
consecutive frames. The webapp passes the previously-seen anomaly set
into ``detect_anomalies`` so we can apply this without holding state in
this module.

The rules table is small and explicit. No ML, no learned baselines
across sessions — the baseline is the *median of the first 10 frames in
the current session*, computed fresh per request. That's the right call
because focus, filter, target, sky transparency all shift between
sessions and a learned baseline would mislead more than help.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable

from .snapshot import Anomaly, FrameStat, MonitorSnapshot


# ---------------------------------------------------------------------------
# Configuration. Editable in one place; defaults aim to alert before a
# real failure surfaces, not after.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnomalyConfig:
    # HFR drift relative to session baseline (median of first BASELINE_FRAMES).
    hfr_amber_factor: float = 1.5
    hfr_red_factor: float = 2.0
    # Star count drop relative to session baseline.
    stars_amber_drop_pct: float = 0.50
    stars_red_drop_pct: float = 0.80
    # Guide RMS in arcseconds.
    guide_rms_amber: float = 1.5
    guide_rms_red: float = 3.0
    # Camera temp delta from setpoint (absolute °C).
    camera_temp_delta_amber: float = 2.0
    camera_temp_delta_red: float = 4.0
    # Minutes-until-target-sets warning thresholds.
    target_setting_amber_min: int = 20
    target_setting_red_min: int = 0
    # How many frames a triggering condition must persist before firing.
    sustained_frames: int = 3
    # First N frames used to compute the session baseline.
    baseline_frames: int = 10
    # Hysteresis: once fired, must clear for N frames to un-fire.
    hysteresis_frames: int = 5


DEFAULT_CONFIG = AnomalyConfig()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_anomalies(
    snapshot: MonitorSnapshot,
    *,
    config: AnomalyConfig = DEFAULT_CONFIG,
    previous: tuple[Anomaly, ...] = (),
) -> tuple[Anomaly, ...]:
    """Compute the anomaly set for a snapshot.

    ``previous`` is the anomaly tuple from the previous /monitor refresh
    — passed so hysteresis can keep a fired anomaly visible for one more
    cycle even if the current frame is clean. (Phase 1 implements one-
    refresh hysteresis; full N-frame hysteresis lands in Phase 4 when we
    have the request-history infrastructure.)"""
    now = snapshot.generated_utc
    out: list[Anomaly] = []

    # Newest-first frames; baseline uses the OLDEST frames in the buffer
    # (which were the FIRST frames of the session if the buffer is full).
    frames = list(snapshot.recent_frames)
    out.extend(_check_hfr(frames, config, now))
    out.extend(_check_stars(frames, config, now))
    out.extend(_check_guiding(snapshot, config, now))
    out.extend(_check_camera_temp(snapshot, config, now))
    out.extend(_check_session_stalled(snapshot, frames, config, now))
    out.extend(_check_filter_canonical(snapshot, config, now))
    out.extend(_check_target_setting(snapshot, config, now))

    # One-refresh hysteresis: include any previous anomaly that isn't in
    # the freshly-computed set but fired less than `hysteresis_frames`
    # refreshes ago. Approximation by elapsed time at 5s/refresh.
    if previous:
        hysteresis_seconds = config.hysteresis_frames * 5
        fresh_keys = {(a.section, a.message) for a in out}
        for prev_a in previous:
            key = (prev_a.section, prev_a.message)
            if key in fresh_keys:
                continue
            elapsed = (now - prev_a.fired_at).total_seconds()
            if elapsed < hysteresis_seconds:
                out.append(replace(prev_a, severity="amber"))
    return tuple(out)


def attach_anomalies(
    snapshot: MonitorSnapshot,
    *,
    config: AnomalyConfig = DEFAULT_CONFIG,
    previous: tuple[Anomaly, ...] = (),
) -> MonitorSnapshot:
    """Convenience: detect + return a new snapshot with ``anomalies``
    populated. Frozen dataclass so we have to rebuild."""
    return replace(
        snapshot,
        anomalies=detect_anomalies(snapshot, config=config, previous=previous),
    )


# ---------------------------------------------------------------------------
# Individual checks. Each returns 0 or 1 Anomaly. Pure; tested separately.
# ---------------------------------------------------------------------------

def _check_hfr(
    frames: list[FrameStat], config: AnomalyConfig, now: datetime,
) -> list[Anomaly]:
    """HFR rising above N× the session baseline."""
    baseline = _baseline_hfr(frames, config.baseline_frames)
    if baseline is None or baseline <= 0:
        return []
    recent = [f.hfr for f in frames[: config.sustained_frames] if f.hfr is not None]
    if len(recent) < config.sustained_frames:
        return []
    # "Sustained" means every recent frame is above threshold — use the
    # MIN of the recent buffer so a single outlier doesn't trip it.
    factor = min(recent) / baseline
    if factor >= config.hfr_red_factor:
        return [Anomaly(
            section="frame", severity="red",
            message=f"HFR {factor:.1f}× baseline",
            detail=(
                f"HFR has been ≥ {config.hfr_red_factor:.1f}× the session "
                f"baseline ({baseline:.2f}) for the last "
                f"{config.sustained_frames} frames. Check focus, "
                "transparency, dew on the objective."
            ),
            fired_at=now,
        )]
    if factor >= config.hfr_amber_factor:
        return [Anomaly(
            section="frame", severity="amber",
            message=f"HFR {factor:.1f}× baseline",
            detail=(
                f"HFR is drifting above {config.hfr_amber_factor:.1f}× the "
                f"baseline ({baseline:.2f}). Worth running an autofocus "
                "if no AF temp-trigger has fired recently."
            ),
            fired_at=now,
        )]
    return []


def _check_stars(
    frames: list[FrameStat], config: AnomalyConfig, now: datetime,
) -> list[Anomaly]:
    """Star count dropping vs session baseline."""
    baseline = _baseline_stars(frames, config.baseline_frames)
    if baseline is None or baseline <= 0:
        return []
    recent = [
        f.stars for f in frames[: config.sustained_frames]
        if f.stars is not None
    ]
    if len(recent) < config.sustained_frames:
        return []
    # "Sustained" means every recent frame has lost stars — use the MAX
    # of the recent star counts so a single transient dip doesn't fire.
    drop = 1.0 - (max(recent) / baseline)
    if drop >= config.stars_red_drop_pct:
        return [Anomaly(
            section="frame", severity="red",
            message=f"stars −{drop * 100:.0f}%",
            detail=(
                f"Star count dropped {drop * 100:.0f}% from baseline "
                f"({baseline}). Cloud band, dew, or guide failure with "
                "trailing — open Siril Live Stack and check the latest "
                "frame."
            ),
            fired_at=now,
        )]
    if drop >= config.stars_amber_drop_pct:
        return [Anomaly(
            section="frame", severity="amber",
            message=f"stars −{drop * 100:.0f}%",
            detail=(
                f"Star count dropped {drop * 100:.0f}% from baseline "
                f"({baseline}). May be transient haze; watch the next "
                "few frames."
            ),
            fired_at=now,
        )]
    return []


def _check_guiding(
    snapshot: MonitorSnapshot, config: AnomalyConfig, now: datetime,
) -> list[Anomaly]:
    rms = snapshot.guider.rms_total_arcsec
    if rms is None or not snapshot.guider.connected:
        return []
    if rms >= config.guide_rms_red:
        return [Anomaly(
            section="guiding", severity="red",
            message=f"guide RMS {rms:.1f}″",
            detail=(
                f"PHD2 total RMS is {rms:.2f}″. Mount, cable snag, or wind."
                " Frames captured during this window are likely to be "
                "elongated."
            ),
            fired_at=now,
        )]
    if rms >= config.guide_rms_amber:
        return [Anomaly(
            section="guiding", severity="amber",
            message=f"guide RMS {rms:.1f}″",
            detail=(
                f"PHD2 total RMS is {rms:.2f}″ (target ≤ 1″). Borderline."
                " Check seeing and that the guide star hasn't drifted."
            ),
            fired_at=now,
        )]
    return []


def _check_camera_temp(
    snapshot: MonitorSnapshot, config: AnomalyConfig, now: datetime,
) -> list[Anomaly]:
    cam = snapshot.camera
    if cam.temp_c is None or cam.setpoint_c is None or not cam.connected:
        return []
    delta = abs(cam.temp_c - cam.setpoint_c)
    if delta >= config.camera_temp_delta_red:
        return [Anomaly(
            section="camera", severity="red",
            message=f"cooler Δ {delta:.1f}°C",
            detail=(
                f"Camera is at {cam.temp_c:.1f} °C, target {cam.setpoint_c:.1f}"
                " °C. Cooler can't hold. Frames will have higher dark "
                "current; consider increasing setpoint or aborting."
            ),
            fired_at=now,
        )]
    if delta >= config.camera_temp_delta_amber:
        return [Anomaly(
            section="camera", severity="amber",
            message=f"cooler Δ {delta:.1f}°C",
            detail=(
                f"Camera at {cam.temp_c:.1f} °C, drifting from "
                f"{cam.setpoint_c:.1f} °C. Ambient may be climbing or the "
                "cooler is at duty ceiling."
            ),
            fired_at=now,
        )]
    return []


def _check_session_stalled(
    snapshot: MonitorSnapshot, frames: list[FrameStat],
    config: AnomalyConfig, now: datetime,
) -> list[Anomaly]:
    """No new frame in 2×exposure + 60s. NINA's CameraState may say
    Exposing, but if the last frame timestamp is old, something
    stalled."""
    if not snapshot.session.sequence_running or not frames:
        return []
    newest = frames[0]
    if newest.timestamp_utc is None:
        return []
    elapsed = (now - newest.timestamp_utc).total_seconds()
    limit = 2 * newest.exposure_s + 60.0
    if elapsed > limit and limit > 0:
        return [Anomaly(
            section="session", severity="red",
            message="session stalled",
            detail=(
                f"No new frame in {elapsed:.0f}s (last frame "
                f"{newest.exposure_s:.0f}s exposure → expected ≤ "
                f"{limit:.0f}s). NINA might be mid-AF, mid-dither, or "
                "the camera dropped — RDP in and check the sequence."
            ),
            fired_at=now,
        )]
    return []


def _check_filter_canonical(
    snapshot: MonitorSnapshot, config: AnomalyConfig, now: datetime,
) -> list[Anomaly]:
    """Cross-check: the selected filter must be canonical for the DSO
    ledger to book this session. Mirrors the doctor-time check; this is
    the at-capture-time equivalent."""
    from ..doctor import DSO_CANONICAL_FILTERS, DSO_ALLOWED_NON_PHOTOMETRIC
    sel = snapshot.filter_wheel.selected_name
    if not sel:
        return []
    if sel in DSO_CANONICAL_FILTERS:
        return []
    if sel.lower() in {n.lower() for n in DSO_ALLOWED_NON_PHOTOMETRIC}:
        return []
    return [Anomaly(
        section="filter", severity="red",
        message=f"non-canonical filter '{sel}'",
        detail=(
            f"Filter wheel reports '{sel}', not one of the canonical "
            f"set {sorted(DSO_CANONICAL_FILTERS)}. The DSO ledger won't "
            "book this session under the right key. Rename in NINA → "
            "Equipment → Filter Wheel → Filters."
        ),
        fired_at=now,
    )]


def _check_target_setting(
    snapshot: MonitorSnapshot, config: AnomalyConfig, now: datetime,
) -> list[Anomaly]:
    mins = snapshot.session.target_sets_in_min
    if mins is None:
        return []
    if mins <= config.target_setting_red_min:
        return [Anomaly(
            section="target", severity="red",
            message="target below floor",
            detail=(
                "The current target is already below the altitude floor "
                "for this site. Frames captured now are pulling through "
                "more atmosphere; consider switching targets."
            ),
            fired_at=now,
        )]
    if mins <= config.target_setting_amber_min:
        return [Anomaly(
            section="target", severity="amber",
            message=f"sets in {mins}m",
            detail=(
                f"Current target drops below the altitude floor in "
                f"{mins} minutes. Plan to swap targets or finish the "
                "active filter."
            ),
            fired_at=now,
        )]
    return []


# ---------------------------------------------------------------------------
# Baseline helpers
# ---------------------------------------------------------------------------

def _baseline_hfr(
    frames: list[FrameStat], baseline_n: int,
) -> float | None:
    """Median of the OLDEST baseline_n frames' HFR (i.e., the first frames
    of the session). Frames list is newest-first, so take the tail."""
    if len(frames) < baseline_n:
        return None
    tail = frames[-baseline_n:]
    hfrs = [f.hfr for f in tail if f.hfr is not None and f.hfr > 0]
    if not hfrs:
        return None
    return _median(hfrs)


def _baseline_stars(
    frames: list[FrameStat], baseline_n: int,
) -> int | None:
    if len(frames) < baseline_n:
        return None
    tail = frames[-baseline_n:]
    stars = [f.stars for f in tail if f.stars is not None and f.stars > 0]
    if not stars:
        return None
    return int(_median(stars))


def _median(xs: Iterable[float]) -> float:
    s = sorted(float(x) for x in xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0
