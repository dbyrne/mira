from __future__ import annotations

from unittest import TestCase

from mira.anomaly import (
    ANOMALY_SIGMA,
    BASELINE_MIN_SAMPLES,
    CATALOG_TOLERANCE_MAG,
    WATCH_SIGMA,
    assess_session_anomaly,
)
from mira.models import VsxTarget
from mira.photometry import Observation


def _target(max_mag: float | None, min_mag: float | None, faint_is_amplitude: bool = False) -> VsxTarget:
    return VsxTarget(
        oid=1,
        name="RR LYR",
        var_type="RRAB",
        bright_mag=max_mag,
        faint_mag=min_mag,
        bright_band="V",
        faint_band="V",
        faint_is_amplitude=faint_is_amplitude,
        period_days=0.5668,
        spectral_type="A",
        ra_deg=291.366,
        dec_deg=42.785,
    )


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


def _baseline(median_mag: float, sigma: float, n: int = 20) -> list[tuple[float, float, str]]:
    """Generate a list of (jd, mag, band) samples around a known median + spread."""
    # Spread mags symmetrically around median to give a deterministic median + MAD
    mags = []
    for i in range(n):
        offset = ((i - n / 2) / (n / 2)) * sigma * 1.5  # spans ~3-sigma either way
        mags.append(median_mag + offset)
    return [(2460000.0 + i, m, "V") for i, m in enumerate(mags)]


class AnomalyAssessmentTests(TestCase):
    def test_consistent_observation(self) -> None:
        target = _target(max_mag=7.06, min_mag=8.12)
        observations = [_obs(2460000.0 + i * 0.001, 7.6 + i * 0.01) for i in range(20)]
        result = assess_session_anomaly(observations, target, aavso_recent=None)
        self.assertEqual(result.level, "info")
        self.assertAlmostEqual(result.session_median, 7.7, places=1)

    def test_brighter_than_catalog_is_anomaly(self) -> None:
        target = _target(max_mag=7.06, min_mag=8.12)
        # Observed at mag 5.5, way brighter than catalog max
        observations = [_obs(2460000.0 + i * 0.001, 5.5) for i in range(20)]
        result = assess_session_anomaly(observations, target, aavso_recent=None)
        self.assertEqual(result.level, "anomaly")
        self.assertTrue(any("brighter" in f for f in result.flags))

    def test_fainter_than_catalog_is_anomaly(self) -> None:
        target = _target(max_mag=7.06, min_mag=8.12)
        # Observed at mag 9.5, way fainter than catalog min
        observations = [_obs(2460000.0 + i * 0.001, 9.5) for i in range(20)]
        result = assess_session_anomaly(observations, target, aavso_recent=None)
        self.assertEqual(result.level, "anomaly")
        self.assertTrue(any("fainter" in f for f in result.flags))

    def test_catalog_tolerance_within_floor(self) -> None:
        target = _target(max_mag=7.06, min_mag=8.12)
        # Observed at 6.85, just barely within tolerance (0.21 mag brighter, threshold 0.3)
        observations = [_obs(2460000.0 + i * 0.001, 6.85) for i in range(20)]
        result = assess_session_anomaly(observations, target, aavso_recent=None)
        self.assertEqual(result.level, "info")

    def test_faint_is_amplitude_skips_faint_check(self) -> None:
        # When faint_is_amplitude is True, "faint_mag" is the amplitude, not a faint floor.
        target = _target(max_mag=7.06, min_mag=1.06, faint_is_amplitude=True)
        # Observed at mag 9.0; way over "1.06" but that's amplitude, not a faint floor
        observations = [_obs(2460000.0 + i * 0.001, 9.0) for i in range(20)]
        result = assess_session_anomaly(observations, target, aavso_recent=None)
        # Still anomaly via brighter check? 9.0 is fainter than 7.06+0.3, so brighter check passes.
        # No faint check because amplitude. So no catalog-range flag at all.
        self.assertEqual(result.level, "info")

    def test_baseline_skipped_when_too_few_samples(self) -> None:
        target = _target(max_mag=7.06, min_mag=8.12)
        observations = [_obs(2460000.0 + i * 0.001, 9.5) for i in range(20)]
        baseline = _baseline(median_mag=7.6, sigma=0.05, n=BASELINE_MIN_SAMPLES - 1)
        result = assess_session_anomaly(observations, target, aavso_recent=baseline)
        # Catalog flag fires (9.5 > 8.12 + 0.3); baseline check is skipped due to N < 10
        self.assertEqual(result.level, "anomaly")
        self.assertEqual(result.baseline_n, 0)

    def test_baseline_anomaly_off_recent_trend(self) -> None:
        target = _target(max_mag=7.06, min_mag=8.12)
        observations = [_obs(2460000.0 + i * 0.001, 7.7) for i in range(20)]
        # Baseline expects mag ~ 7.7 with tiny spread; observation right on top
        baseline = _baseline(median_mag=7.7, sigma=0.05, n=20)
        result = assess_session_anomaly(observations, target, aavso_recent=baseline)
        self.assertEqual(result.level, "info")

    def test_baseline_flags_anomaly_when_off_by_many_sigma(self) -> None:
        target = _target(max_mag=7.06, min_mag=8.12)
        # Observed at 7.95; baseline median 7.6 with tight sigma 0.05 → ~7σ off
        observations = [_obs(2460000.0 + i * 0.001, 7.95) for i in range(20)]
        baseline = _baseline(median_mag=7.6, sigma=0.05, n=20)
        result = assess_session_anomaly(observations, target, aavso_recent=baseline)
        self.assertEqual(result.level, "anomaly")
        self.assertEqual(result.baseline_n, 20)
        self.assertGreater(result.deviation_sigma, ANOMALY_SIGMA)

    def test_baseline_flags_watch_at_low_sigma(self) -> None:
        target = _target(max_mag=7.06, min_mag=8.12)
        # 7.7 vs baseline 7.6 with sigma 0.05 → ~2σ
        observations = [_obs(2460000.0 + i * 0.001, 7.71) for i in range(20)]
        baseline = _baseline(median_mag=7.6, sigma=0.05, n=20)
        result = assess_session_anomaly(observations, target, aavso_recent=baseline)
        self.assertIn(result.level, ("watch", "info"))
        if result.level == "watch":
            self.assertGreaterEqual(result.deviation_sigma, WATCH_SIGMA)

    def test_anomaly_dominates_watch_when_both(self) -> None:
        # Catalog flag is anomaly, baseline flag is watch; result rolls up to anomaly
        target = _target(max_mag=7.06, min_mag=8.12)
        observations = [_obs(2460000.0 + i * 0.001, 9.5) for i in range(20)]
        baseline = _baseline(median_mag=9.4, sigma=0.05, n=20)  # session ~2σ off baseline
        result = assess_session_anomaly(observations, target, aavso_recent=baseline)
        self.assertEqual(result.level, "anomaly")

    def test_no_target_no_catalog_check(self) -> None:
        observations = [_obs(2460000.0 + i * 0.001, 7.5) for i in range(20)]
        result = assess_session_anomaly(observations, vsx_target=None)
        self.assertEqual(result.level, "info")

    def test_empty_observations(self) -> None:
        result = assess_session_anomaly([], vsx_target=None)
        self.assertEqual(result.level, "info")
        self.assertIsNone(result.session_median)

    def test_baseline_helper_handles_empty_input(self) -> None:
        """Regression: _baseline_median_and_sigma used to IndexError on
        empty input. Now returns (None, None) so the caller can branch
        without try/except."""
        from mira.anomaly import _baseline_median_and_sigma
        median, sigma = _baseline_median_and_sigma([])
        self.assertIsNone(median)
        self.assertIsNone(sigma)

    def test_baseline_helper_returns_sigma_none_when_mad_zero(self) -> None:
        """If all values are identical, MAD is 0 and sigma should be None
        (caller treats that as 'can't trust the spread')."""
        from mira.anomaly import _baseline_median_and_sigma
        samples = [(2461000.0 + i, 7.5, "V") for i in range(10)]
        median, sigma = _baseline_median_and_sigma(samples)
        self.assertEqual(median, 7.5)
        self.assertIsNone(sigma)

    def test_to_dict_contains_keys(self) -> None:
        target = _target(max_mag=7.06, min_mag=8.12)
        observations = [_obs(2460000.0, 7.5)]
        result = assess_session_anomaly(observations, target).to_dict()
        for key in ("level", "flags", "session_median", "baseline_n"):
            self.assertIn(key, result)
        self.assertIsInstance(result["flags"], list)
