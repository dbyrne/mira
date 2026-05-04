from __future__ import annotations

from unittest import TestCase

from anomaly_scout.config import GaiaConfig
from anomaly_scout.gaia import absolute_g_mag, angular_separation_arcsec, parse_gaia_tsv


class GaiaTests(TestCase):
    def test_absolute_g_mag(self) -> None:
        self.assertAlmostEqual(absolute_g_mag(10.0, 10.0) or 0, 5.0)
        self.assertIsNone(absolute_g_mag(10.0, 0.0))

    def test_angular_separation_arcsec(self) -> None:
        sep = angular_separation_arcsec(10.0, 20.0, 10.0, 20.001)
        self.assertAlmostEqual(sep, 3.6, places=2)

    def test_parse_gaia_tsv(self) -> None:
        text = (
            "Source\tRA_ICRS\tDE_ICRS\tGmag\tBP-RP\tPlx\te_Plx\tRUWE\n"
            " \tdeg\tdeg\tmag\tmag\tmas\tmas\t\n"
            "-------------------\t---------------\t---------------\t---------\t---------\t---------\t-------\t-------\n"
            "1398447265748971008\t240.00978072665\t+45.64689819482\t11.711650\t2.471256\t0.1261\t0.0152\t1.134\n"
        )
        config = GaiaConfig(enabled=True, enrich_top=1, search_radius_arcsec=5.0, timeout_seconds=20)
        stats = parse_gaia_tsv(text, 240.00978, 45.64691, config)
        self.assertEqual(stats.status, "ok")
        self.assertEqual(stats.source_id, "1398447265748971008")
        self.assertAlmostEqual(stats.bp_rp or 0, 2.471256)
        self.assertLess(stats.separation_arcsec or 999, 0.1)

