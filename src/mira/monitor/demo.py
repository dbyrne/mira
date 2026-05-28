"""Demo snapshot generator — realistic in-progress narrowband session.

Used by ``/monitor?demo=1`` so the console can be verified visually
without a live NINA. The data is canned but plausible: NGC 6888 mid-Ha,
~12 frames in, healthy guiding but one mild HFR amber anomaly to show
how the badges render.

Demo mode is also useful for documentation screenshots and for quick
template iteration without standing up the rig.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from ..dso.catalog import DsoCatalog, DsoTarget
from .anomaly import attach_anomalies
from .snapshot import (
    Anomaly,
    CameraState,
    EventEntry,
    FilterWheelState,
    FocuserState,
    FrameStat,
    GuiderState,
    MonitorSnapshot,
    MountState,
    SessionState,
    TargetLedgerView,
)


# A small synthetic catalog used for the ledger view even if the real
# catalog isn't loaded. Mirrors NGC 6888's real entry in sho_targets.yaml
# so the rendering matches what a real session would show.
_DEMO_TARGET = DsoTarget(
    name="NGC 6888",
    common_name="Crescent Nebula",
    object_type="WR",
    ra_deg=303.025,
    dec_deg=38.35,
    size_arcmin=(18, 13),
    constellation="Cyg",
    budget_minutes={"Ha": 600, "OIII": 900, "SII": 540},
    notes="OIII shell is the headline",
)


def demo_snapshot(*, now_utc: datetime | None = None) -> MonitorSnapshot:
    """Build a deterministic demo MonitorSnapshot.

    ``now_utc`` defaults to a fixed timestamp so screenshots are
    reproducible. Pass ``datetime.now(timezone.utc)`` if you want the
    demo to drift with real time."""
    now = now_utc or datetime.now(timezone.utc)
    session_start = now - timedelta(hours=1, minutes=12)

    frames = _demo_frames(now=now, session_start=session_start)
    events = _demo_events(now=now)

    session = SessionState(
        sequence_running=True,
        current_target="NGC 6888",
        current_target_common="Crescent Nebula",
        current_filter="Ha",
        frame_in_filter=12,
        frames_planned_in_filter=40,
        target_sets_in_min=167,  # ~2h 47m
    )
    mount = MountState(
        connected=True, at_park=False, tracking=True, slewing=False,
        ra_deg=303.025, dec_deg=38.35, pier_side="East",
    )
    camera = CameraState(
        connected=True, state="Exposing",
        temp_c=-10.0, setpoint_c=-10.0, cooler_power=0.41,
    )
    filter_wheel = FilterWheelState(
        connected=True, is_moving=False, selected_name="Ha",
        available=("L", "R", "G", "B", "V", "Ha", "OIII"),
    )
    focuser = FocuserState(
        connected=True, is_moving=False,
        position=15234, temperature_c=14.8,
        last_af_utc=now - timedelta(minutes=18),
        last_af_hfr_before=3.12, last_af_hfr_after=2.41,
        last_af_position=15234,
    )
    guider = GuiderState(
        connected=True, is_guiding=True,
        rms_total_arcsec=0.46, rms_ra_arcsec=0.31, rms_dec_arcsec=0.34,
        last_dither_utc=now - timedelta(seconds=18),
    )
    ledger_view = TargetLedgerView(
        target_name="NGC 6888",
        common_name="Crescent Nebula",
        per_filter=(
            ("Ha", 60.0, 600, 10.0),
            ("OIII", 0.0, 900, 0.0),
            ("SII", 0.0, 540, 0.0),
        ),
        total_captured=60.0,
        total_budget=2040.0,
        total_pct=2.94,
    )

    snap = MonitorSnapshot(
        generated_utc=now,
        mode="demo",
        nina_reachable=True,
        nina_error="",
        session=session,
        mount=mount,
        camera=camera,
        filter_wheel=filter_wheel,
        focuser=focuser,
        guider=guider,
        recent_frames=frames,
        ledger_view=ledger_view,
        recent_events=tuple(events),
        anomalies=(),
    )
    return attach_anomalies(snap)


def demo_catalog() -> DsoCatalog:
    """The minimal catalog the demo uses when the real one isn't loaded."""
    return DsoCatalog(version="demo", defaults={}, targets=(_DEMO_TARGET,))


# ---------------------------------------------------------------------------
# Frame + event generators — deterministic so screenshots are reproducible.
# ---------------------------------------------------------------------------

def _demo_frames(
    *, now: datetime, session_start: datetime,
) -> tuple[FrameStat, ...]:
    """12 Ha frames spaced 5 minutes apart, with a slow HFR rise across
    the last 3 to demonstrate the amber-trend anomaly without tripping
    the red threshold."""
    rng = random.Random(20260601)    # fixed seed
    frames: list[FrameStat] = []
    for i in range(12):
        t = session_start + timedelta(minutes=12 + i * 5)
        # Baseline HFR ~2.4 with mild noise; last 3 frames climb steeply
        # past the 2× red threshold. Demoing the worst-case alert path is
        # more valuable than demoing a flawless night — the user wants to
        # see what a real "check the rig" badge looks like.
        if i < 9:
            hfr = 2.40 + rng.uniform(-0.10, 0.10)
        else:
            hfr = 3.70 + (i - 8) * 0.95 + rng.uniform(-0.05, 0.05)
        # Stars correspondingly drop hard on the worse frames so the
        # stars-drop anomaly fires alongside.
        if i < 9:
            stars = int(410 + rng.uniform(-15, 15))
        else:
            stars = int(280 + rng.uniform(-12, 12) - (i - 8) * 20)
        frames.append(FrameStat(
            filename=f"NGC_6888_Ha_300s_{i+1:03d}.fits",
            timestamp_utc=t,
            exposure_s=300.0,
            gain=100,
            filter_name="Ha",
            stars=stars,
            hfr=round(hfr, 2),
            mean=round(1340 + rng.uniform(-30, 30), 1),
            median=round(1330 + rng.uniform(-30, 30), 1),
        ))
    # newest-first
    frames.reverse()
    return tuple(frames)


def _demo_events(*, now: datetime) -> list[EventEntry]:
    # Newest-first to match the real ``_derive_events`` ordering — the
    # UI shows them top-to-bottom, freshest first.
    return [
        EventEntry(
            timestamp_utc=now - timedelta(seconds=18),
            kind="dither",
            summary="dither (random walk 12px)",
        ),
        EventEntry(
            timestamp_utc=now - timedelta(minutes=18),
            kind="af",
            summary="autofocus  HFR 3.12 → 2.41",
        ),
        EventEntry(
            timestamp_utc=now - timedelta(minutes=37),
            kind="plate_solve",
            summary="centered  Δ 0.4'",
        ),
        EventEntry(
            timestamp_utc=now - timedelta(minutes=42),
            kind="filter_change",
            summary="filter → Ha (confirmed)",
        ),
    ]
