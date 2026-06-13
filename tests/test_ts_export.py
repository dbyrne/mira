"""Tests for the Target Scheduler Level-1 export (nina_targets.csv from the
DSO/emission planners) and the catalog's optional pa_deg field."""
from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from mira.config import load_config
from mira.dso.catalog import _parse_target, load_dso_catalog
from mira.dso.planner import build_dso_candidates
from mira.dso.report import write_dso_plan, write_nina_targets_csv

CATALOG = Path("data/dso_catalog/emission_nebulae.yaml")
ESPRIT = Path("config/esprit120_jc.yaml")
S30 = Path("config/s30_pro_jc.yaml")


def _row(**overrides):
    base = dict(
        name="Test 1", object_type="HII", ra_deg=300.0, dec_deg=40.0,
        size_arcmin=[30, 20], budget_minutes={"Ha": 60},
    )
    base.update(overrides)
    return base


class SexagesimalCarryTests(unittest.TestCase):
    """The 60s bug: seconds rounding to the output precision must carry
    into minutes/hours/degrees (shipped nina_targets.csv carried
    `+57° 23' 60"` before the 2026-06-12 fix)."""

    def test_ra_seconds_carry(self):
        from mira.session_plan import ra_to_target_scheduler_hms
        # 21h 36m 59.9s must carry to 21h 37m 00s, never "60s"
        self.assertEqual(ra_to_target_scheduler_hms(324.249917), "21h 37m 00s")
        self.assertNotIn("60s", ra_to_target_scheduler_hms(324.249917))
        # 23h 59m 59.6s wraps to 00h 00m 00s
        self.assertEqual(ra_to_target_scheduler_hms(359.99875), "00h 00m 00s")

    def test_dec_seconds_carry(self):
        from mira.session_plan import dec_to_target_scheduler_dms
        self.assertEqual(dec_to_target_scheduler_dms(57.39989), "+57° 24' 00\"")
        self.assertEqual(dec_to_target_scheduler_dms(-0.99993), "-01° 00' 00\"")

    def test_hms_dms_decimal_variants_carry(self):
        from mira.session_plan import dec_to_dms, ra_to_hms
        self.assertEqual(ra_to_hms(359.9999999), "00:00:00.00")
        self.assertEqual(dec_to_dms(29.9999999), "+30:00:00.0")

    def test_shipped_catalogs_emit_no_60(self):
        from mira.session_plan import (
            dec_to_target_scheduler_dms,
            ra_to_target_scheduler_hms,
        )
        for cat_path in (CATALOG, Path("data/dso_catalog/sho_targets.yaml"),
                         Path("data/dso_catalog/galaxies.yaml")):
            for t in load_dso_catalog(cat_path).targets:
                self.assertNotIn("60s", ra_to_target_scheduler_hms(t.ra_deg))
                self.assertNotIn("60\"", dec_to_target_scheduler_dms(t.dec_deg))


class PaDegParsingTests(unittest.TestCase):
    def test_absent_pa_is_none(self):
        self.assertIsNone(_parse_target(_row()).pa_deg)

    def test_valid_pa_parses(self):
        self.assertEqual(_parse_target(_row(pa_deg=135)).pa_deg, 135.0)
        self.assertEqual(_parse_target(_row(pa_deg=0)).pa_deg, 0.0)

    def test_pa_360_normalizes_to_zero(self):
        # 360 is accepted as an author convention but must be STORED as 0 —
        # otherwise the TS export emits `Rotation,360`, outside [0, 360).
        self.assertEqual(_parse_target(_row(pa_deg=360)).pa_deg, 0.0)
        self.assertEqual(_parse_target(_row(pa_deg=360.0)).pa_deg, 0.0)

    def test_out_of_range_pa_rejected(self):
        with self.assertRaises(ValueError):
            _parse_target(_row(pa_deg=400))
        with self.assertRaises(ValueError):
            _parse_target(_row(pa_deg=-10))

    def test_non_numeric_pa_rejected(self):
        with self.assertRaises(ValueError):
            _parse_target(_row(pa_deg="sideways"))


class NinaTargetsCsvTests(unittest.TestCase):
    """Build real candidates from the shipped emission catalog (offline)
    and check the TS-import CSV they produce."""

    @classmethod
    def setUpClass(cls):
        cls.cat = load_dso_catalog(CATALOG)
        cfg = load_config(ESPRIT)
        cls.cands = build_dso_candidates(
            cls.cat, cfg, start_date=date(2026, 8, 15),
            fov_deg=cfg.emission.fov_deg,
            relax_moon=True, ledger=None, deficit_weight=0.0,
        )
        assert cls.cands, "no candidates built — observability regression?"

    def _read(self, path):
        with open(path, encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_csv_format_and_canonical_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nina_targets.csv"
            write_nina_targets_csv(self.cands, path)
            rows = self._read(path)
        self.assertEqual(len(rows), len(self.cands))
        self.assertEqual(
            list(rows[0].keys()),
            ["Type", "Name", "Ra", "Dec", "Rotation", "ROI"],
        )
        catalog_names = {t.name for t in self.cat.targets}
        for row in rows:
            # canonical names — the ledger-matching guarantee
            self.assertIn(row["Name"], catalog_names)
            self.assertEqual(row["ROI"], "100")
            # TS coordinate formats: "20h 12m 34s" / "+38° 21' 09\""
            self.assertRegex(row["Ra"], r"^\d{2}h \d{2}m \d{1,2}s$")
            self.assertRegex(row["Dec"], r"^[+-]\d{2}° \d{2}' \d{1,2}\"$")
            self.assertTrue(0 <= int(row["Rotation"]) < 360)

    def test_rotation_comes_from_catalog_pa(self):
        by_name = {t.name: t for t in self.cat.targets}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nina_targets.csv"
            write_nina_targets_csv(self.cands, path)
            rows = self._read(path)
        # The regenerated emission catalog carries pa_deg for the Esprit-book
        # rows; at least one candidate must export a nonzero Rotation, and
        # every Rotation must equal its catalog pa (or 0 when unset).
        nonzero = 0
        for row in rows:
            target = by_name[row["Name"]]
            expected = int(round(target.pa_deg)) if target.pa_deg is not None else 0
            self.assertEqual(int(row["Rotation"]), expected % 360)
            nonzero += int(row["Rotation"]) != 0
        self.assertGreater(nonzero, 0)

    def test_write_dso_plan_emits_all_three_files_and_footer(self):
        cfg_path = str(ESPRIT)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_dso_plan(
                self.cands, out,
                config_path=cfg_path,
                catalog_version=self.cat.version,
                start_date=date(2026, 8, 15),
                window_nights=14,
                ledger=None,
            )
            self.assertTrue((out / "dso_plan.md").is_file())
            self.assertTrue((out / "dso_plan.csv").is_file())
            self.assertTrue((out / "nina_targets.csv").is_file())
            md = (out / "dso_plan.md").read_text(encoding="utf-8")
        self.assertIn("NINA / Target Scheduler import", md)
        self.assertIn("One conductor per night", md)
        # rig-aware dither block: esprit config → PHD2 guidance
        self.assertIn("dithers through PHD2", md)
        self.assertNotIn("S30 dither WARNING", md)

    def test_s30_footer_carries_the_silent_noop_warning(self):
        cfg = load_config(S30)
        cands = build_dso_candidates(
            self.cat, cfg, start_date=date(2026, 8, 15),
            fov_deg=cfg.emission.fov_deg,
            relax_moon=True, ledger=None, deficit_weight=0.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_dso_plan(
                cands, out,
                config_path=str(S30),
                catalog_version=self.cat.version,
                start_date=date(2026, 8, 15),
                window_nights=14,
                ledger=None,
            )
            md = (out / "dso_plan.md").read_text(encoding="utf-8")
        self.assertIn("S30 dither WARNING", md)
        self.assertIn("Direct Guider", md)


if __name__ == "__main__":
    unittest.main()
