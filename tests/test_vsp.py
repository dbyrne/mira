from __future__ import annotations

from unittest import TestCase

from mira.vsp import (
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


class VspMalformedResponseTests(TestCase):
    """VSP responses can be malformed in production: missing fields,
    null values, partial photometry rows. parse_vsp_chart must surface
    a clean ValueError or skip bad rows rather than crash."""

    def test_missing_chartid_falls_back_to_na(self) -> None:
        chart = parse_vsp_chart({
            "star": "X",
            "ra": "12:00:00",
            "dec": "+00:00:00",
            "photometry": [
                {"label": "100", "ra": "12:00:30", "dec": "+00:01:00",
                 "bands": [{"band": "V", "mag": 10.0, "error": 0.05}]},
            ],
        })
        self.assertEqual(chart.chart_id, "na")

    def test_missing_photometry_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_vsp_chart({"chartid": "X", "star": "Y", "photometry": []})

    def test_skips_comp_with_invalid_coords(self) -> None:
        chart = parse_vsp_chart({
            "chartid": "X1",
            "star": "Y",
            "ra": "12:00:00",
            "dec": "+00:00:00",
            "photometry": [
                {"label": "good", "ra": "12:00:30", "dec": "+00:01:00",
                 "bands": [{"band": "V", "mag": 10.0, "error": 0.05}]},
                {"label": "bad-ra", "ra": "garbage", "dec": "+00:01:00",
                 "bands": [{"band": "V", "mag": 10.0, "error": 0.05}]},
                {"label": "bad-dec", "ra": "12:00:30", "dec": "not-a-coord",
                 "bands": [{"band": "V", "mag": 10.0, "error": 0.05}]},
            ],
        })
        labels = [c.label for c in chart.comps]
        self.assertEqual(labels, ["good"])

    def test_skips_comp_with_missing_band(self) -> None:
        chart = parse_vsp_chart({
            "chartid": "X1",
            "star": "Y",
            "ra": "12:00:00",
            "dec": "+00:00:00",
            "photometry": [
                {"label": "v-only", "ra": "12:00:30", "dec": "+00:01:00",
                 "bands": [{"band": "V", "mag": 10.0, "error": 0.05}]},
                {"label": "no-bands", "ra": "12:00:35", "dec": "+00:01:00",
                 "bands": []},
                {"label": "no-mag", "ra": "12:00:40", "dec": "+00:01:00",
                 "bands": [{"band": "V", "mag": None, "error": 0.05}]},
            ],
        })
        labels = [c.label for c in chart.comps]
        self.assertEqual(labels, ["v-only"])

    def test_label_falls_back_to_mag_when_blank(self) -> None:
        chart = parse_vsp_chart({
            "chartid": "X1",
            "star": "Y",
            "ra": "12:00:00",
            "dec": "+00:00:00",
            "photometry": [
                {"label": "", "ra": "12:00:30", "dec": "+00:01:00",
                 "bands": [{"band": "V", "mag": 9.7, "error": 0.05}]},
            ],
        })
        # Empty label → synthesize from magnitude
        self.assertEqual(chart.comps[0].label, "9.7")

    def test_filter_unknown_target_mag_returns_brightest(self) -> None:
        # When VSX has no bright_mag (rare but happens for some types),
        # filter_comps_for_target should still return a usable list.
        from mira.photometry import CompStar
        comps = [
            CompStar(label=f"c{i}", ra_deg=0, dec_deg=0,
                     catalog_mag=8.0 + i * 0.5, catalog_band="V")
            for i in range(8)
        ]
        result = filter_comps_for_target(comps, target_mag=None, max_count=4)
        self.assertEqual(len(result), 4)
        # Brightest first when target_mag is unknown
        self.assertEqual(result[0].label, "c0")
