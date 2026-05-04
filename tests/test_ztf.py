from __future__ import annotations

import math
from unittest import TestCase

import numpy as np

from anomaly_scout.ztf import (
    PERIOD_MAX_DAYS,
    PERIOD_MIN_DAYS,
    assess_period_disagreement,
    estimate_period_from_rows,
    period_disagreement,
)


class PeriodEstimationTests(TestCase):
    def _synthesize_rows(self, period_days: float, n: int = 100, span: float = 200.0, amp: float = 0.4) -> list[dict[str, str]]:
        rng = np.random.default_rng(42)
        # Irregular cadence (more realistic than evenly spaced)
        times = np.sort(rng.uniform(0.0, span, n))
        mags = 15.0 + amp * np.sin(2 * np.pi * times / period_days) + rng.normal(0, 0.02, n)
        return [
            {"mjd": str(t), "mag": str(m), "filtercode": "zg"}
            for t, m in zip(times, mags)
        ]

    def test_recovers_known_short_period(self) -> None:
        rows = self._synthesize_rows(period_days=2.5, n=120, span=120.0)
        derived, power, span = estimate_period_from_rows(rows)
        self.assertIsNotNone(derived)
        self.assertAlmostEqual(derived, 2.5, places=1)
        self.assertGreater(power, 0.5)
        self.assertGreater(span, 100.0)

    def test_recovers_known_long_period(self) -> None:
        rows = self._synthesize_rows(period_days=80.0, n=200, span=800.0)
        derived, power, span = estimate_period_from_rows(rows)
        self.assertIsNotNone(derived)
        self.assertAlmostEqual(derived, 80.0, delta=2.0)
        self.assertGreater(power, 0.5)

    def test_returns_none_when_too_few_observations(self) -> None:
        rows = [{"mjd": "1.0", "mag": "12.0", "filtercode": "zg"}] * 5
        derived, power, span = estimate_period_from_rows(rows)
        self.assertIsNone(derived)
        self.assertIsNone(power)


class AssessPeriodDisagreementTests(TestCase):
    def test_below_search_minimum_returns_none_with_note(self) -> None:
        # Catalog period 0.026 d (37 minutes) < PERIOD_MIN_DAYS (0.1 d)
        result, note = assess_period_disagreement(
            catalog_period=0.026,
            derived_period=1.25,
            peak_power=0.5,
            time_span_days=500.0,
            period_min=PERIOD_MIN_DAYS,
            period_max=PERIOD_MAX_DAYS,
            min_peak_power=0.3,
        )
        self.assertIsNone(result)
        self.assertIn("below the searched minimum", note)

    def test_above_baseline_half_returns_none_with_note(self) -> None:
        # Catalog period 600 d > time_span/2 = 200 d
        result, note = assess_period_disagreement(
            catalog_period=600.0,
            derived_period=10.0,
            peak_power=0.7,
            time_span_days=400.0,
            period_min=PERIOD_MIN_DAYS,
            period_max=PERIOD_MAX_DAYS,
            min_peak_power=0.3,
        )
        self.assertIsNone(result)
        self.assertIn("data baseline", note)

    def test_low_peak_power_returns_none_with_note(self) -> None:
        result, note = assess_period_disagreement(
            catalog_period=10.0,
            derived_period=1.25,
            peak_power=0.118,  # below default 0.3 threshold
            time_span_days=400.0,
            period_min=PERIOD_MIN_DAYS,
            period_max=PERIOD_MAX_DAYS,
            min_peak_power=0.3,
        )
        self.assertIsNone(result)
        self.assertIn("below the confidence threshold", note)

    def test_assessable_disagreement_passes_through(self) -> None:
        result, note = assess_period_disagreement(
            catalog_period=10.0,
            derived_period=2.5,
            peak_power=0.7,
            time_span_days=400.0,
            period_min=PERIOD_MIN_DAYS,
            period_max=PERIOD_MAX_DAYS,
            min_peak_power=0.3,
        )
        self.assertTrue(result)
        self.assertEqual(note, "")

    def test_assessable_agreement_passes_through(self) -> None:
        result, note = assess_period_disagreement(
            catalog_period=10.0,
            derived_period=10.2,
            peak_power=0.7,
            time_span_days=400.0,
            period_min=PERIOD_MIN_DAYS,
            period_max=PERIOD_MAX_DAYS,
            min_peak_power=0.3,
        )
        self.assertFalse(result)
        self.assertEqual(note, "")


class PeriodDisagreementTests(TestCase):
    def test_agreement_within_tolerance(self) -> None:
        # 100.0 d catalog vs 102.0 d derived - within ~12% tolerance
        self.assertFalse(period_disagreement(100.0, 102.0))

    def test_disagreement_outside_tolerance(self) -> None:
        # 100.0 d vs 12.5 d - clear disagreement, not a 1/2x or 2x alias
        self.assertTrue(period_disagreement(100.0, 12.5))

    def test_half_period_alias_treated_as_agreement(self) -> None:
        # Lomb-Scargle commonly picks the half-period harmonic of an eclipsing binary
        self.assertFalse(period_disagreement(2.0, 1.0))
        self.assertFalse(period_disagreement(2.0, 4.0))

    def test_none_inputs_yield_none(self) -> None:
        self.assertIsNone(period_disagreement(None, 10.0))
        self.assertIsNone(period_disagreement(10.0, None))
        self.assertIsNone(period_disagreement(None, None))
