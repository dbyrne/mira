from __future__ import annotations

from unittest import TestCase

from mira.scoring import is_classical_gcvs_name, is_survey_name, is_uncertain_type
from mira.vsx import tokenize_var_type, type_matches


class TypeMatchingTests(TestCase):
    def test_tokenize_strips_uncertainty_trailers(self) -> None:
        self.assertEqual(tokenize_var_type("SR:"), ["SR"])
        self.assertEqual(tokenize_var_type("EW|EA"), ["EW", "EA"])
        self.assertEqual(tokenize_var_type("RRAB/BL"), ["RRAB", "BL"])
        self.assertEqual(tokenize_var_type(""), [])
        self.assertEqual(tokenize_var_type("LB?"), ["LB"])

    def test_exact_token_match(self) -> None:
        self.assertTrue(type_matches("SR", ("SR",)))
        self.assertTrue(type_matches("SR:", ("SR",)))
        self.assertFalse(type_matches("SRA", ("SR",)))

    def test_prefix_wildcard_matches_family(self) -> None:
        self.assertTrue(type_matches("SR", ("SR*",)))
        self.assertTrue(type_matches("SRA", ("SR*",)))
        self.assertTrue(type_matches("SRB", ("SR*",)))
        self.assertTrue(type_matches("SRD", ("SR*",)))

    def test_prefix_wildcard_does_not_match_via_substring(self) -> None:
        # The chief regression we're guarding against: 'L' must not match 'ELL'.
        self.assertFalse(type_matches("ELL", ("L*",)))
        self.assertFalse(type_matches("ELL", ("L",)))
        self.assertTrue(type_matches("LB", ("L*",)))
        self.assertTrue(type_matches("L", ("L*",)))

    def test_alternate_types_split_on_pipe_and_slash(self) -> None:
        self.assertTrue(type_matches("EW|EA", ("EW",)))
        self.assertTrue(type_matches("EW|EA", ("EA",)))
        self.assertTrue(type_matches("RRAB/BL", ("RR*",)))

    def test_blank_type_is_question_mark(self) -> None:
        self.assertTrue(type_matches("", ("?",)))
        self.assertFalse(type_matches("", ("SR",)))


class UncertainTypeTests(TestCase):
    def test_real_modifiers_are_uncertain(self) -> None:
        self.assertTrue(is_uncertain_type(""))
        self.assertTrue(is_uncertain_type("SR:"))
        self.assertTrue(is_uncertain_type("SR?"))
        self.assertTrue(is_uncertain_type("EW|EA"))
        self.assertTrue(is_uncertain_type("VAR"))
        self.assertTrue(is_uncertain_type("MISC"))

    def test_well_defined_types_are_certain(self) -> None:
        # The chief regression: the old code flagged SR/SRS/L/LB as uncertain.
        self.assertFalse(is_uncertain_type("SR"))
        self.assertFalse(is_uncertain_type("SRA"))
        self.assertFalse(is_uncertain_type("SRB"))
        self.assertFalse(is_uncertain_type("SRS"))
        self.assertFalse(is_uncertain_type("L"))
        self.assertFalse(is_uncertain_type("LB"))
        self.assertFalse(is_uncertain_type("M"))
        self.assertFalse(is_uncertain_type("EA"))
        self.assertFalse(is_uncertain_type("RRAB"))

    def test_compound_type_with_slash_is_certain(self) -> None:
        # 'RRAB/BL' is a confirmed RRAB with Blazhko effect - not uncertain.
        self.assertFalse(is_uncertain_type("RRAB/BL"))
        self.assertFalse(is_uncertain_type("EA/SD"))


class NameClassificationTests(TestCase):
    def test_classical_gcvs_names(self) -> None:
        self.assertTrue(is_classical_gcvs_name("RR Cam"))
        self.assertTrue(is_classical_gcvs_name("VX CrB"))
        self.assertTrue(is_classical_gcvs_name("U Mon"))
        self.assertTrue(is_classical_gcvs_name("V0492 Aur"))
        self.assertTrue(is_classical_gcvs_name("V404 Cyg"))

    def test_non_classical_names(self) -> None:
        self.assertFalse(is_classical_gcvs_name("ASASSN-V J160002.35+453848.8"))
        self.assertFalse(is_classical_gcvs_name("Gaia DR3 4503175632500692480"))
        self.assertFalse(is_classical_gcvs_name("WISE J120003.9+632552"))
        self.assertFalse(is_classical_gcvs_name("HD 12345"))

    def test_classical_and_survey_are_mutually_exclusive(self) -> None:
        for survey in ("ASASSN-V J160002.35+453848.8", "Gaia DR3 1", "ZTF J0000+0000"):
            self.assertTrue(is_survey_name(survey))
            self.assertFalse(is_classical_gcvs_name(survey))
        for classical in ("RR Cam", "V0492 Aur"):
            self.assertFalse(is_survey_name(classical))
            self.assertTrue(is_classical_gcvs_name(classical))
