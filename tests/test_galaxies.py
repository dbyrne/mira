"""Tests for the bright-galaxy planner path (`mira galaxies`).

Covers the galaxy-specific additions layered onto the shared DSO engine:
- catalog: GALAXY object type, the optional `magnitude` field, derived
  mean surface brightness;
- planner: surface-brightness-weighted + size-penalized scoring, the
  dark-site-only / undersampled flags, and — load-bearing — the invariant
  that all of this is a strict no-op for narrowband targets (no magnitude),
  so the existing DSO ranking is preserved bit-for-bit;
- config: the `galaxies:` section and its moon-strict, SB-floored defaults;
- the shipped data/dso_catalog/galaxies.yaml.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import yaml

from mira.config import (
    GALAXY_DEFAULTS, AavsoConfig, FilterConfig, GaiaConfig, ObserverConfig,
    OutputConfig, ScoringConfig, ScoutConfig, SimbadConfig, SiteConfig,
    VsxQueryConfig, WindowConfig, ZtfConfig, load_config,
)
from mira.dso.catalog import DsoCatalog, DsoTarget, load_dso_catalog
from mira.dso.planner import build_dso_candidates


# --- shared fixtures (mirroring test_dso_planner's minimal helpers) --------

def _make_site(name: str = "Test JC", **overrides) -> SiteConfig:
    window = WindowConfig(
        start_hour_local=20, end_hour_local=2, nights=1, sample_minutes=30,
        min_altitude_deg=overrides.get("min_altitude_deg", 25),
        max_sun_altitude_deg=-12.0, max_moon_altitude_deg=90.0,
        max_moon_illumination=1.01, min_moon_separation_deg=0.0,
    )
    return SiteConfig(
        name=name,
        observer=ObserverConfig(40.7178, -74.0431, "America/New_York"),
        observing_window=window,
        filters=FilterConfig(0, 0, 0, 20, 0),
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


def _galaxy(
    name: str,
    *,
    magnitude: float,
    size_arcmin=(10.0, 5.0),
    ra_deg: float = 303.025,   # high transit from JC in mid-August
    dec_deg: float = 45.0,
) -> DsoTarget:
    return DsoTarget(
        name=name, common_name=name, object_type="GALAXY",
        ra_deg=ra_deg, dec_deg=dec_deg, size_arcmin=size_arcmin,
        constellation="Cyg", budget_minutes={"IR": 240}, magnitude=magnitude,
    )


def _nb_target(name: str = "NB") -> DsoTarget:
    """A narrowband target — no magnitude. Used to pin the no-op invariant."""
    return DsoTarget(
        name=name, common_name=name, object_type="HII",
        ra_deg=303.025, dec_deg=45.0, size_arcmin=(18.0, 13.0),
        constellation="Cyg", budget_minutes={"Ha": 600, "OIII": 600},
    )


def _write_catalog(dir_path: Path, raw: dict) -> Path:
    path = dir_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


_GALAXY_YAML = {
    "name": "M51", "common_name": "Whirlpool", "object_type": "GALAXY",
    "ra_deg": 202.47, "dec_deg": 47.195, "size_arcmin": [11.2, 6.9],
    "magnitude": 8.4, "constellation": "CVn", "budget_minutes": {"IR": 240},
}


# --- catalog: magnitude + surface brightness ------------------------------

class GalaxyCatalogTests(TestCase):
    def test_galaxy_type_and_magnitude_load(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {"targets": [_GALAXY_YAML]})
            cat = load_dso_catalog(path)
            m51 = cat.by_name("M51")
            self.assertTrue(m51.is_galaxy)
            self.assertEqual(m51.magnitude, 8.4)
            self.assertFalse(m51.is_narrowband)  # IR budget → broadband → moon-strict

    def test_surface_brightness_matches_hand_calc(self) -> None:
        # M51: m 8.4 over an 11.2'×6.9' ellipse → mean SB ≈ 21.7 mag/arcsec².
        t = _galaxy("M51", magnitude=8.4, size_arcmin=(11.2, 6.9))
        self.assertAlmostEqual(t.surface_brightness, 21.75, places=1)

    def test_surface_brightness_none_without_magnitude(self) -> None:
        self.assertIsNone(_nb_target().surface_brightness)
        self.assertIsNone(_nb_target().magnitude)

    def test_invalid_magnitude_rejected(self) -> None:
        bad = {**_GALAXY_YAML, "magnitude": 99}
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {"targets": [bad]})
            with self.assertRaises(ValueError) as cm:
                load_dso_catalog(path)
            self.assertIn("magnitude", str(cm.exception))

    def test_magnitude_optional_for_narrowband(self) -> None:
        # An entry with no magnitude key still loads (narrowband).
        nb = {
            "name": "NGC 6888", "object_type": "WR", "ra_deg": 303.0,
            "dec_deg": 38.3, "size_arcmin": [18, 13], "constellation": "Cyg",
            "budget_minutes": {"Ha": 600},
        }
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {"targets": [nb]})
            cat = load_dso_catalog(path)
            self.assertIsNone(cat.by_name("NGC 6888").magnitude)


# --- planner: SB + size scoring -------------------------------------------

class GalaxyScoringTests(TestCase):
    DATE = date(2026, 8, 15)

    def _rank(self, *targets, fov_deg=(4.2, 2.4), sb_limit=22.5):
        cfg = _make_config(_make_site())
        cat = DsoCatalog(version="t", defaults={}, targets=tuple(targets))
        return build_dso_candidates(
            cat, cfg, start_date=self.DATE, fov_deg=fov_deg,
            relax_moon=False, sb_limit_mag_arcsec2=sb_limit,
        )

    def test_higher_surface_brightness_outranks_lower(self) -> None:
        # Identical position + size; only SB differs (via magnitude).
        bright = _galaxy("Bright", magnitude=8.0)   # SB ~20.8
        faint = _galaxy("Faint", magnitude=10.0)    # SB ~22.8
        cands = self._rank(faint, bright)
        self.assertEqual([c.target.name for c in cands], ["Bright", "Faint"])

    def test_large_galaxy_outranks_small_at_equal_sb(self) -> None:
        # Same mean SB (~22), different angular size. Size only penalizes
        # the small — the large one wins, and the small one is flagged.
        small = _galaxy("Small", magnitude=11.12, size_arcmin=(4.0, 2.0))
        large = _galaxy("Large", magnitude=8.40, size_arcmin=(14.0, 7.0))
        self.assertAlmostEqual(small.surface_brightness, 22.0, places=1)
        self.assertAlmostEqual(large.surface_brightness, 22.0, places=1)
        cands = self._rank(small, large)
        self.assertEqual([c.target.name for c in cands], ["Large", "Small"])
        by_name = {c.target.name: c for c in cands}
        self.assertTrue(by_name["Small"].under_sampled)   # 4' < 4.2°/40 = 6.3'
        self.assertFalse(by_name["Large"].under_sampled)

    def test_dark_site_only_flag(self) -> None:
        faint = _galaxy("LowSB", magnitude=9.5, size_arcmin=(10.0, 9.0))  # SB ~23
        bright = _galaxy("HighSB", magnitude=8.0, size_arcmin=(10.0, 5.0))  # SB ~20.8
        self.assertGreater(faint.surface_brightness, 22.5)
        cands = {c.target.name: c for c in self._rank(faint, bright)}
        self.assertTrue(cands["LowSB"].dark_site_only)
        self.assertFalse(cands["HighSB"].dark_site_only)


class NarrowbandNoOpInvariantTests(TestCase):
    """The galaxy SB/size machinery must NOT touch narrowband ranking."""

    def test_sb_limit_kwarg_is_noop_for_narrowband(self) -> None:
        cfg = _make_config(_make_site())
        cat = DsoCatalog(version="t", defaults={}, targets=(_nb_target(),))
        without = build_dso_candidates(cat, cfg, start_date=date(2026, 8, 15))
        with_sb = build_dso_candidates(
            cat, cfg, start_date=date(2026, 8, 15),
            fov_deg=(4.2, 2.4), sb_limit_mag_arcsec2=22.5,
        )
        self.assertEqual(without[0].score, with_sb[0].score)
        self.assertIsNone(with_sb[0].surface_brightness)
        self.assertFalse(with_sb[0].dark_site_only)
        self.assertFalse(with_sb[0].under_sampled)


# --- config: galaxies section ---------------------------------------------

class GalaxyConfigTests(TestCase):
    def test_galaxy_defaults_present_and_moon_strict(self) -> None:
        cfg = _make_config(_make_site())
        self.assertEqual(cfg.galaxies, GALAXY_DEFAULTS)
        self.assertFalse(cfg.galaxies.relax_moon)  # broadband → strict
        self.assertEqual(cfg.galaxies.sb_limit_mag_arcsec2, 22.5)
        self.assertEqual(cfg.galaxies.output_subdir, "galaxies")

    def test_shipped_s30_config_parses_galaxies_section(self) -> None:
        cfg = load_config("config/s30_pro_jc.yaml")
        self.assertTrue(cfg.galaxies.enabled)
        self.assertFalse(cfg.galaxies.relax_moon)
        # Measured FOV (3.66"/px / eff. 163mm fl), not the nominal-150mm 4.2x2.4.
        self.assertEqual(cfg.galaxies.fov_deg, (3.9, 2.2))
        self.assertEqual(
            cfg.galaxies.catalog_path, Path("data/dso_catalog/galaxies.yaml"),
        )


# --- the shipped catalog --------------------------------------------------

class ShippedGalaxyCatalogTests(TestCase):
    def setUp(self) -> None:
        self.cat = load_dso_catalog("data/dso_catalog/galaxies.yaml")

    def test_loads_and_all_entries_are_galaxies_with_magnitude(self) -> None:
        self.assertGreater(len(self.cat.targets), 30)
        for t in self.cat.targets:
            with self.subTest(target=t.name):
                self.assertTrue(t.is_galaxy)
                self.assertIsNotNone(t.magnitude, f"{t.name} missing magnitude")
                self.assertIsNotNone(t.surface_brightness)
                self.assertFalse(t.is_narrowband)  # IR-only → moon-strict

    def test_budgets_keyed_ir_per_s30_galaxy_doctrine(self) -> None:
        # The galaxy doctrine shoots through the S30's IR(-cut) broadband
        # filter, and the ledger only books minutes against budgeted filter
        # keys — an LP-keyed budget made every by-the-book galaxy session
        # invisible (0% complete forever). Pin the key to IR.
        for t in self.cat.targets:
            with self.subTest(target=t.name):
                self.assertEqual(
                    set(t.budget_minutes), {"IR"},
                    f"{t.name} budget keys {set(t.budget_minutes)} — galaxy "
                    "sessions are shot through IR and must be budgeted as IR",
                )
                self.assertGreater(t.budget_minutes["IR"], 0)

    def test_m51_present_and_sane(self) -> None:
        m51 = self.cat.by_name("M51")
        self.assertIsNotNone(m51)
        self.assertAlmostEqual(m51.magnitude, 8.4, places=1)
        self.assertLess(m51.surface_brightness, 22.5)  # city-friendly
