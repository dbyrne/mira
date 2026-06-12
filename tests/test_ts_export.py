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


class PaDegParsingTests(unittest.TestCase):
    def test_absent_pa_is_none(self):
        self.assertIsNone(_parse_target(_row()).pa_deg)

    def test_valid_pa_parses(self):
        self.assertEqual(_parse_target(_row(pa_deg=135)).pa_deg, 135.0)
        self.assertEqual(_parse_target(_row(pa_deg=0)).pa_deg, 0.0)

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
