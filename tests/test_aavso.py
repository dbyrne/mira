from __future__ import annotations

from unittest import TestCase

from mira.aavso import count_cdata_csv_rows, parse_cdata_observations


class AavsoTests(TestCase):
    def test_count_cdata_csv_rows(self) -> None:
        xml = """<?xml version="1.0"?><VSXObject><Data><![CDATA[JD,mag,band
2460000.1,12.3,V
2460001.1,12.4,V
]]></Data></VSXObject>"""
        self.assertEqual(count_cdata_csv_rows(xml), 2)

    def test_parse_cdata_observations(self) -> None:
        xml = """<?xml version="1.0"?><VSXObject><Data><![CDATA[JD,mag,band
2460000.1,12.3,V
2460001.5,12.4,Vis.
2460003.0,12.5,V
]]></Data></VSXObject>"""
        obs = parse_cdata_observations(xml)
        self.assertEqual(len(obs), 3)
        self.assertEqual(obs[0], (2460000.1, 12.3, "V"))
        self.assertEqual(obs[1][2], "Vis.")

    def test_parse_skips_blank_rows(self) -> None:
        xml = """<?xml version="1.0"?><VSXObject><Data><![CDATA[JD,mag,band
2460000.1,12.3,V
,,
2460003.0,12.5,V
]]></Data></VSXObject>"""
        obs = parse_cdata_observations(xml)
        self.assertEqual(len(obs), 2)

