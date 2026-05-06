"""Network error path tests for vsx module — retry behavior, target name
matching, malformed responses. We mock cached_get at the vsx module
boundary so we don't touch the disk cache or real network.

These cover real production hazards: VizieR returning 5xx during a busy
window, transient DNS issues, partial result sets."""
from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests

from anomaly_scout import vsx


def _ok_response(tsv_text: str) -> MagicMock:
    response = MagicMock()
    response.text = tsv_text
    response.raise_for_status = MagicMock()  # no-op
    return response


def _erroring_response(exc: Exception) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock(side_effect=exc)
    return response


SAMPLE_TSV = (
    "OID\tName\tType\tmax\tn_max\tmin\tn_min\tl_min\tPeriod\tSp\tRAJ2000\tDEJ2000\n"
    "string\tstring\tstring\tdouble\tstring\tdouble\tstring\tstring\tdouble\tstring\tdouble\tdouble\n"
    "deg\tdeg\tdeg\tmag\t-\tmag\t-\t-\td\t-\tdeg\tdeg\n"
    "----\t----\t----\t----\t----\t----\t----\t----\t----\t----\t----\t----\n"
    "1\tRR Lyr\tRRAB\t7.06\tV\t8.12\tV\t\t0.5668\tA-F\t291.366\t42.785\n"
)


class GetWithRetriesTests(TestCase):
    def test_succeeds_on_first_attempt(self) -> None:
        with patch.object(vsx, "cached_get", return_value=_ok_response(SAMPLE_TSV)) as mock_get:
            result = vsx._get_with_retries({"Name": "RR Lyr"}, timeout_seconds=10)
        self.assertIsNotNone(result)
        self.assertEqual(mock_get.call_count, 1)

    def test_retries_on_transient_5xx_then_succeeds(self) -> None:
        side_effects = [
            _erroring_response(requests.HTTPError("503 Server Error")),
            _ok_response(SAMPLE_TSV),
        ]
        with patch.object(vsx, "cached_get", side_effect=side_effects) as mock_get:
            with patch.object(vsx.time, "sleep"):  # skip the backoff wait
                result = vsx._get_with_retries({"Name": "RR Lyr"}, timeout_seconds=10)
        self.assertIsNotNone(result)
        self.assertEqual(mock_get.call_count, 2)

    def test_retries_on_request_exception(self) -> None:
        side_effects = [
            requests.ConnectionError("DNS lookup failed"),
            requests.Timeout("read timed out"),
            _ok_response(SAMPLE_TSV),
        ]
        with patch.object(vsx, "cached_get", side_effect=side_effects) as mock_get:
            with patch.object(vsx.time, "sleep"):
                result = vsx._get_with_retries({"Name": "X"}, timeout_seconds=10)
        self.assertIsNotNone(result)
        self.assertEqual(mock_get.call_count, 3)

    def test_returns_none_after_exhausting_attempts(self) -> None:
        side_effects = [requests.ConnectionError("down")] * 5
        with patch.object(vsx, "cached_get", side_effect=side_effects) as mock_get:
            with patch.object(vsx.time, "sleep"):
                result = vsx._get_with_retries({"Name": "X"}, timeout_seconds=10, attempts=3)
        self.assertIsNone(result)
        # default 3 attempts
        self.assertEqual(mock_get.call_count, 3)


class FetchVsxTargetByNameTests(TestCase):
    def test_exact_case_match_wins_when_multiple_results(self) -> None:
        # When VizieR returns multiple matches (e.g. partial-name search),
        # an exact case-insensitive match takes priority over the first row.
        multi_tsv = (
            "OID\tName\tType\tmax\tn_max\tmin\tn_min\tl_min\tPeriod\tSp\tRAJ2000\tDEJ2000\n"
            "string\tstring\tstring\tdouble\tstring\tdouble\tstring\tstring\tdouble\tstring\tdouble\tdouble\n"
            "deg\tdeg\tdeg\tmag\t-\tmag\t-\t-\td\t-\tdeg\tdeg\n"
            "----\t----\t----\t----\t----\t----\t----\t----\t----\t----\t----\t----\n"
            "1\tRR LYR-Adjacent\tRRAB\t7.06\tV\t8.12\tV\t\t0.5\tA\t291.366\t42.785\n"
            "2\tRR Lyr\tRRAB\t7.06\tV\t8.12\tV\t\t0.5668\tA-F\t291.366\t42.785\n"
        )
        with patch.object(vsx, "cached_get", return_value=_ok_response(multi_tsv)):
            target = vsx.fetch_vsx_target_by_name("RR Lyr")
        self.assertIsNotNone(target)
        self.assertEqual(target.name, "RR Lyr")

    def test_returns_first_when_no_exact_match(self) -> None:
        # No exact match → fall back to first result (best partial)
        multi_tsv = (
            "OID\tName\tType\tmax\tn_max\tmin\tn_min\tl_min\tPeriod\tSp\tRAJ2000\tDEJ2000\n"
            "string\tstring\tstring\tdouble\tstring\tdouble\tstring\tstring\tdouble\tstring\tdouble\tdouble\n"
            "deg\tdeg\tdeg\tmag\t-\tmag\t-\t-\td\t-\tdeg\tdeg\n"
            "----\t----\t----\t----\t----\t----\t----\t----\t----\t----\t----\t----\n"
            "1\tASASSN-V J123\tEW\t12.0\tV\t13.0\tV\t\t0.3\tA\t100.0\t-5.0\n"
        )
        with patch.object(vsx, "cached_get", return_value=_ok_response(multi_tsv)):
            target = vsx.fetch_vsx_target_by_name("nonexistent target")
        self.assertIsNotNone(target)
        self.assertEqual(target.oid, 1)

    def test_returns_none_on_empty_result(self) -> None:
        empty_tsv = (
            "OID\tName\tType\tmax\tn_max\tmin\tn_min\tl_min\tPeriod\tSp\tRAJ2000\tDEJ2000\n"
            "string\tstring\tstring\tdouble\tstring\tdouble\tstring\tstring\tdouble\tstring\tdouble\tdouble\n"
            "deg\tdeg\tdeg\tmag\t-\tmag\t-\t-\td\t-\tdeg\tdeg\n"
            "----\t----\t----\t----\t----\t----\t----\t----\t----\t----\t----\t----\n"
        )
        with patch.object(vsx, "cached_get", return_value=_ok_response(empty_tsv)):
            target = vsx.fetch_vsx_target_by_name("RR Lyr")
        self.assertIsNone(target)

    def test_returns_none_when_network_dies(self) -> None:
        with patch.object(vsx, "cached_get", side_effect=requests.ConnectionError("down")):
            with patch.object(vsx.time, "sleep"):
                target = vsx.fetch_vsx_target_by_name("RR Lyr")
        self.assertIsNone(target)
