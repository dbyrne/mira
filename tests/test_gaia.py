from __future__ import annotations

from unittest import TestCase

from mira.gaia import (
    color_type_disagreement,
    extract_gaia_dr3_source_id,
    parse_gaia_csv,
)


class GaiaSourceIdExtractTests(TestCase):
    def test_extracts_from_canonical_name(self) -> None:
        self.assertEqual(
            extract_gaia_dr3_source_id("Gaia DR3 1991157769123098752"),
            "1991157769123098752",
        )

    def test_handles_lowercase_and_extra_whitespace(self) -> None:
        self.assertEqual(extract_gaia_dr3_source_id("gaia  DR3   1234567"), "1234567")

    def test_handles_embedded_in_longer_string(self) -> None:
        self.assertEqual(
            extract_gaia_dr3_source_id("V0492 Aur (also Gaia DR3 1234567)"),
            "1234567",
        )

    def test_returns_none_for_non_gaia_names(self) -> None:
        self.assertIsNone(extract_gaia_dr3_source_id("RR Lyr"))
        self.assertIsNone(extract_gaia_dr3_source_id("ASASSN-V J160002.35+453848.8"))
        self.assertIsNone(extract_gaia_dr3_source_id(""))
        self.assertIsNone(extract_gaia_dr3_source_id(None))


class ColorTypeDisagreementTests(TestCase):
    def test_m_type_blue_color_flagged(self) -> None:
        flag = color_type_disagreement("M", 1.0)
        self.assertIsNotNone(flag)
        self.assertIn("M", flag)

    def test_m_type_red_color_passes(self) -> None:
        self.assertIsNone(color_type_disagreement("M", 2.0))

    def test_sr_family_too_blue_flagged(self) -> None:
        for var_type in ("SR", "SRA", "SRB"):
            self.assertIsNotNone(color_type_disagreement(var_type, 0.5))

    def test_l_family_too_blue_flagged(self) -> None:
        self.assertIsNotNone(color_type_disagreement("LB", 0.5))

    def test_short_period_too_red_flagged(self) -> None:
        for var_type in ("RRAB", "EA", "EB", "EW", "DSCT"):
            self.assertIsNotNone(color_type_disagreement(var_type, 2.0))

    def test_consistent_classifications_pass(self) -> None:
        # Mira / SR / L should be red; pulsators / eclipsing should be blue/white
        self.assertIsNone(color_type_disagreement("SRA", 1.5))
        self.assertIsNone(color_type_disagreement("RRAB", 0.5))
        self.assertIsNone(color_type_disagreement("EA", 0.8))

    def test_missing_color_returns_none(self) -> None:
        self.assertIsNone(color_type_disagreement("M", None))


class GaiaCsvParseTests(TestCase):
    def test_parse_typical_response(self) -> None:
        text = (
            "source_id,phot_g_mean_mag,bp_rp,parallax,parallax_error,ruwe,phot_variable_flag,dist_deg\n"
            "1234567890,11.5,1.85,2.4,0.05,1.02,VARIABLE,1.0E-5\n"
        )
        stats = parse_gaia_csv(text)
        self.assertEqual(stats.status, "ok")
        self.assertEqual(stats.source_id, "1234567890")
        self.assertAlmostEqual(stats.g_mag, 11.5)
        self.assertAlmostEqual(stats.bp_rp, 1.85)
        self.assertAlmostEqual(stats.parallax_mas, 2.4)
        self.assertAlmostEqual(stats.ruwe, 1.02)
        self.assertTrue(stats.photometric_variable)
        self.assertAlmostEqual(stats.separation_arcsec, 0.036, places=2)

    def test_empty_response_yields_no_match(self) -> None:
        text = "source_id,phot_g_mean_mag,bp_rp,parallax,parallax_error,ruwe,phot_variable_flag,dist_deg\n"
        stats = parse_gaia_csv(text)
        self.assertEqual(stats.status, "no-match")
