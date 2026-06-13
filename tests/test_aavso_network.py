"""Network error path tests for the AAVSO module.

The most important behavior is the ok-cached fallback: when the live
AAVSO endpoint is unreachable, the module should look for any cached
response file matching the target name and return its data marked
"ok-cached" rather than "unavailable". This protects against
intermittent AAVSO outages during evening sessions.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests

from mira import aavso
from mira.config import (
    AavsoConfig,
    FilterConfig,
    GaiaConfig,
    ObserverConfig,
    OutputConfig,
    ScoringConfig,
    ScoutConfig,
    SimbadConfig,
    SiteConfig,
    VsxQueryConfig,
    WindowConfig,
    ZtfConfig,
)
from mira.models import Candidate, Observability, VsxTarget
from mira.observability import julian_date


def _config(recent_days: int = 90) -> AavsoConfig:
    return AavsoConfig(
        enabled=True, enrich_top=20, recent_days=recent_days,
        sparse_recent_threshold=10, timeout_seconds=30,
        bands=("V", "TG", "Vis."), period_min_peak_power=0.4,
    )


def _sinusoid_xml(period_days: float = 5.0, n: int = 60, span_days: float = 120.0) -> str:
    """Synthetic AAVSO XML: a clean sinusoid on irregular cadence, enough
    observations (>= PERIOD_MIN_OBSERVATIONS) for Lomb-Scargle to lock on."""
    rng = random.Random(7)
    times = sorted(rng.uniform(0.0, span_days) for _ in range(n))
    rows = "\n".join(
        f"{2460000.0 + t:.5f},{12.0 + 0.5 * math.sin(2 * math.pi * t / period_days):.3f},V"
        for t in times
    )
    return (
        '<?xml version="1.0"?><VSXObject><Data><![CDATA[JD,mag,band\n'
        + rows
        + "\n]]></Data></VSXObject>"
    )


def _ok_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.raise_for_status = MagicMock()
    return response


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

    def test_period_analysis_runs_without_catalog_period(self) -> None:
        """Lomb-Scargle must run on period-less VSX targets too — that is the
        only path to the 'period discovered' bonus. (It used to be gated on
        catalog_period is not None, which made the bonus dead code.)"""
        ok = _ok_response(_sinusoid_xml(period_days=5.0))
        with patch.object(aavso, "cached_get", return_value=ok):
            stats = aavso.fetch_recent_observation_count("New Var", _config())
        self.assertEqual(stats.status, "ok")
        self.assertIsNotNone(stats.derived_period_days)
        self.assertIsNotNone(stats.period_power)
        self.assertAlmostEqual(stats.derived_period_days, 5.0, places=1)
        # No catalog period -> agreement is not assessable, with no gating note
        self.assertIsNone(stats.period_disagrees)

    def test_period_analysis_with_catalog_period_still_assessed(self) -> None:
        ok = _ok_response(_sinusoid_xml(period_days=5.0))
        with patch.object(aavso, "cached_get", return_value=ok):
            stats = aavso.fetch_recent_observation_count(
                "RR Lyr", _config(), catalog_period=5.0
            )
        self.assertIsNotNone(stats.derived_period_days)
        self.assertIs(stats.period_disagrees, False)

    def test_too_few_observations_yield_no_derived_period(self) -> None:
        # 3 observations < PERIOD_MIN_OBSERVATIONS: the analysis runs but
        # returns None rather than a junk period.
        ok = _ok_response(VALID_AAVSO_XML)
        with patch.object(aavso, "cached_get", return_value=ok):
            stats = aavso.fetch_recent_observation_count("RR Lyr", _config())
        self.assertIsNone(stats.derived_period_days)


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

    def test_prefix_ident_does_not_match_longer_name(self) -> None:
        """The ident match must be exact, not substring: "ident=ZTF J123"
        used to match a cached "ZTF J1234..." and return the WRONG star's
        observations as ok-cached."""
        import json as _json
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "aavso"
            cache_dir.mkdir()
            # URL encoded the way requests builds it: '+' for spaces,
            # %2B for a literal '+', more params after ident.
            payload = {
                "url": (
                    "https://vsx.aavso.org/index.php?view=api.object"
                    "&ident=ZTF+J1234.5%2B67&data=50000&fromjd=2461113.00000"
                    "&tojd=2461204.00000&csv=&band=V%2CTG%2CVis.&mtype=std"
                ),
                "status_code": 200,
                "headers": {},
                "text": VALID_AAVSO_XML,
            }
            (cache_dir / "abc.json").write_text(_json.dumps(payload), encoding="utf-8")

            with patch.object(aavso, "AAVSO_CACHE_DIR", cache_dir):
                # Prefixes of the cached star's name must NOT match...
                self.assertIsNone(aavso.find_cached_response_for_name("ZTF J123"))
                self.assertIsNone(aavso.find_cached_response_for_name("ZTF J1234.5"))
                # ...while the exact name (literal '+' included) must.
                self.assertEqual(
                    aavso.find_cached_response_for_name("ZTF J1234.5+67"),
                    VALID_AAVSO_XML,
                )


class CacheKeyStabilityTests(TestCase):
    """The fromjd/tojd request params are floored to whole JDs so the URL —
    and therefore the disk-cache key — is stable across runs within the same
    day. Second-resolution JDs gave every run a unique key: the cache never
    hit and data/cache/aavso/ grew without bound."""

    def _fetch_params(self, fixed_now: datetime, recent_days: int = 90) -> dict:
        ok = _ok_response(VALID_AAVSO_XML)
        with patch.object(aavso, "cached_get", return_value=ok) as mock_get:
            with patch.object(aavso, "datetime") as mock_dt:
                mock_dt.now.return_value = fixed_now
                aavso.fetch_recent_observation_count(
                    "RR Lyr", _config(recent_days=recent_days)
                )
        return dict(mock_get.call_args.kwargs["params"])

    def test_jd_window_is_whole_days(self) -> None:
        fixed = datetime(2026, 6, 12, 3, 45, 17, tzinfo=timezone.utc)
        params = self._fetch_params(fixed)
        now_jd = julian_date(fixed)
        self.assertEqual(float(params["fromjd"]), math.floor(now_jd) - 90)
        self.assertEqual(float(params["tojd"]), math.ceil(now_jd))

    def test_cache_key_stable_across_same_day_runs(self) -> None:
        # Two passes hours apart (the documented practice/novelty workflow)
        # must produce byte-identical request params.
        first_pass = datetime(2026, 6, 12, 13, 0, 1, tzinfo=timezone.utc)
        second_pass = datetime(2026, 6, 12, 22, 37, 53, tzinfo=timezone.utc)
        self.assertEqual(
            self._fetch_params(first_pass), self._fetch_params(second_pass)
        )


def _scout_config() -> ScoutConfig:
    site = SiteConfig(
        name="JC",
        observer=ObserverConfig(
            latitude_deg=40.7178, longitude_deg=-74.0431,
            timezone="America/New_York",
        ),
        observing_window=WindowConfig(20, 2, 1, 30, 25, -12.0, 30.0, 0.7),
        filters=FilterConfig(0, 0, 0, 20, 0),
    )
    return ScoutConfig(
        sites=(site,),
        vsx_query=VsxQueryConfig(100, 30, 3, -10, 17, False, ()),
        scoring=ScoringConfig(
            uncertain_type_bonus=0, survey_name_bonus=0, classical_name_bonus=0,
            sparse_aavso_bonus=6, well_observed_aavso_penalty=4,
            high_amplitude_bonus=0, moderate_amplitude_bonus=0,
            bright_target_bonus=0, long_period_bonus=0, time_series_bonus=0,
            clean_field_bonus=0, period_disagreement_bonus=25,
            period_discovered_bonus=18, gaia_color_anomaly_bonus=0,
            gaia_crowding_penalty=0,
        ),
        aavso=_config(),
        simbad=SimbadConfig(False, 0, 0, 0),
        gaia=GaiaConfig(False, 0, 0, 0),
        ztf=ZtfConfig(False, 0, 0, 0, (), 0),
        output=OutputConfig(directory=Path("output"), top_packets=10),
    )


def _candidate(period_days: float | None) -> Candidate:
    target = VsxTarget(
        oid=42, name="New Var", var_type="SR", bright_mag=11.0, faint_mag=12.0,
        bright_band="V", faint_band="V", faint_is_amplitude=False,
        period_days=period_days, spectral_type="", ra_deg=120.0, dec_deg=40.0,
    )
    obs = Observability(
        site_name="JC", max_altitude_deg=70.0, minutes_above_minimum=200,
        best_local_time=None, best_night_date=None, galactic_latitude_deg=30.0,
    )
    return Candidate(
        target=target, observabilities=[obs], score=10.0, reasons=[],
        best_site_name="JC", site_scores={"JC": 10.0}, site_reasons={"JC": []},
    )


class PeriodDiscoveredBonusTests(TestCase):
    """End-to-end pin for the fix: observations + no VSX catalog period ->
    derived_period_days set -> apply_aavso_score awards
    period_discovered_bonus. Before the fix the analysis only ran when a
    catalog period existed, so the discovery bonus could never fire."""

    def test_period_discovered_bonus_awarded_for_periodless_target(self) -> None:
        config = _scout_config()
        candidate = _candidate(period_days=None)
        ok = _ok_response(_sinusoid_xml(period_days=5.0))
        with patch.object(aavso, "cached_get", return_value=ok):
            candidate.aavso = aavso.fetch_recent_observation_count(
                candidate.target.name,
                config.aavso,
                catalog_period=candidate.target.period_days,
            )
        self.assertIsNotNone(candidate.aavso.derived_period_days)
        self.assertGreaterEqual(
            candidate.aavso.period_power, config.aavso.period_min_peak_power
        )

        before = candidate.score
        aavso.apply_aavso_score(candidate, config)
        # 60 recent observations: above the sparse threshold (10), below the
        # well-observed cutoff (100) -> the only score change is the bonus.
        bonus = config.scoring.period_discovered_bonus
        self.assertEqual(candidate.score - before, bonus)
        # apply_target_bonus mirrors to the per-site score (CSV honesty).
        self.assertEqual(candidate.site_scores["JC"] - before, bonus)
        self.assertTrue(
            any("discovered period" in reason for reason in candidate.reasons)
        )
