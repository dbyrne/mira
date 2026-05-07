from __future__ import annotations

from datetime import date, datetime, timezone
from unittest import TestCase

from mira.config import WindowConfig
from mira.observability import (
    _local_window_samples_for_night,
    altitude_deg,
    angular_separation_deg,
    galactic_latitude_deg,
    moon_altitude_deg,
    moon_illumination,
    moon_position,
    moon_separation_deg,
    sun_altitude_deg,
    sun_position,
)


class ObservabilityTests(TestCase):
    def test_altitude_is_reasonable_for_polaris_from_jersey_city(self) -> None:
        altitude = altitude_deg(
            37.95456067,
            89.26410897,
            datetime(2026, 5, 4, tzinfo=timezone.utc),
            40.7178,
            -74.0431,
        )
        self.assertGreaterEqual(altitude, 39.0)
        self.assertLessEqual(altitude, 42.0)

    def test_galactic_latitude_range(self) -> None:
        latitude = galactic_latitude_deg(0.0, 0.0)
        self.assertGreaterEqual(latitude, -90.0)
        self.assertLessEqual(latitude, 90.0)

    def test_window_sample_count_matches_interval_count(self) -> None:
        # 22:00 -> 05:00 is a 7-hour window. With 30-min sampling, that's 14
        # half-hour intervals; multiplying samples by sample_minutes must
        # therefore yield 420 minutes, not 450.
        window = WindowConfig(
            start_hour_local=22,
            end_hour_local=5,
            nights=1,
            sample_minutes=30,
            min_altitude_deg=25,
            max_sun_altitude_deg=-12,
            max_moon_altitude_deg=30,
            max_moon_illumination=0.7,
        )
        samples = _local_window_samples_for_night(date(2026, 8, 15), "America/Anchorage", window)
        self.assertEqual(len(samples), 14)
        self.assertEqual(len(samples) * window.sample_minutes, 420)

    def test_window_sample_count_jersey_city(self) -> None:
        window = WindowConfig(
            start_hour_local=20,
            end_hour_local=1,
            nights=1,
            sample_minutes=30,
            min_altitude_deg=45,
            max_sun_altitude_deg=-12,
            max_moon_altitude_deg=30,
            max_moon_illumination=0.7,
        )
        samples = _local_window_samples_for_night(date(2026, 5, 4), "America/New_York", window)
        # 20:00 -> 01:00 next day is 5 hours = 10 half-hour intervals.
        self.assertEqual(len(samples), 10)
        self.assertEqual(len(samples) * window.sample_minutes, 300)


class SunPositionTests(TestCase):
    def test_sun_declination_in_may(self) -> None:
        # May 4 2026: sun should be at declination roughly +16 degrees.
        _, dec = sun_position(datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc))
        self.assertGreater(dec, 14.0)
        self.assertLess(dec, 18.0)

    def test_sun_high_at_jc_solar_noon(self) -> None:
        # JC solar noon May 4 is roughly 17:00 UTC. Sun should be near max alt.
        alt = sun_altitude_deg(
            datetime(2026, 5, 4, 17, 0, tzinfo=timezone.utc),
            40.7178,
            -74.0431,
        )
        self.assertGreater(alt, 55.0)
        self.assertLess(alt, 70.0)

    def test_sun_well_below_horizon_at_jc_local_midnight(self) -> None:
        # JC local midnight May 4 -> 04:00 UTC May 5. Sun should be deep below horizon.
        alt = sun_altitude_deg(
            datetime(2026, 5, 5, 4, 0, tzinfo=timezone.utc),
            40.7178,
            -74.0431,
        )
        self.assertLess(alt, -30.0)

    def test_fairbanks_summer_no_astronomical_darkness(self) -> None:
        # 2026-05-15 at Fairbanks local midnight -> 09:00 UTC May 15. At 64.84N
        # the sun does not get below -18 deg in mid-May; -12 (nautical) only
        # marginally. We assert the relaxed condition: alt is above -12.
        alt = sun_altitude_deg(
            datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc),
            64.8378,
            -147.7164,
        )
        self.assertGreater(alt, -12.0)


class MoonPositionTests(TestCase):
    def test_full_moon_2026_05_01_high_illumination(self) -> None:
        # USNO ephemeris: full moon was 2026-05-01 ~17:24 UTC. Illumination
        # at that exact moment should be very close to 1.
        illum = moon_illumination(datetime(2026, 5, 1, 17, 24, tzinfo=timezone.utc))
        self.assertGreater(illum, 0.99)

    def test_new_moon_2026_05_16_low_illumination(self) -> None:
        # USNO ephemeris: new moon was 2026-05-16 ~10:01 UTC.
        illum = moon_illumination(datetime(2026, 5, 16, 10, 1, tzinfo=timezone.utc))
        self.assertLess(illum, 0.05)

    def test_moon_position_returns_valid_ranges(self) -> None:
        ra, dec, ecl_lon = moon_position(datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc))
        self.assertGreaterEqual(ra, 0.0)
        self.assertLess(ra, 360.0)
        self.assertGreaterEqual(dec, -90.0)
        self.assertLessEqual(dec, 90.0)
        self.assertGreaterEqual(ecl_lon, 0.0)
        self.assertLess(ecl_lon, 360.0)

    def test_moon_altitude_at_known_position(self) -> None:
        # Sanity: moon altitude is a finite number between -90 and 90.
        alt = moon_altitude_deg(
            datetime(2026, 5, 1, 17, 24, tzinfo=timezone.utc),
            40.7178,
            -74.0431,
        )
        self.assertGreaterEqual(alt, -90.0)
        self.assertLessEqual(alt, 90.0)


class AngularSeparationTests(TestCase):
    def test_zero_separation_when_same_position(self) -> None:
        self.assertAlmostEqual(angular_separation_deg(180.0, 0.0, 180.0, 0.0), 0.0, places=5)

    def test_pole_to_equator_is_90(self) -> None:
        self.assertAlmostEqual(angular_separation_deg(0.0, 90.0, 0.0, 0.0), 90.0, places=4)

    def test_180_apart_along_equator(self) -> None:
        self.assertAlmostEqual(angular_separation_deg(0.0, 0.0, 180.0, 0.0), 180.0, places=4)

    def test_known_polaris_to_vega(self) -> None:
        # Polaris at (37.95, 89.26), Vega at (279.23, 38.78)
        # True separation is ~50.7° (90-39.3 ish; Vega is dec 38.78 so 51.22°)
        sep = angular_separation_deg(37.95, 89.26, 279.23, 38.78)
        self.assertAlmostEqual(sep, 51.22, delta=0.5)


class MoonSeparationTests(TestCase):
    def test_separation_returns_value_in_range(self) -> None:
        sep = moon_separation_deg(279.23, 38.78,
                                  datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc))
        self.assertGreaterEqual(sep, 0.0)
        self.assertLessEqual(sep, 180.0)

    def test_target_at_moon_position_separation_near_zero(self) -> None:
        # Use the moon's own position as the target → separation should be 0.
        utc = datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc)
        moon_ra, moon_dec, _ = moon_position(utc)
        sep = moon_separation_deg(moon_ra, moon_dec, utc)
        self.assertLess(sep, 0.001)
