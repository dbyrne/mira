from __future__ import annotations

from unittest import TestCase

from mira.config import SimbadConfig
from mira.simbad import parse_simbad_rows


class SimbadTests(TestCase):
    def test_parse_simbad_rows_collects_identifiers(self) -> None:
        text = (
            "main_id\totype\tra\tdec\tid\tdist_deg\n"
            '"2MASS J16000234+4538488"\t"S*?"\t240.0\t45.0\t"Gaia DR3 1"\t1E-6\n'
            '"2MASS J16000234+4538488"\t"S*?"\t240.0\t45.0\t"2MASS J16000234+4538488"\t1E-6\n'
        )
        config = SimbadConfig(enabled=True, enrich_top=1, search_radius_arcsec=5.0, timeout_seconds=20)
        stats = parse_simbad_rows(text, 240.0, 45.0, config)
        self.assertEqual(stats.status, "ok")
        self.assertEqual(stats.main_id, "2MASS J16000234+4538488")
        self.assertEqual(stats.object_type, "S*?")
        self.assertAlmostEqual(stats.separation_arcsec or 0, 0.0036)
        self.assertIn("Gaia DR3 1", stats.identifiers)

