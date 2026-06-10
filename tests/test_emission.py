"""Tests for the emission-nebula planner path (`mira emission`).

Covers the additions that make emission a first-class path layered on the
shared DSO engine:
- config: EMISSION_DEFAULTS (moon-relaxed, emission catalog, `emission/`
  subdir, no SB floor) and the `emission:` section in both rig configs,
  with the load-bearing S30 wide-FOV override;
- the shipped data/dso_catalog/emission_nebulae.yaml (all emission types,
  every target narrowband-budgeted);
- the rig-agnostic FOV behavior: the SAME catalog mosaic-flags the medium
  giants on the Esprit single frame but frames them single-shot on the S30,
  driven by fov_deg at plan time (not a static Esprit-centric flag).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest import TestCase

from mira.config import EMISSION_DEFAULTS, load_config
from mira.dso.catalog import load_dso_catalog
from mira.dso.planner import build_dso_candidates

CATALOG = Path("data/dso_catalog/emission_nebulae.yaml")
ESPRIT = Path("config/esprit120_jc.yaml")
S30 = Path("config/s30_pro_jc.yaml")


class EmissionDefaultsTests(TestCase):
    def test_defaults(self):
        d = EMISSION_DEFAULTS
        self.assertTrue(d.enabled)
        self.assertEqual(d.catalog_path, Path("data/dso_catalog/emission_nebulae.yaml"))
        self.assertEqual(d.fov_deg, (1.6, 1.07))
        self.assertTrue(d.relax_moon)            # narrowband / LP tolerate moonlight
        self.assertEqual(d.output_subdir, "emission")
        self.assertIsNone(d.sb_limit_mag_arcsec2)  # emission has no SB floor


class EmissionConfigTests(TestCase):
    def test_esprit_section(self):
        cfg = load_config(ESPRIT)
        self.assertTrue(cfg.emission.enabled)
        self.assertEqual(cfg.emission.fov_deg, (1.6, 1.07))
        self.assertEqual(cfg.emission.output_subdir, "emission")
        self.assertEqual(
            cfg.emission.catalog_path, Path("data/dso_catalog/emission_nebulae.yaml")
        )
        self.assertTrue(cfg.emission.relax_moon)

    def test_s30_wide_fov_override(self):
        # The load-bearing setting: the S30's wide field frames the giants
        # single-shot, so its emission FOV must override the Esprit default.
        # Values are the MEASURED field (3.66"/px plate scale / eff. 163mm fl),
        # not the nominal-150mm 4.2x2.4.
        cfg = load_config(S30)
        self.assertEqual(cfg.emission.fov_deg, (3.9, 2.2))
        self.assertTrue(cfg.emission.relax_moon)

    def test_absent_section_falls_back_to_defaults(self):
        # A VSX-only config with no `emission:` section keeps loading.
        cfg = load_config(Path("config/jersey_city.yaml"))
        self.assertEqual(cfg.emission, EMISSION_DEFAULTS)


class EmissionCatalogTests(TestCase):
    def test_catalog_loads_and_is_all_emission(self):
        cat = load_dso_catalog(CATALOG)
        self.assertGreaterEqual(len(cat.targets), 30)
        types = {t.object_type for t in cat.targets}
        self.assertNotIn("GALAXY", types)               # not the galaxy path
        self.assertTrue(types <= {"HII", "PN", "SNR", "WR"})
        for t in cat.targets:
            self.assertTrue(
                t.is_narrowband, f"{t.name} has no narrowband budget"
            )
            self.assertIsNone(t.surface_brightness)     # no magnitude → no SB

    def test_known_targets_present(self):
        cat = load_dso_catalog(CATALOG)
        names = {t.name for t in cat.targets}
        for n in ("NGC 6888", "NGC 7000", "M42", "Cygnus Loop"):
            self.assertIn(n, names)


class EmissionFovBehaviorTests(TestCase):
    """The rig-agnostic payoff: one catalog, FOV decides single-frame fit."""

    def _candidate(self, cands, name):
        return next((c for c in cands if c.target.name == name), None)

    def test_medium_giant_fits_s30_not_esprit(self):
        cat = load_dso_catalog(CATALOG)
        esp, s30 = load_config(ESPRIT), load_config(S30)
        d = date(2026, 8, 15)
        esp_c = build_dso_candidates(
            cat, esp, start_date=d, fov_deg=esp.emission.fov_deg,
            relax_moon=True, ledger=None, deficit_weight=0.0,
        )
        s30_c = build_dso_candidates(
            cat, s30, start_date=d, fov_deg=s30.emission.fov_deg,
            relax_moon=True, ledger=None, deficit_weight=0.0,
        )
        self.assertTrue(esp_c and s30_c)
        # NGC 7000 (~120'×100' = 2°×1.67°): overflows the Esprit 1.6° frame,
        # fits the S30 4.2°×2.4° field — driven purely by fov_deg.
        na_esp = self._candidate(esp_c, "NGC 7000")
        na_s30 = self._candidate(s30_c, "NGC 7000")
        self.assertIsNotNone(na_esp)
        self.assertIsNotNone(na_s30)
        self.assertFalse(na_esp.fits_fov)   # mosaic on the Esprit
        self.assertTrue(na_s30.fits_fov)    # single-frame on the S30

    def test_small_target_fits_both(self):
        cat = load_dso_catalog(CATALOG)
        esp, s30 = load_config(ESPRIT), load_config(S30)
        d = date(2026, 8, 15)
        for cfg, fov in ((esp, esp.emission.fov_deg), (s30, s30.emission.fov_deg)):
            cands = build_dso_candidates(
                cat, cfg, start_date=d, fov_deg=fov,
                relax_moon=True, ledger=None, deficit_weight=0.0,
            )
            crescent = self._candidate(cands, "NGC 6888")  # 18'×12'
            self.assertIsNotNone(crescent)
            self.assertTrue(crescent.fits_fov)

    def test_rim_kiss_within_tolerance_stays_single_frame(self):
        # Full IC 1396 (170'×140') vs the S30's measured 3.9°×2.2° field:
        # the 140' minor axis overflows the 132' short axis by ~6% — a diffuse
        # rim kiss, not a mosaic (it's the Catskills single-frame target).
        # FOV_FIT_TOLERANCE (10%/axis) must keep it fits_fov=True.
        cat = load_dso_catalog(CATALOG)
        s30 = load_config(S30)
        cands = build_dso_candidates(
            cat, s30, start_date=date(2026, 8, 15),
            fov_deg=s30.emission.fov_deg,
            relax_moon=True, ledger=None, deficit_weight=0.0,
        )
        ic1396 = self._candidate(cands, "IC 1396")
        self.assertIsNotNone(ic1396)
        self.assertTrue(ic1396.fits_fov)

    def test_static_mosaic_flag_not_blessed_by_tolerance(self):
        # The full Cygnus Loop carries the catalog's static mosaic=true (it
        # overflows even the S30). FOV_FIT_TOLERANCE must never bless a
        # static-flagged target as single-frame — the flag short-circuits.
        # (Beyond-tolerance *arithmetic* is pinned by NGC 7000 on the Esprit
        # in test_medium_giant_fits_s30_not_esprit: 1.67° minor vs 1.07°×1.1.)
        cat = load_dso_catalog(CATALOG)
        s30 = load_config(S30)
        cands = build_dso_candidates(
            cat, s30, start_date=date(2026, 8, 15),
            fov_deg=s30.emission.fov_deg,
            relax_moon=True, ledger=None, deficit_weight=0.0,
        )
        loop = self._candidate(cands, "Cygnus Loop")
        self.assertIsNotNone(loop)
        self.assertFalse(loop.fits_fov)
