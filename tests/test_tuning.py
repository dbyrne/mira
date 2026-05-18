"""Tests for capture tuning. No NINA — an injected fake client drives
run_tune; recommend/format_report are pure."""
from __future__ import annotations

from unittest import TestCase

from mira.tuning import (
    SAT_LIMIT,
    FrameStat,
    format_report,
    recommend,
    run_tune,
)


class FakeClient:
    def __init__(self, stats_for):
        self.calls: list[tuple] = []
        self._stats_for = stats_for
        self._last = None

    def wait_camera_idle(self, timeout_s: float = 90.0, poll_s: float = 1.0) -> bool:
        return True

    def capture(self, *, duration, gain=None, save=True, solve=False,
                target_name="", timeout_s=180.0):
        self.calls.append((gain, duration))
        s = self._stats_for(gain, duration)
        if isinstance(s, Exception):
            raise s
        self._last = s
        return {"Response": "ok"}

    def latest_image_stats(self):
        return self._last


def _stats(max_adu, hfr=2.0, stars=50, median=1500):
    return {"Max": max_adu, "HFR": hfr, "Stars": stars,
            "Median": median, "Filename": "x.fits"}


class TestRunTune(TestCase):
    def test_grid_order(self) -> None:
        c = FakeClient(lambda g, e: _stats(1000))
        run_tune(c, exposures=[5, 10], gains=[200, 120])
        self.assertEqual(c.calls, [(200, 5), (200, 10), (120, 5), (120, 10)])

    def test_per_combo_failure_recorded_and_continues(self) -> None:
        def sf(g, e):
            return RuntimeError("camera busy") if (g, e) == (120, 10) else _stats(2000)
        c = FakeClient(sf)
        res = run_tune(c, exposures=[5, 10], gains=[200, 120])
        self.assertEqual(len(res), 4)  # ramp didn't abort
        bad = [r for r in res if r.gain == 120 and r.exposure_s == 10][0]
        self.assertIn("camera busy", bad.error)
        self.assertTrue(all(not r.error for r in res if r is not bad))

    def test_saturation_flag(self) -> None:
        # Max scales with exposure; 10s clips at SAT_LIMIT.
        c = FakeClient(lambda g, e: _stats(int(e * 7000)))
        res = run_tune(c, exposures=[5, 10], gains=[200])
        self.assertFalse(res[0].saturated)            # 35000
        self.assertTrue(res[1].saturated)             # 70000 >= 60000


class TestRecommend(TestCase):
    def test_picks_longest_non_saturating(self) -> None:
        res = [
            FrameStat(gain=200, exposure_s=3, max_adu=20000, hfr=2.0),
            FrameStat(gain=200, exposure_s=8, max_adu=50000, hfr=2.0),
            FrameStat(gain=200, exposure_s=12, max_adu=64000, hfr=2.0),
        ]
        r = recommend(res)[200]
        self.assertEqual(r["best_exposure_s"], 8)

    def test_all_saturated_note(self) -> None:
        res = [FrameStat(gain=200, exposure_s=3, max_adu=SAT_LIMIT + 1, hfr=2.0)]
        r = recommend(res)[200]
        self.assertIsNone(r["best_exposure_s"])
        self.assertIn("clips", r["note"])

    def test_trailing_flag(self) -> None:
        res = [
            FrameStat(gain=120, exposure_s=3, max_adu=10000, hfr=2.0),
            FrameStat(gain=120, exposure_s=30, max_adu=20000, hfr=3.5),  # >1.4x
        ]
        r = recommend(res)[120]
        self.assertEqual(r["trailing_from_s"], 30)


class TestReport(TestCase):
    def test_ascii_only_and_contents(self) -> None:
        res = [
            FrameStat(gain=200, exposure_s=5, max_adu=30000, hfr=2.1, stars=60, median=1400),
            FrameStat(gain=200, exposure_s=12, max_adu=SAT_LIMIT + 100, hfr=2.2, stars=80, median=1800),
            FrameStat(gain=120, exposure_s=5, max_adu=0, hfr=None, error="boom"),
        ]
        report = format_report(res, recommend(res))
        self.assertTrue(report.isascii(), "report must be ASCII-only (cp1252 consoles)")
        self.assertIn("Recommendation", report)
        self.assertIn("SAT", report)
        self.assertIn("ERROR: boom", report)
