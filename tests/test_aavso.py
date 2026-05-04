from __future__ import annotations

from unittest import TestCase

from anomaly_scout.aavso import count_cdata_csv_rows


class AavsoTests(TestCase):
    def test_count_cdata_csv_rows(self) -> None:
        xml = """<?xml version="1.0"?><VSXObject><Data><![CDATA[JD,mag,band
2460000.1,12.3,V
2460001.1,12.4,V
]]></Data></VSXObject>"""
        self.assertEqual(count_cdata_csv_rows(xml), 2)

