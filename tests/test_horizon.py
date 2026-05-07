"""Tests for the local horizon profile module — interpolation,
azimuth wrap-around, YAML loader, and integration with observability."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from anomaly_scout.horizon import (
    HorizonPoint,
    HorizonProfile,
    load_horizon_profile,
)
from anomaly_scout.observability import azimuth_deg


def _profile(*pairs: tuple[float, float]) -> HorizonProfile:
    points = tuple(
        HorizonPoint(az_deg=az, alt_deg=alt)
        for az, alt in sorted(pairs, key=lambda p: p[0])
    )
    return HorizonProfile(site="test", captured_at="", points=points)


class HorizonInterpolationTests(TestCase):
    def test_returns_zero_for_empty_profile(self) -> None:
        profile = HorizonProfile(site="x", captured_at="", points=())
        self.assertEqual(profile.min_altitude_at(180.0), 0.0)

    def test_exact_point_returns_exact_altitude(self) -> None:
        profile = _profile((0.0, 5.0), (90.0, 25.0), (180.0, 10.0), (270.0, 30.0))
        self.assertEqual(profile.min_altitude_at(90.0), 25.0)
        self.assertEqual(profile.min_altitude_at(180.0), 10.0)

    def test_linear_interpolation_between_points(self) -> None:
        profile = _profile((90.0, 20.0), (180.0, 40.0))
        # halfway should be the average
        self.assertAlmostEqual(profile.min_altitude_at(135.0), 30.0)
        # quarter of the way
        self.assertAlmostEqual(profile.min_altitude_at(112.5), 25.0)

    def test_wraparound_through_north(self) -> None:
        # Last point at 350° (alt 10), first at 10° (alt 30) — interpolating
        # at 0° should yield 20° (halfway).
        profile = _profile((10.0, 30.0), (350.0, 10.0))
        self.assertAlmostEqual(profile.min_altitude_at(0.0), 20.0)
        self.assertAlmostEqual(profile.min_altitude_at(355.0), 15.0)
        self.assertAlmostEqual(profile.min_altitude_at(5.0), 25.0)

    def test_az_normalization(self) -> None:
        profile = _profile((180.0, 10.0))
        self.assertEqual(profile.min_altitude_at(540.0), 10.0)  # 540 mod 360 = 180
        self.assertEqual(profile.min_altitude_at(-180.0), 10.0)

    def test_floor_at_combines_with_global_floor(self) -> None:
        profile = _profile((90.0, 15.0), (270.0, 35.0))
        # If global floor is 25°, the east direction (15°) is overruled by
        # global floor (25°). The west (35°) still wins.
        self.assertEqual(profile.floor_at(90.0, global_floor=25.0), 25.0)
        self.assertEqual(profile.floor_at(270.0, global_floor=25.0), 35.0)


class LoadHorizonProfileTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "h.yaml"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_loads_valid_profile(self) -> None:
        self.path.write_text(
            "site: balcony\n"
            "captured_at: 2026-05-06\n"
            "points:\n"
            "  - {az: 0, alt: 5}\n"
            "  - {az: 180, alt: 10}\n",
            encoding="utf-8",
        )
        profile = load_horizon_profile(self.path)
        self.assertEqual(profile.site, "balcony")
        self.assertEqual(len(profile.points), 2)
        self.assertEqual(profile.points[0].az_deg, 0.0)
        self.assertEqual(profile.points[1].alt_deg, 10.0)

    def test_sorts_points_by_azimuth(self) -> None:
        self.path.write_text(
            "site: x\ncaptured_at: ''\npoints:\n"
            "  - {az: 270, alt: 25}\n"
            "  - {az: 90, alt: 15}\n"
            "  - {az: 180, alt: 20}\n",
            encoding="utf-8",
        )
        profile = load_horizon_profile(self.path)
        azs = [p.az_deg for p in profile.points]
        self.assertEqual(azs, [90.0, 180.0, 270.0])

    def test_rejects_empty_points(self) -> None:
        self.path.write_text("site: x\ncaptured_at: ''\npoints: []\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_horizon_profile(self.path)

    def test_rejects_out_of_range_altitude(self) -> None:
        self.path.write_text(
            "site: x\ncaptured_at: ''\npoints:\n  - {az: 0, alt: 95}\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            load_horizon_profile(self.path)

    def test_normalizes_azimuth_to_0_360(self) -> None:
        self.path.write_text(
            "site: x\ncaptured_at: ''\npoints:\n"
            "  - {az: 720, alt: 10}\n"  # 720 mod 360 = 0
            "  - {az: -90, alt: 20}\n",  # -90 mod 360 = 270
            encoding="utf-8",
        )
        profile = load_horizon_profile(self.path)
        azs = sorted(p.az_deg for p in profile.points)
        self.assertEqual(azs, [0.0, 270.0])


class AzimuthDegTests(TestCase):
    """Sanity-check the azimuth formula against a known case: from
    Jersey City latitude (~40.7°), Polaris (RA 2h31m, Dec +89.26°)
    should always be very close to azimuth 0° (true north)."""

    def test_polaris_is_near_north(self) -> None:
        polaris_ra_deg = (2 + 31 / 60) * 15.0
        polaris_dec_deg = 89.26
        # A few times across a day; Polaris moves <2° in azimuth
        for hour in (0, 6, 12, 18):
            utc = datetime(2026, 5, 6, hour, 0, tzinfo=timezone.utc)
            az = azimuth_deg(polaris_ra_deg, polaris_dec_deg, utc, 40.7, -74.0)
            self.assertTrue(az < 5.0 or az > 355.0,
                            f"Polaris az at hour {hour} = {az} (expected near 0/360)")

    def test_zenith_meridian_target_is_due_south_or_north(self) -> None:
        # A target at dec equal to latitude on the meridian is at zenith,
        # so azimuth is undefined. Instead test: a target slightly south
        # of zenith on the meridian should be due south.
        utc = datetime(2026, 5, 6, 4, 0, tzinfo=timezone.utc)
        from anomaly_scout.observability import local_sidereal_time_hours
        lst = local_sidereal_time_hours(utc, -74.0)
        # Target at LST (so ha=0, on meridian) and dec = lat - 30
        ra = lst * 15.0
        dec = 40.7 - 30.0  # 10.7° dec, definitely south of zenith from 40.7°N
        az = azimuth_deg(ra, dec, utc, 40.7, -74.0)
        self.assertAlmostEqual(az, 180.0, delta=0.5)


class HorizonAffectsObservabilityTests(TestCase):
    """End-to-end: a target that would pass the global floor but lies
    behind a profile bump should be marked unobservable from that site."""

    def test_target_blocked_by_horizon_loses_minutes(self) -> None:
        from anomaly_scout.config import (
            FilterConfig,
            ObserverConfig,
            SiteConfig,
            WindowConfig,
        )
        from anomaly_scout.models import VsxTarget
        from anomaly_scout.observability import evaluate_observability

        # Build a profile where everything from azimuth 0–360 has a +60°
        # floor — i.e. nothing is observable from any direction. Even a
        # target at high altitude from JC latitude should get 0 minutes.
        wall_profile = HorizonProfile(
            site="wall",
            captured_at="",
            points=(HorizonPoint(0.0, 60.0), HorizonPoint(180.0, 60.0)),
        )

        observer = ObserverConfig(latitude_deg=40.7, longitude_deg=-74.0,
                                   timezone="America/New_York")
        window = WindowConfig(
            start_hour_local=20, end_hour_local=1, nights=1, sample_minutes=10,
            min_altitude_deg=20.0, max_sun_altitude_deg=-12.0,
            max_moon_altitude_deg=90.0, max_moon_illumination=1.0,
        )
        filters = FilterConfig(
            min_galactic_latitude_abs_deg=0.0, min_catalog_amplitude_mag=0.0,
            prefer_amplitude_mag=0.5, prefer_max_mag=14.0,
            reject_saturated_brighter_than_mag=2.0,
        )
        # Same site, with and without the wall
        site_open = SiteConfig(name="open", observer=observer,
                               observing_window=window, filters=filters)
        site_walled = SiteConfig(name="walled", observer=observer,
                                  observing_window=window, filters=filters,
                                  horizon_profile=wall_profile)

        # A target in the late-spring sky that's well above 20° from JC
        target = VsxTarget(
            oid=1, name="Vega", var_type="DSCT",
            bright_mag=0.0, faint_mag=0.1, bright_band="V", faint_band="V",
            faint_is_amplitude=False, period_days=0.2, spectral_type="A",
            ra_deg=279.234, dec_deg=38.78,
        )
        open_obs = evaluate_observability(target, site_open, start_date=date(2026, 5, 6))
        walled_obs = evaluate_observability(target, site_walled, start_date=date(2026, 5, 6))
        # Without horizon: some observable minutes (Vega rises high)
        self.assertGreater(open_obs.minutes_above_minimum, 0)
        # With a 60° wall everywhere: zero minutes (Vega never gets that high
        # from JC at 40.7° dec ~= 38.78° declination ⇒ peaks ~88° but only
        # passes 60° for a window). Wait, Vega does pass 60° for a few
        # hours from JC. Need a steeper wall.
        # Re-test: with wall at 89° (basically zenith only), should be 0
        zenith_wall = HorizonProfile(
            site="zenith",
            captured_at="",
            points=(HorizonPoint(0.0, 89.0), HorizonPoint(180.0, 89.0)),
        )
        site_extreme = SiteConfig(name="zenith", observer=observer,
                                   observing_window=window, filters=filters,
                                   horizon_profile=zenith_wall)
        extreme_obs = evaluate_observability(target, site_extreme, start_date=date(2026, 5, 6))
        self.assertEqual(extreme_obs.minutes_above_minimum, 0)


class JCBalconyProfileTests(TestCase):
    """Smoke test loading the real JC balcony profile shipped in config/."""

    def test_jc_profile_loads_and_interpolates_sensibly(self) -> None:
        path = Path(__file__).resolve().parent.parent / "config" / "horizon_balcony_jc.yaml"
        profile = load_horizon_profile(path)
        self.assertGreater(len(profile.points), 20)
        # NE chimney should require >40° for visibility
        self.assertGreater(profile.min_altitude_at(50.0), 40.0)
        # Clean south window should be low
        self.assertLess(profile.min_altitude_at(195.0), 10.0)
        # SW tree peak
        self.assertGreater(profile.min_altitude_at(220.0), 35.0)
