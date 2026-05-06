from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from anomaly_scout.lightcurve import plot_history, plot_phase_folded, plot_session_light_curve
from anomaly_scout.photometry import Observation


def _obs(jd: float, mag: float, err: float = 0.05) -> Observation:
    return Observation(
        target_name="RR LYR",
        julian_date=jd,
        magnitude=mag,
        magnitude_error=err,
        band="TG",
        comp_star_label="97",
        comp_star_mag=9.7,
    )


class LightCurveTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_session_plot_writes_png(self) -> None:
        observations = [
            _obs(2460000.20, 7.85),
            _obs(2460000.21, 7.88),
            _obs(2460000.22, 7.91),
        ]
        out = self.tmp_path / "lightcurve.png"
        result = plot_session_light_curve(observations, "RR LYR", out)
        self.assertEqual(result, out)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1000)

    def test_session_plot_returns_none_for_empty(self) -> None:
        out = self.tmp_path / "lightcurve.png"
        result = plot_session_light_curve([], "RR LYR", out)
        self.assertIsNone(result)
        self.assertFalse(out.exists())

    def test_session_plot_with_aavso_overlay(self) -> None:
        observations = [_obs(2460000.20, 7.85), _obs(2460000.22, 7.90)]
        aavso = [
            (2459990.0, 7.6, "V"),
            (2459995.0, 8.1, "V"),
            (2460000.0, 7.7, "Vis."),
        ]
        out = self.tmp_path / "lightcurve.png"
        result = plot_session_light_curve(observations, "RR LYR", out, aavso_recent=aavso)
        self.assertEqual(result, out)
        self.assertTrue(out.exists())

    def test_phase_folded_writes_png_when_period_known(self) -> None:
        # RR Lyr period ~ 0.5668 days; spread points across a phase
        observations = [
            _obs(2460000.20, 7.85),
            _obs(2460000.30, 7.95),
            _obs(2460000.40, 7.70),
            _obs(2460000.50, 7.92),
        ]
        out = self.tmp_path / "folded.png"
        result = plot_phase_folded(observations, "RR LYR", 0.5668, out)
        self.assertEqual(result, out)
        self.assertTrue(out.exists())

    def test_phase_folded_returns_none_for_empty(self) -> None:
        out = self.tmp_path / "folded.png"
        self.assertIsNone(plot_phase_folded([], "RR LYR", 0.5668, out))
        self.assertFalse(out.exists())

    def test_phase_folded_returns_none_for_zero_period(self) -> None:
        observations = [_obs(2460000.20, 7.85)]
        out = self.tmp_path / "folded.png"
        self.assertIsNone(plot_phase_folded(observations, "RR LYR", 0.0, out))

    def test_history_plot_writes_png(self) -> None:
        # Three sessions of RR Lyr over a month
        points = [
            (2460000.0, 7.6, 0.05, "2026-04-15"),
            (2460000.05, 7.65, 0.05, "2026-04-15"),
            (2460010.0, 7.55, 0.05, "2026-04-25"),
            (2460010.05, 7.6, 0.05, "2026-04-25"),
            (2460020.0, 7.7, 0.05, "2026-05-05"),
        ]
        out = self.tmp_path / "history.png"
        result = plot_history("RR LYR", points, out)
        self.assertEqual(result, out)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1000)

    def test_history_plot_returns_none_for_empty(self) -> None:
        out = self.tmp_path / "history.png"
        self.assertIsNone(plot_history("RR LYR", [], out))
