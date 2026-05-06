"""Network error path tests for the AAVSO module.

The most important behavior is the ok-cached fallback: when the live
AAVSO endpoint is unreachable, the module should look for any cached
response file matching the target name and return its data marked
"ok-cached" rather than "unavailable". This protects against
intermittent AAVSO outages during evening sessions.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests

from anomaly_scout import aavso
from anomaly_scout.config import AavsoConfig


def _config(recent_days: int = 90) -> AavsoConfig:
    return AavsoConfig(
        enabled=True, enrich_top=20, recent_days=recent_days,
        sparse_recent_threshold=10, timeout_seconds=30,
        bands=("V", "TG", "Vis."), period_min_peak_power=0.4,
    )


VALID_AAVSO_XML = (
    '<?xml version="1.0"?>'
    '<VSXObject><Data><![CDATA[JD,mag,band\n'
    '2461165.5,7.6,V\n'
    '2461166.0,7.65,V\n'
    '2461167.0,7.7,Vis.\n'
    ']]></Data></VSXObject>'
)


class FetchRecentObservationCountTests(TestCase):
    def test_live_success_returns_ok(self) -> None:
        ok = MagicMock()
        ok.text = VALID_AAVSO_XML
        ok.raise_for_status = MagicMock()
        with patch.object(aavso, "cached_get", return_value=ok):
            stats = aavso.fetch_recent_observation_count("RR Lyr", _config())
        self.assertEqual(stats.status, "ok")
        self.assertEqual(stats.recent_observations, 3)

    def test_falls_back_to_cached_when_live_fails(self) -> None:
        # Live request throws, but find_cached_response_for_name returns text
        with patch.object(aavso, "cached_get", side_effect=requests.ConnectionError("down")):
            with patch.object(aavso, "find_cached_response_for_name",
                              return_value=VALID_AAVSO_XML):
                stats = aavso.fetch_recent_observation_count("RR Lyr", _config())
        self.assertEqual(stats.status, "ok-cached")
        self.assertEqual(stats.recent_observations, 3)
        self.assertIn("cached AAVSO response", stats.note)

    def test_returns_unavailable_when_no_cache_either(self) -> None:
        with patch.object(aavso, "cached_get", side_effect=requests.ConnectionError("down")):
            with patch.object(aavso, "find_cached_response_for_name", return_value=None):
                stats = aavso.fetch_recent_observation_count("RR Lyr", _config())
        self.assertEqual(stats.status, "unavailable")
        self.assertIn("down", stats.note)

    def test_period_analysis_only_runs_with_catalog_period(self) -> None:
        ok = MagicMock()
        ok.text = VALID_AAVSO_XML
        ok.raise_for_status = MagicMock()
        with patch.object(aavso, "cached_get", return_value=ok):
            stats_no_period = aavso.fetch_recent_observation_count("RR Lyr", _config())
            stats_with_period = aavso.fetch_recent_observation_count(
                "RR Lyr", _config(), catalog_period=0.5668
            )
        # Without catalog period, no Lomb-Scargle output
        self.assertIsNone(stats_no_period.derived_period_days)
        # With catalog period, derived period should be populated (or have a
        # gating note) — both paths are valid
        self.assertTrue(
            stats_with_period.derived_period_days is not None
            or stats_with_period.period_note
        )


class CachedResponseLookupTests(TestCase):
    """find_cached_response_for_name walks the AAVSO cache dir looking for
    any payload that mentions the target's identifier. Tests the fallback
    pathway used when the live endpoint is down."""

    def test_returns_none_when_cache_dir_missing(self) -> None:
        with patch.object(aavso, "AAVSO_CACHE_DIR", Path("nonexistent-cache")):
            self.assertIsNone(aavso.find_cached_response_for_name("RR Lyr"))

    def test_returns_text_when_cache_has_matching_payload(self) -> None:
        import json as _json
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "aavso"
            cache_dir.mkdir()
            payload = {
                "url": "https://vsx.aavso.org/index.php?ident=RR+Lyr",
                "status_code": 200,
                "headers": {},
                "text": VALID_AAVSO_XML,
            }
            (cache_dir / "abc123.json").write_text(_json.dumps(payload), encoding="utf-8")

            with patch.object(aavso, "AAVSO_CACHE_DIR", cache_dir):
                result = aavso.find_cached_response_for_name("RR Lyr")
        self.assertEqual(result, VALID_AAVSO_XML)

    def test_returns_none_when_no_matching_cache_entry(self) -> None:
        import json as _json
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "aavso"
            cache_dir.mkdir()
            # Cache holds a response for a *different* target
            payload = {
                "url": "https://vsx.aavso.org/index.php?ident=Some+Other",
                "status_code": 200,
                "headers": {},
                "text": "<VSXObject></VSXObject>",
            }
            (cache_dir / "abc.json").write_text(_json.dumps(payload), encoding="utf-8")

            with patch.object(aavso, "AAVSO_CACHE_DIR", cache_dir):
                result = aavso.find_cached_response_for_name("RR Lyr")
        self.assertIsNone(result)
