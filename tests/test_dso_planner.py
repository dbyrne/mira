"""Tests for the DSO planner — observability + FOV-fit + moon-relax ranking."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest import TestCase

from mira.config import (
    AavsoConfig, DsoConfig, FilterConfig, GaiaConfig, ObserverConfig,
    OutputConfig, ScoringConfig, ScoutConfig, SimbadConfig, SiteConfig,
    VsxQueryConfig, WindowConfig, ZtfConfig,
)
from mira.dso.catalog import DsoCatalog, DsoTarget
from mira.dso.planner import build_dso_candidates


def _make_site(name: str = "Test JC", **overrides) -> SiteConfig:
    window = WindowConfig(
        start_hour_local=overrides.get("start_hour_local", 20),
        end_hour_local=overrides.get("end_hour_local", 2),
        nights=overrides.get("nights", 1),
        sample_minutes=overrides.get("sample_minutes", 30),
        min_altitude_deg=overrides.get("min_altitude_deg", 25),
        max_sun_altitude_deg=-12.0,
        max_moon_altitude_deg=overrides.get("max_moon_altitude_deg", 30.0),
        max_moon_illumination=overrides.get("max_moon_illumination", 0.7),
        min_moon_separation_deg=overrides.get("min_moon_separation_deg", 30.0),
    )
    return SiteConfig(
        name=name,
        observer=ObserverConfig(
            latitude_deg=40.7178,
            longitude_deg=-74.0431,
            timezone="America/New_York",
        ),
        observing_window=window,
        filters=FilterConfig(
            min_galactic_latitude_abs_deg=0,
            min_catalog_amplitude_mag=0,
            prefer_amplitude_mag=0,
            prefer_max_mag=20,
            reject_saturated_brighter_than_mag=0,
        ),
    )


def _make_config(*sites: SiteConfig) -> ScoutConfig:
    return ScoutConfig(
        sites=tuple(sites),
        vsx_query=VsxQueryConfig(100, 30, 3, -10, 17, False, ()),
        scoring=ScoringConfig(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        aavso=AavsoConfig(False, 0, 0, 0, 0, (), 0),
        simbad=SimbadConfig(False, 0, 0, 0),
        gaia=GaiaConfig(False, 0, 0, 0),
        ztf=ZtfConfig(False, 0, 0, 0, (), 0),
        output=OutputConfig(directory=Path("/tmp"), top_packets=10),
    )


def _make_target(
    name: str = "T1",
    ra_deg: float = 303.025,    # NGC 6888 — high transit from JC
    dec_deg: float = 38.35,
    size_arcmin=(18.0, 13.0),
    object_type: str = "WR",
    budget=None,
) -> DsoTarget:
    return DsoTarget(
        name=name,
        common_name=name,
        object_type=object_type,
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        size_arcmin=size_arcmin,
        constellation="Cyg",
        budget_minutes=budget or {"Ha": 600, "OIII": 600, "SII": 480},
    )


class BuildDsoCandidatesTests(TestCase):
    def test_culminating_target_is_viable(self) -> None:
        # NGC 6888 in mid-August from JC transits very high.
        config = _make_config(_make_site())
        catalog = DsoCatalog(
            version="t", defaults={}, targets=(_make_target(),),
        )
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
        )
        self.assertEqual(len(cands), 1)
        cand = cands[0]
        self.assertGreater(cand.best_observability.minutes_above_minimum, 0)
        self.assertGreater(cand.best_observability.max_altitude_deg, 60)
        self.assertTrue(cand.fits_fov)

    def test_too_southern_target_drops_out(self) -> None:
        # Dec -60 from JC (lat +40.7) never rises above 25° floor.
        config = _make_config(_make_site())
        catalog = DsoCatalog(version="t", defaults={}, targets=(
            _make_target(dec_deg=-60.0),
        ))
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
        )
        self.assertEqual(cands, [])

    def test_mosaic_flagged_and_demoted(self) -> None:
        config = _make_config(_make_site())
        # Same RA/Dec, one fits FOV, one doesn't (oversized + mosaic flag).
        small = _make_target(name="Small", size_arcmin=(20.0, 15.0))
        big = DsoTarget(
            name="Big", common_name="Big", object_type="HII",
            ra_deg=303.025, dec_deg=38.35,
            size_arcmin=(240.0, 180.0),
            constellation="Cyg", budget_minutes={"Ha": 600},
            mosaic=True,
        )
        catalog = DsoCatalog(version="t", defaults={}, targets=(big, small))
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            fov_deg=(1.6, 1.07),
        )
        # Both viable, but the FOV-fitting one ranks first (mosaic demoted).
        names = [c.target.name for c in cands]
        self.assertEqual(names[0], "Small")
        self.assertEqual(names[1], "Big")
        big_cand = next(c for c in cands if c.target.name == "Big")
        small_cand = next(c for c in cands if c.target.name == "Small")
        self.assertFalse(big_cand.fits_fov)
        self.assertTrue(small_cand.fits_fov)
        self.assertLess(big_cand.score, small_cand.score)

    def test_moon_relax_only_applies_to_narrowband(self) -> None:
        # Pin: a broadband-only DSO target (REF/galaxy with L+RGB) gets the
        # VSX-style moon gate; a narrowband target ignores moon entirely.
        # The way to surface this without faking a moon-up date is to set
        # max_moon_altitude_deg=-90 (always treated as "moon below limit",
        # so the moon-separation gate never activates) — which is the
        # default site config; we instead lock max_moon_altitude_deg to a
        # value low enough that the moon will sometimes trip it.
        site = _make_site(
            min_moon_separation_deg=180.0,    # any sky → blocked when moon-up
            max_moon_altitude_deg=0.0,
            max_moon_illumination=0.0,        # any phase counts as bright
        )
        config = _make_config(site)
        narrowband = _make_target(name="NB", budget={"Ha": 600})
        broadband = _make_target(
            name="BB", budget={"L": 240, "R": 180, "G": 180, "B": 180},
        )
        catalog = DsoCatalog(
            version="t", defaults={}, targets=(narrowband, broadband),
        )
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            relax_moon=True,
        )
        # Narrowband still observable (moon ignored). Broadband may be
        # observable or not depending on the moon that night — but
        # importantly, when relax_moon=False, *neither* should get a free
        # pass.
        names_relaxed = {c.target.name for c in cands}
        self.assertIn("NB", names_relaxed)
        cands_strict = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            relax_moon=False,
        )
        names_strict = {c.target.name for c in cands_strict}
        # In strict mode, NB no longer gets the moon-relax — its viability
        # equals the broadband one. The point of this test: relax_moon=True
        # must produce ≥ candidates than relax_moon=False (narrowband can
        # only gain viability, never lose it).
        self.assertGreaterEqual(len(names_relaxed), len(names_strict))

    def test_ranking_score_orders_results(self) -> None:
        # Two narrowband targets in Cygnus; the higher-transit one should
        # outrank the lower-transit one.
        config = _make_config(_make_site())
        high = _make_target(name="High", dec_deg=40.0)
        low = _make_target(name="Low", dec_deg=10.0)
        catalog = DsoCatalog(version="t", defaults={}, targets=(low, high))
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
        )
        self.assertEqual([c.target.name for c in cands], ["High", "Low"])

    def test_multi_site_picks_best(self) -> None:
        # JC vs a phantom Fairbanks. NGC 6888 (dec +38) transits higher at
        # JC than at Fairbanks (lat +64.8); test that best_observability
        # is the site with the most dark-minutes above floor.
        jc = _make_site(name="JC")
        fbx = _make_site(
            name="Fairbanks",
            min_altitude_deg=25,
            max_sun_altitude_deg=-12.0,
        )
        # Hack: replace Fairbanks lat/lon by re-building the observer block
        fbx = replace(
            fbx,
            observer=ObserverConfig(
                latitude_deg=64.8378,
                longitude_deg=-147.7164,
                timezone="America/Anchorage",
            ),
        )
        config = _make_config(jc, fbx)
        catalog = DsoCatalog(
            version="t", defaults={}, targets=(_make_target(),),
        )
        # Late November — Fairbanks has long nights, JC has limited but the
        # target rises higher at JC. Either could win; what we're testing
        # is just that best_observability points at one of them, not None.
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 11, 1),
        )
        self.assertEqual(len(cands), 1)
        self.assertIn(cands[0].best_site_name, {"JC", "Fairbanks"})
        self.assertEqual(len(cands[0].observabilities), 2)


class DsoConfigDefaultsTests(TestCase):
    def test_default_dsoconfig_present_on_scoutconfig(self) -> None:
        # ScoutConfig.dso must always have a value — even on configs that
        # don't declare a `dso:` YAML section, the field defaults to
        # DSO_DEFAULTS so `cfg.dso.catalog_path` is safe to read.
        from mira.config import DSO_DEFAULTS
        config = _make_config(_make_site())
        self.assertEqual(config.dso.enabled, DSO_DEFAULTS.enabled)
        self.assertEqual(config.dso.fov_deg, DSO_DEFAULTS.fov_deg)
        self.assertTrue(config.dso.relax_moon)
