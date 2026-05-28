"""Tests for monitor.anomaly — pin every detection rule and the
hysteresis behavior."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest import TestCase

from mira.monitor.anomaly import (
    DEFAULT_CONFIG,
    AnomalyConfig,
    attach_anomalies,
    detect_anomalies,
)
from mira.monitor.snapshot import (
    Anomaly,
    CameraState,
    FilterWheelState,
    FocuserState,
    FrameStat,
    GuiderState,
    MonitorSnapshot,
    MountState,
    SessionState,
)


NOW = datetime(2026, 5, 26, 3, 0, tzinfo=timezone.utc)


def _frame(hfr: float | None = 2.4, stars: int | None = 400,
           t_offset_min: int = 0) -> FrameStat:
    return FrameStat(
        filename=f"f_{t_offset_min}.fit",
        timestamp_utc=NOW - timedelta(minutes=t_offset_min),
        exposure_s=300.0, gain=100, filter_name="Ha",
        stars=stars, hfr=hfr, mean=1340.0, median=1330.0,
    )


def _snapshot(
    *,
    frames=(),
    guide_rms=None,
    camera_temp=None,
    camera_setpoint=None,
    filter_name="Ha",
    sequence_running=True,
    target_sets_in=None,
) -> MonitorSnapshot:
    return MonitorSnapshot(
        generated_utc=NOW,
        mode="test",
        nina_reachable=True,
        nina_error="",
        session=SessionState(
            sequence_running=sequence_running,
            current_target="NGC 6888", current_target_common="Crescent",
            current_filter=filter_name,
            target_sets_in_min=target_sets_in,
        ),
        mount=MountState(connected=True, at_park=False, tracking=True,
                         slewing=False, ra_deg=303.0, dec_deg=38.0),
        camera=CameraState(connected=True, state="Exposing",
                           temp_c=camera_temp, setpoint_c=camera_setpoint),
        filter_wheel=FilterWheelState(connected=True, selected_name=filter_name),
        focuser=FocuserState(connected=True),
        guider=GuiderState(connected=True, is_guiding=True,
                           rms_total_arcsec=guide_rms),
        recent_frames=tuple(frames),
        ledger_view=None,
        recent_events=(),
        anomalies=(),
    )


class HfrAnomalyTests(TestCase):
    def test_no_baseline_yet_no_anomaly(self) -> None:
        # Only 5 frames: baseline_frames=10 → no detection. Returns empty.
        frames = [_frame(hfr=3.5, t_offset_min=i) for i in range(5)]
        anoms = detect_anomalies(_snapshot(frames=frames))
        self.assertEqual([a for a in anoms if a.section == "frame"], [])

    def test_amber_at_1_5x_baseline(self) -> None:
        # 10 baseline frames at 2.0, then 3 recent at 3.0 (= 1.5x).
        recent = [_frame(hfr=3.0, t_offset_min=i) for i in range(3)]
        baseline = [_frame(hfr=2.0, t_offset_min=i + 3) for i in range(10)]
        frames = recent + baseline    # newest-first
        anoms = detect_anomalies(_snapshot(frames=frames))
        hfr_anoms = [a for a in anoms if a.section == "frame"
                     and "HFR" in a.message]
        self.assertEqual(len(hfr_anoms), 1)
        self.assertEqual(hfr_anoms[0].severity, "amber")

    def test_red_at_2x_baseline(self) -> None:
        recent = [_frame(hfr=4.5, t_offset_min=i) for i in range(3)]
        baseline = [_frame(hfr=2.0, t_offset_min=i + 3) for i in range(10)]
        frames = recent + baseline
        anoms = detect_anomalies(_snapshot(frames=frames))
        hfr_red = [a for a in anoms if a.section == "frame"
                   and a.severity == "red" and "HFR" in a.message]
        self.assertEqual(len(hfr_red), 1)

    def test_single_bad_frame_does_not_fire(self) -> None:
        # Sustained_frames=3; one outlier shouldn't trip the anomaly.
        recent = [_frame(hfr=4.5, t_offset_min=0),
                  _frame(hfr=2.0, t_offset_min=1),
                  _frame(hfr=2.0, t_offset_min=2)]
        baseline = [_frame(hfr=2.0, t_offset_min=i + 3) for i in range(10)]
        frames = recent + baseline
        anoms = detect_anomalies(_snapshot(frames=frames))
        self.assertEqual([a for a in anoms if a.section == "frame"
                          and "HFR" in a.message], [])


class StarsAnomalyTests(TestCase):
    def test_red_at_80pct_drop(self) -> None:
        recent = [_frame(stars=60, t_offset_min=i) for i in range(3)]
        baseline = [_frame(stars=400, t_offset_min=i + 3) for i in range(10)]
        anoms = detect_anomalies(_snapshot(frames=recent + baseline))
        red = [a for a in anoms if a.section == "frame"
               and "stars" in a.message and a.severity == "red"]
        self.assertEqual(len(red), 1)

    def test_amber_at_50pct_drop(self) -> None:
        recent = [_frame(stars=180, t_offset_min=i) for i in range(3)]
        baseline = [_frame(stars=400, t_offset_min=i + 3) for i in range(10)]
        anoms = detect_anomalies(_snapshot(frames=recent + baseline))
        amber = [a for a in anoms if a.section == "frame"
                 and "stars" in a.message and a.severity == "amber"]
        self.assertEqual(len(amber), 1)


class GuidingAnomalyTests(TestCase):
    def test_amber_at_1_5_arcsec(self) -> None:
        snap = _snapshot(guide_rms=1.7)
        anoms = detect_anomalies(snap)
        self.assertEqual(
            [a.severity for a in anoms if a.section == "guiding"],
            ["amber"],
        )

    def test_red_at_3_arcsec(self) -> None:
        snap = _snapshot(guide_rms=3.5)
        anoms = detect_anomalies(snap)
        self.assertEqual(
            [a.severity for a in anoms if a.section == "guiding"],
            ["red"],
        )

    def test_clean_below_threshold(self) -> None:
        snap = _snapshot(guide_rms=0.5)
        self.assertEqual([a for a in detect_anomalies(snap)
                          if a.section == "guiding"], [])


class CameraTempAnomalyTests(TestCase):
    def test_amber_at_2_deg_drift(self) -> None:
        snap = _snapshot(camera_temp=-7.5, camera_setpoint=-10.0)
        anoms = detect_anomalies(snap)
        cam = [a for a in anoms if a.section == "camera"]
        self.assertEqual(len(cam), 1)
        self.assertEqual(cam[0].severity, "amber")

    def test_red_at_4_deg_drift(self) -> None:
        snap = _snapshot(camera_temp=-5.0, camera_setpoint=-10.0)
        anoms = detect_anomalies(snap)
        cam = [a for a in anoms if a.section == "camera"]
        self.assertEqual(cam[0].severity, "red")

    def test_no_setpoint_no_anomaly(self) -> None:
        snap = _snapshot(camera_temp=-7.5, camera_setpoint=None)
        self.assertEqual([a for a in detect_anomalies(snap)
                          if a.section == "camera"], [])


class SessionStalledTests(TestCase):
    def test_no_frame_in_window_is_red(self) -> None:
        # Last frame 20 min ago, exposure was 300s → expected ≤ 660s.
        snap = _snapshot(frames=[
            FrameStat(
                filename="old.fit",
                timestamp_utc=NOW - timedelta(minutes=20),
                exposure_s=300.0, gain=100, filter_name="Ha",
                stars=400, hfr=2.4, mean=1340.0, median=1330.0,
            )
        ])
        anoms = detect_anomalies(snap)
        sess = [a for a in anoms if a.section == "session"]
        self.assertEqual(len(sess), 1)
        self.assertEqual(sess[0].severity, "red")

    def test_recent_frame_no_anomaly(self) -> None:
        snap = _snapshot(frames=[_frame(t_offset_min=0)])
        self.assertEqual([a for a in detect_anomalies(snap)
                          if a.section == "session"], [])


class FilterCanonicalTests(TestCase):
    def test_non_canonical_filter_fires_red(self) -> None:
        snap = _snapshot(filter_name="H-alpha")
        anoms = detect_anomalies(snap)
        filt = [a for a in anoms if a.section == "filter"]
        self.assertEqual(len(filt), 1)
        self.assertEqual(filt[0].severity, "red")
        self.assertIn("H-alpha", filt[0].message)

    def test_dark_position_tolerated(self) -> None:
        snap = _snapshot(filter_name="Dark")
        self.assertEqual([a for a in detect_anomalies(snap)
                          if a.section == "filter"], [])

    def test_canonical_filter_no_anomaly(self) -> None:
        for f in ("Ha", "OIII", "SII", "L", "R", "G", "B", "V"):
            with self.subTest(f=f):
                snap = _snapshot(filter_name=f)
                self.assertEqual([a for a in detect_anomalies(snap)
                                  if a.section == "filter"], [])


class TargetSettingTests(TestCase):
    def test_amber_when_setting_in_15_min(self) -> None:
        snap = _snapshot(target_sets_in=15)
        anoms = detect_anomalies(snap)
        tgt = [a for a in anoms if a.section == "target"]
        self.assertEqual(tgt[0].severity, "amber")

    def test_red_when_already_below(self) -> None:
        snap = _snapshot(target_sets_in=0)
        anoms = detect_anomalies(snap)
        tgt = [a for a in anoms if a.section == "target"]
        self.assertEqual(tgt[0].severity, "red")

    def test_no_anomaly_when_high_up(self) -> None:
        snap = _snapshot(target_sets_in=180)
        self.assertEqual([a for a in detect_anomalies(snap)
                          if a.section == "target"], [])


class HysteresisTests(TestCase):
    def test_previous_anomaly_kept_briefly_after_clear(self) -> None:
        # A previous amber that just fired (1s ago) should persist on the
        # next refresh even if the underlying condition is gone.
        prev = (Anomaly(
            section="guiding", severity="amber",
            message="guide RMS 1.7″", detail="...",
            fired_at=NOW - timedelta(seconds=1),
        ),)
        snap = _snapshot(guide_rms=0.4)    # clean now
        anoms = detect_anomalies(snap, previous=prev)
        self.assertTrue(
            any(a.section == "guiding" and "guide RMS 1.7" in a.message
                for a in anoms),
            "previous anomaly should still be visible under hysteresis",
        )

    def test_previous_anomaly_expires_after_hysteresis_window(self) -> None:
        # Same setup but fired long enough ago to clear.
        prev = (Anomaly(
            section="guiding", severity="amber",
            message="guide RMS 1.7″", detail="...",
            fired_at=NOW - timedelta(minutes=2),
        ),)
        snap = _snapshot(guide_rms=0.4)
        anoms = detect_anomalies(snap, previous=prev)
        self.assertEqual([a for a in anoms if a.section == "guiding"], [])

    def test_attach_anomalies_returns_new_snapshot(self) -> None:
        snap = _snapshot(guide_rms=2.0)
        attached = attach_anomalies(snap)
        self.assertEqual(snap.anomalies, ())
        self.assertGreater(len(attached.anomalies), 0)
