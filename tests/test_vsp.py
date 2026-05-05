from __future__ import annotations

from unittest import TestCase

from anomaly_scout.vsp import (
    _dms_to_deg,
    _hms_to_deg,
    filter_comps_for_target,
    parse_vsp_chart,
)


SAMPLE_CHART = {
    "auid": "000-BCT-000",
    "chartid": "X32985CY",
    "star": "RR LYR",
    "ra": "19:25:27.91",
    "dec": "+42:47:03.7",
    "fov": 60.0,
    "maglimit": 14.5,
    "image_uri": "https://app.aavso.org/vsp/chart/X32985CY.png",
    "photometry": [
        {
            "auid": "000-BCT-001",
            "ra": "19:24:36.43",
            "dec": "+42:48:42.6",
            "label": "85",
            "bands": [
                {"band": "V", "mag": 8.512, "error": 0.041},
                {"band": "B", "mag": 9.234, "error": 0.052},
            ],
        },
        {
            "auid": "000-BCT-002",
            "ra": "19:25:55.20",
            "dec": "+42:50:11.0",
            "label": "97",
            "bands": [{"band": "V", "mag": 9.712, "error": 0.045}],
        },
        {
            "auid": "000-BCT-003",
            "ra": "19:26:10.00",
            "dec": "+42:46:22.0",
            "label": "112",
            "bands": [{"band": "V", "mag": 11.234, "error": 0.062}],
        },
        {
            "auid": "000-BCT-004",
            "ra": "19:27:00.00",
            "dec": "+42:43:00.0",
            "label": "B-only",
            "bands": [{"band": "B", "mag": 10.500, "error": 0.06}],
        },
    ],
}


class VspParseTests(TestCase):
    def test_parse_extracts_chart_metadata(self) -> None:
        chart = parse_vsp_chart(SAMPLE_CHART)
        self.assertEqual(chart.chart_id, "X32985CY")
        self.assertEqual(chart.star_name, "RR LYR")
        self.assertAlmostEqual(chart.target_ra_deg, (19 + 25 / 60 + 27.91 / 3600) * 15, places=3)
        self.assertAlmostEqual(chart.target_dec_deg, 42 + 47 / 60 + 3.7 / 3600, places=3)

    def test_parse_returns_v_band_comps(self) -> None:
        chart = parse_vsp_chart(SAMPLE_CHART, band="V")
        # 3 V-band comps; the B-only entry should be skipped
        self.assertEqual(len(chart.comps), 3)
        labels = [c.label for c in chart.comps]
        self.assertIn("85", labels)
        self.assertIn("97", labels)
        self.assertIn("112", labels)
        self.assertNotIn("B-only", labels)

    def test_parse_b_band(self) -> None:
        chart = parse_vsp_chart(SAMPLE_CHART, band="B")
        # Only the first and B-only comps have B-band entries
        self.assertEqual(len(chart.comps), 2)

    def test_parse_raises_when_no_comps_in_band(self) -> None:
        with self.assertRaises(ValueError):
            parse_vsp_chart(SAMPLE_CHART, band="I")

    def test_filter_by_target_mag(self) -> None:
        chart = parse_vsp_chart(SAMPLE_CHART)
        comps = filter_comps_for_target(chart.comps, target_mag=9.5, mag_tolerance=2.0)
        # Within ±2 of 9.5: 8.512, 9.712, 11.234 (since 11.234 - 9.5 = 1.73)
        self.assertEqual(len(comps), 3)
        # Sorted closest to 9.5 first: 9.712 (delta 0.21), 8.512 (delta 0.99), 11.234 (delta 1.73)
        self.assertEqual(comps[0].label, "97")

    def test_filter_drops_outside_tolerance(self) -> None:
        chart = parse_vsp_chart(SAMPLE_CHART)
        comps = filter_comps_for_target(chart.comps, target_mag=9.0, mag_tolerance=0.6)
        # Only 8.512 (delta 0.488) and 9.712 (delta 0.712) — actually 9.712 is outside 0.6
        # So only 8.512
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].label, "85")

    def test_filter_max_count(self) -> None:
        chart = parse_vsp_chart(SAMPLE_CHART)
        comps = filter_comps_for_target(chart.comps, target_mag=9.5, max_count=2)
        self.assertEqual(len(comps), 2)

    def test_filter_unknown_target_mag_returns_brightest(self) -> None:
        chart = parse_vsp_chart(SAMPLE_CHART)
        comps = filter_comps_for_target(chart.comps, target_mag=None, max_count=2)
        self.assertEqual(len(comps), 2)
        self.assertEqual(comps[0].label, "85")  # mag 8.512 — brightest


class CoordParseTests(TestCase):
    def test_hms_basic(self) -> None:
        self.assertAlmostEqual(_hms_to_deg("12:00:00"), 180.0)
        self.assertAlmostEqual(_hms_to_deg("19:25:27.91"), (19 + 25 / 60 + 27.91 / 3600) * 15)

    def test_hms_returns_none_on_garbage(self) -> None:
        self.assertIsNone(_hms_to_deg(""))
        self.assertIsNone(_hms_to_deg("not-a-coordinate"))

    def test_dms_handles_signs(self) -> None:
        self.assertAlmostEqual(_dms_to_deg("+42:47:03.7"), 42 + 47 / 60 + 3.7 / 3600, places=4)
        self.assertAlmostEqual(_dms_to_deg("-12:30:00"), -(12 + 30 / 60), places=4)
        self.assertAlmostEqual(_dms_to_deg("00:00:00"), 0.0)

    def test_dms_returns_none_on_garbage(self) -> None:
        self.assertIsNone(_dms_to_deg(""))
        self.assertIsNone(_dms_to_deg("garbage"))
