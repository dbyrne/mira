"""Tests for the DSO catalog loader. Catalogs are hand-edited YAML, so the
schema-validation messages need to be readable — these tests pin both the
happy path and the readable-error paths."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import yaml

from mira.dso.catalog import (
    KNOWN_OBJECT_TYPES,
    DsoCatalog,
    DsoTarget,
    load_dso_catalog,
)


def _write_catalog(dir_path: Path, raw: dict) -> Path:
    path = dir_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


VALID_TARGET = {
    "name": "NGC 6888",
    "common_name": "Crescent Nebula",
    "object_type": "WR",
    "ra_deg": 303.025,
    "dec_deg": 38.35,
    "size_arcmin": [18, 13],
    "constellation": "Cyg",
    "budget_minutes": {"Ha": 600, "OIII": 900, "SII": 540},
    "notes": "OIII shell is the headline",
}


class LoadDsoCatalogTests(TestCase):
    def test_loads_valid_catalog(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {
                "catalog_version": "test-1",
                "defaults": {"gain": 100},
                "targets": [VALID_TARGET],
            })
            cat = load_dso_catalog(path)
            self.assertIsInstance(cat, DsoCatalog)
            self.assertEqual(cat.version, "test-1")
            self.assertEqual(len(cat.targets), 1)
            t = cat.targets[0]
            self.assertEqual(t.name, "NGC 6888")
            self.assertEqual(t.object_type, "WR")
            self.assertEqual(t.size_arcmin, (18.0, 13.0))
            self.assertEqual(t.budget_minutes["Ha"], 600)

    def test_missing_file_raises_filenotfound(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertRaises(
                FileNotFoundError,
                load_dso_catalog, Path(tmp) / "nope.yaml",
            )

    def test_empty_targets_list_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {"targets": []})
            with self.assertRaises(ValueError) as cm:
                load_dso_catalog(path)
            self.assertIn("non-empty", str(cm.exception))

    def test_unknown_object_type_rejected(self) -> None:
        # Strict on types so YAML typos don't silently lose targets.
        bad = {**VALID_TARGET, "object_type": "QUASAR"}
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {"targets": [bad]})
            with self.assertRaises(ValueError) as cm:
                load_dso_catalog(path)
            self.assertIn("QUASAR", str(cm.exception))
            self.assertIn("object_type", str(cm.exception))

    def test_known_object_types_all_accepted(self) -> None:
        # Every code in KNOWN_OBJECT_TYPES must parse — guards against an
        # entry accidentally getting removed from the loader's whitelist.
        for code in KNOWN_OBJECT_TYPES:
            with self.subTest(code=code):
                with TemporaryDirectory() as tmp:
                    path = _write_catalog(Path(tmp), {
                        "targets": [{**VALID_TARGET, "object_type": code}],
                    })
                    load_dso_catalog(path)

    def test_out_of_range_ra_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {
                "targets": [{**VALID_TARGET, "ra_deg": 999}],
            })
            with self.assertRaises(ValueError) as cm:
                load_dso_catalog(path)
            self.assertIn("ra_deg", str(cm.exception))

    def test_negative_ra_rejected(self) -> None:
        # The old -360..360 range let a pasted negative RA through, which
        # survived into the TS export as a garbage sexagesimal row. Strict
        # [0, 360) now: negative RA and 360.0 itself are both errors.
        for bad_ra in (-10.0, -0.001, 360.0, 360):
            with self.subTest(ra_deg=bad_ra):
                with TemporaryDirectory() as tmp:
                    path = _write_catalog(Path(tmp), {
                        "targets": [{**VALID_TARGET, "ra_deg": bad_ra}],
                    })
                    with self.assertRaises(ValueError) as cm:
                        load_dso_catalog(path)
                    self.assertIn("ra_deg", str(cm.exception))

    def test_ra_zero_accepted(self) -> None:
        # The boundary that must stay valid: RA 0 is a real coordinate.
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {
                "targets": [{**VALID_TARGET, "ra_deg": 0.0}],
            })
            cat = load_dso_catalog(path)
            self.assertEqual(cat.targets[0].ra_deg, 0.0)

    def test_fractional_budget_rejected(self) -> None:
        # int(90.5) used to silently truncate to 90 — a hand-edit typo the
        # strict loader elsewhere would have caught. Now a ValueError.
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {
                "targets": [{**VALID_TARGET, "budget_minutes": {"Ha": 90.5}}],
            })
            with self.assertRaises(ValueError) as cm:
                load_dso_catalog(path)
            self.assertIn("whole minutes", str(cm.exception))
            self.assertIn("90.5", str(cm.exception))

    def test_integral_float_budget_accepted(self) -> None:
        # 90.0 is a valid spelling of 90 — only truly fractional values reject.
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {
                "targets": [{**VALID_TARGET, "budget_minutes": {"Ha": 90.0}}],
            })
            cat = load_dso_catalog(path)
            self.assertEqual(cat.targets[0].budget_minutes["Ha"], 90)

    def test_out_of_range_dec_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {
                "targets": [{**VALID_TARGET, "dec_deg": -91}],
            })
            with self.assertRaises(ValueError) as cm:
                load_dso_catalog(path)
            self.assertIn("dec_deg", str(cm.exception))

    def test_negative_budget_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {
                "targets": [{**VALID_TARGET, "budget_minutes": {"Ha": -1}}],
            })
            with self.assertRaises(ValueError) as cm:
                load_dso_catalog(path)
            self.assertIn("non-negative", str(cm.exception))

    def test_duplicate_names_rejected(self) -> None:
        # Catch hand-edit foot-gun where the same target gets pasted twice.
        with TemporaryDirectory() as tmp:
            path = _write_catalog(Path(tmp), {
                "targets": [VALID_TARGET, {**VALID_TARGET}],
            })
            with self.assertRaises(ValueError) as cm:
                load_dso_catalog(path)
            self.assertIn("duplicate", str(cm.exception).lower())


class DsoCatalogShippedTests(TestCase):
    """Validate the actual shipped catalog at data/dso_catalog/sho_targets.yaml.
    Lightweight sanity check — every target must parse, no duplicates, all
    dec >= -25 (we're targeting from Jersey City at lat ~40N)."""

    def test_all_shipped_catalogs_load_under_strict_ra_range(self) -> None:
        # The loader now rejects ra_deg outside [0, 360); every shipped
        # catalog must comply (i.e. keep loading) under the strict rule.
        for rel in ("data/dso_catalog/sho_targets.yaml",
                    "data/dso_catalog/galaxies.yaml",
                    "data/dso_catalog/emission_nebulae.yaml"):
            path = Path(rel)
            if not path.exists():
                self.skipTest(f"shipped catalog not present at {path}")
            cat = load_dso_catalog(path)
            for target in cat.targets:
                with self.subTest(catalog=rel, target=target.name):
                    self.assertTrue(0.0 <= target.ra_deg < 360.0)

    def test_shipped_catalog_loads_and_is_jc_friendly(self) -> None:
        path = Path("data/dso_catalog/sho_targets.yaml")
        if not path.exists():
            self.skipTest(f"shipped catalog not present at {path}")
        cat = load_dso_catalog(path)
        self.assertGreater(len(cat.targets), 30)
        for target in cat.targets:
            with self.subTest(target=target.name):
                # JC dec floor: target must rise above horizon (lat - 90 + 0)
                # = -49 in principle, but practical altitude floor at 25° means
                # dec >= lat - 90 + 25 = -25°.
                self.assertGreaterEqual(
                    target.dec_deg, -25.0,
                    f"{target.name} at dec {target.dec_deg} can't reach 25° "
                    "altitude from Jersey City"
                )
                self.assertGreater(
                    target.total_budget_minutes, 0,
                    f"{target.name} has zero total budget"
                )


class RenderResearchNotesTests(TestCase):
    """Lightweight smoke tests for the research-notes generator. The
    Markdown is for human reading, so pin a few structural invariants
    rather than the full content."""

    def _catalog(self) -> DsoCatalog:
        return DsoCatalog(
            version="t-1", defaults={},
            targets=(
                # Two targets in different seasons + a mosaic + a broadband-only
                # so the season grouping, mosaic note, and link generation all
                # exercise.
                DsoTarget(
                    name="NGC 6888", common_name="Crescent Nebula",
                    object_type="WR",
                    ra_deg=303.025, dec_deg=38.35,
                    size_arcmin=(18, 13), constellation="Cyg",
                    budget_minutes={"Ha": 600, "OIII": 900},
                    notes="OIII shell",
                ),
                DsoTarget(
                    name="IC 1396", common_name="Elephant's Trunk",
                    object_type="HII",
                    ra_deg=324.5, dec_deg=57.5,
                    size_arcmin=(170, 140), constellation="Cep",
                    budget_minutes={"Ha": 600},
                    mosaic=True,
                ),
                DsoTarget(
                    name="NGC 7023", common_name="Iris Nebula",
                    object_type="REF",
                    ra_deg=315.379, dec_deg=68.158,
                    size_arcmin=(18, 18), constellation="Cep",
                    budget_minutes={"L": 360, "R": 240},
                    notes="Reflection nebula",
                ),
            ),
        )

    def test_includes_every_target_with_anchor(self) -> None:
        # The index anchor must slug the FULL heading ("name — common"), not
        # just the name — a name-only slug is a dead link in GitHub-style
        # renderers. Pin the exact expected anchors (hand-computed per
        # GitHub's algorithm: em-dash dropped, flanking spaces → "--").
        from mira.dso.research import render_research_notes
        md = render_research_notes(self._catalog())
        expected = {
            "NGC 6888": ("Crescent Nebula", "ngc-6888--crescent-nebula"),
            "IC 1396": ("Elephant's Trunk", "ic-1396--elephants-trunk"),
            "NGC 7023": ("Iris Nebula", "ngc-7023--iris-nebula"),
        }
        for name, (common, anchor) in expected.items():
            with self.subTest(name=name):
                self.assertIn(
                    f"### {name} — {common}", md,
                    f"missing detail header for {name}",
                )
                self.assertIn(
                    f"](#{anchor})", md, f"missing index anchor for {name}",
                )

    def test_slug_matches_github_algorithm(self) -> None:
        # Hand-verified GitHub anchor behavior: lowercase; word chars and
        # hyphens kept (underscore is a word char — preserved, NOT mapped to
        # a hyphen); spaces → hyphens; all other punctuation dropped. The
        # em-dash is punctuation, so " — " yields "--" (its two flanking
        # spaces survive as hyphens).
        from mira.dso.research import _slug
        self.assertEqual(
            _slug("NGC 6888 — Crescent Nebula"), "ngc-6888--crescent-nebula",
        )
        self.assertEqual(
            _slug("IC 1396 — Elephant's Trunk"), "ic-1396--elephants-trunk",
        )
        self.assertEqual(_slug("Sh2-101 — Tulip"), "sh2-101--tulip")
        self.assertEqual(_slug("foo_bar Baz"), "foo_bar-baz")

    def test_mosaic_flagged_in_detail(self) -> None:
        from mira.dso.research import render_research_notes
        md = render_research_notes(self._catalog())
        # Mosaic target gets the bold marker; non-mosaic doesn't.
        idx_mosaic = md.find("### IC 1396")
        idx_solo = md.find("### NGC 6888")
        self.assertGreater(idx_mosaic, 0)
        # Find the line containing the FOV note for each
        mosaic_block = md[idx_mosaic:idx_mosaic + 400]
        solo_block = md[idx_solo:idx_solo + 400]
        self.assertIn("mosaic candidate", mosaic_block)
        self.assertNotIn("mosaic candidate", solo_block)

    def test_research_links_present(self) -> None:
        from mira.dso.research import render_research_notes
        md = render_research_notes(self._catalog())
        for site in ("simbad", "aladin", "ned", "telescopius", "astrobin"):
            self.assertIn(site, md.lower(), f"missing {site} link")
        # Wikipedia link only when common_name differs from name
        self.assertIn("Wikipedia", md)

    def test_target_with_no_common_name_skips_wikipedia(self) -> None:
        from mira.dso.research import render_research_notes
        # Same name + common_name → wikipedia URL guess is too noisy; skip it.
        cat = DsoCatalog(version="t", defaults={}, targets=(
            DsoTarget(
                name="Abell 78", common_name="Abell 78",
                object_type="WR",
                ra_deg=326.5, dec_deg=31.5,
                size_arcmin=(2, 2), constellation="Cyg",
                budget_minutes={"OIII": 1200},
            ),
        ))
        md = render_research_notes(cat)
        # SIMBAD/Telescopius links should be present; Wikipedia omitted
        self.assertIn("simbad", md.lower())
        # Look for the link list line specifically
        link_lines = [ln for ln in md.splitlines() if "**Research:**" in ln]
        self.assertEqual(len(link_lines), 1)
        self.assertNotIn("Wikipedia", link_lines[0])

    def test_seasons_grouped(self) -> None:
        from mira.dso.research import render_research_notes
        md = render_research_notes(self._catalog())
        # All three test targets are RA 20-21h → Summer. Season header must
        # be present; other seasons must NOT appear since they're empty.
        self.assertIn("## Summer", md)
        self.assertNotIn("## Winter", md)
        self.assertNotIn("## Spring", md)
        self.assertNotIn("## Autumn", md)

    def test_all_seasons_covered_by_shipped_catalog(self) -> None:
        """The shipped catalog spans all four seasons — guards against an
        accidental edit that drains a whole bucket."""
        from mira.dso.research import render_research_notes
        from mira.dso.catalog import load_dso_catalog
        path = Path("data/dso_catalog/sho_targets.yaml")
        if not path.exists():
            self.skipTest("shipped catalog not present")
        md = render_research_notes(load_dso_catalog(path))
        for season in ("Winter", "Spring", "Summer", "Autumn"):
            self.assertIn(
                f"## {season}", md,
                f"shipped catalog has no targets in {season} bucket"
            )


class CoordinateFormatTests(TestCase):
    def test_ra_hms_zero(self) -> None:
        from mira.dso.research import _ra_hms
        self.assertEqual(_ra_hms(0.0), "00h 00m 00.0s")

    def test_ra_hms_180_is_12h(self) -> None:
        from mira.dso.research import _ra_hms
        self.assertEqual(_ra_hms(180.0), "12h 00m 00.0s")

    def test_ra_hms_wraps_at_360(self) -> None:
        # Some catalog rows might be near 360 from external sources; modulo it.
        from mira.dso.research import _ra_hms
        self.assertEqual(_ra_hms(360.0), "00h 00m 00.0s")

    def test_dec_dms_positive(self) -> None:
        from mira.dso.research import _dec_dms
        self.assertTrue(_dec_dms(38.35).startswith("+38° 21'"))

    def test_dec_dms_negative(self) -> None:
        from mira.dso.research import _dec_dms
        self.assertTrue(_dec_dms(-5.391).startswith("-05° 23'"))


class DsoTargetPropsTests(TestCase):
    def test_is_narrowband_with_ha(self) -> None:
        t = DsoTarget(
            name="x", common_name="y", object_type="HII",
            ra_deg=0, dec_deg=0, size_arcmin=(1, 1), constellation="",
            budget_minutes={"Ha": 100},
        )
        self.assertTrue(t.is_narrowband)

    def test_is_narrowband_zero_means_no(self) -> None:
        # Budget present but zero shouldn't count as narrowband — pinning it
        # so a hand-edit that explicitly sets `Ha: 0` doesn't accidentally
        # opt in to moon-relax.
        t = DsoTarget(
            name="x", common_name="y", object_type="REF",
            ra_deg=0, dec_deg=0, size_arcmin=(1, 1), constellation="",
            budget_minutes={"Ha": 0, "L": 240},
        )
        self.assertFalse(t.is_narrowband)

    def test_is_narrowband_false_for_pure_broadband(self) -> None:
        t = DsoTarget(
            name="x", common_name="y", object_type="REF",
            ra_deg=0, dec_deg=0, size_arcmin=(1, 1), constellation="",
            budget_minutes={"L": 240, "R": 180, "G": 180, "B": 180},
        )
        self.assertFalse(t.is_narrowband)

    def test_lp_budget_does_not_make_narrowband(self) -> None:
        # The emission catalog budgets LP for the S30 alongside Ha/OIII/SII.
        # is_narrowband checks Ha/OIII/SII ONLY — an LP key must neither
        # grant narrowband status on its own nor revoke it when present
        # next to a real narrowband budget.
        lp_only = DsoTarget(
            name="x", common_name="y", object_type="GALAXY",
            ra_deg=0, dec_deg=0, size_arcmin=(1, 1), constellation="",
            budget_minutes={"LP": 180},
        )
        self.assertFalse(lp_only.is_narrowband)
        nb_plus_lp = DsoTarget(
            name="x", common_name="y", object_type="HII",
            ra_deg=0, dec_deg=0, size_arcmin=(1, 1), constellation="",
            budget_minutes={"Ha": 150, "OIII": 150, "LP": 180},
        )
        self.assertTrue(nb_plus_lp.is_narrowband)

    def test_total_budget_minutes(self) -> None:
        t = DsoTarget(
            name="x", common_name="y", object_type="HII",
            ra_deg=0, dec_deg=0, size_arcmin=(1, 1), constellation="",
            budget_minutes={"Ha": 600, "OIII": 720, "SII": 540},
        )
        self.assertEqual(t.total_budget_minutes, 1860)

    def test_by_name_is_case_insensitive(self) -> None:
        t = DsoTarget(
            name="NGC 6888", common_name="", object_type="WR",
            ra_deg=0, dec_deg=0, size_arcmin=(1, 1), constellation="",
            budget_minutes={"Ha": 100},
        )
        cat = DsoCatalog(version="x", defaults={}, targets=(t,))
        self.assertIsNotNone(cat.by_name("ngc 6888"))
        self.assertIsNotNone(cat.by_name("NGC 6888"))
        self.assertIsNone(cat.by_name("M42"))
