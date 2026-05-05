from __future__ import annotations

from unittest import TestCase

from anomaly_scout.session_plan import (
    dec_to_dms,
    dec_to_target_scheduler_dms,
    ra_to_hms,
    ra_to_target_scheduler_hms,
    recommended_exposure_plan,
)


class CoordinateFormattingTests(TestCase):
    def test_ra_zero_is_zero_hours(self) -> None:
        self.assertEqual(ra_to_hms(0.0), "00:00:00.00")

    def test_ra_180_is_twelve_hours(self) -> None:
        self.assertEqual(ra_to_hms(180.0), "12:00:00.00")

    def test_ra_typical_target(self) -> None:
        # Vega is at RA = 18h 36m 56s = 279.234 deg
        self.assertTrue(ra_to_hms(279.234).startswith("18:36:"))

    def test_dec_zero(self) -> None:
        self.assertEqual(dec_to_dms(0.0), "+00:00:00.0")

    def test_dec_positive(self) -> None:
        # Polaris dec ~= +89.264
        result = dec_to_dms(89.264)
        self.assertTrue(result.startswith("+89:"))

    def test_dec_negative(self) -> None:
        result = dec_to_dms(-30.5)
        self.assertTrue(result.startswith("-30:30:"))


class ExposurePlanTests(TestCase):
    def test_bright_target_short_exposure(self) -> None:
        plan = recommended_exposure_plan(7.0)
        self.assertEqual(plan["exposure_s"], 5)

    def test_mid_mag_15s(self) -> None:
        plan = recommended_exposure_plan(9.5)
        self.assertEqual(plan["exposure_s"], 15)

    def test_faint_30s(self) -> None:
        plan = recommended_exposure_plan(11.0)
        self.assertEqual(plan["exposure_s"], 30)

    def test_very_faint_60s(self) -> None:
        plan = recommended_exposure_plan(13.5)
        self.assertEqual(plan["exposure_s"], 60)

    def test_unknown_mag_defaults_to_30s(self) -> None:
        plan = recommended_exposure_plan(None)
        self.assertEqual(plan["exposure_s"], 30)

    def test_total_minutes_consistent(self) -> None:
        for mag in (6.0, 9.0, 11.0, 13.0):
            plan = recommended_exposure_plan(mag)
            total_seconds = plan["exposure_s"] * plan["frames"]
            self.assertEqual(plan["total_min"], total_seconds // 60)


class TargetSchedulerFormatTests(TestCase):
    def test_ra_format_uses_hms_letters(self) -> None:
        # Vega: 18h 36m 56s = 279.234 deg
        result = ra_to_target_scheduler_hms(279.234)
        self.assertTrue(result.startswith("18h 36m"))
        self.assertTrue(result.endswith("s"))

    def test_ra_format_zero(self) -> None:
        self.assertEqual(ra_to_target_scheduler_hms(0.0), "00h 00m 00s")

    def test_dec_format_positive(self) -> None:
        result = dec_to_target_scheduler_dms(40.0)
        self.assertEqual(result, "+40° 00' 00\"")

    def test_dec_format_negative(self) -> None:
        result = dec_to_target_scheduler_dms(-30.5)
        self.assertTrue(result.startswith("-30°"))
        self.assertIn("30'", result)

    def test_dec_format_zero(self) -> None:
        self.assertEqual(dec_to_target_scheduler_dms(0.0), "+00° 00' 00\"")
