"""Tests for the scoring heart: filter-pass rules, per-site/global score
mirroring, candidate sort key, and ZTF bonus application."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase

from anomaly_scout.config import FilterConfig, load_config
from anomaly_scout.models import (
    AavsoStats,
    Candidate,
    Observability,
    VsxTarget,
    ZtfStats,
)
from anomaly_scout.scoring import (
    apply_target_bonus,
    apply_target_reason,
    apply_ztf_score,
    candidate_sort_key,
    is_classical_gcvs_name,
    is_survey_name,
    is_uncertain_type,
    passes_static_filters,
    score_candidate,
)

CONFIG = load_config(Path(__file__).resolve().parent.parent / "config" / "s30_pro_jc.yaml")
SITE = CONFIG.sites[0]


def _filters(
    prefer_max_mag: float = 14.0,
    prefer_amplitude: float = 0.5,
    min_amplitude: float = 0.2,
    min_galactic_lat: float = 12.0,
    reject_brighter_than: float = 4.0,
) -> FilterConfig:
    return FilterConfig(
        min_galactic_latitude_abs_deg=min_galactic_lat,
        min_catalog_amplitude_mag=min_amplitude,
        prefer_amplitude_mag=prefer_amplitude,
        prefer_max_mag=prefer_max_mag,
        reject_saturated_brighter_than_mag=reject_brighter_than,
    )


def _target(
    name: str = "RR LYR",
    var_type: str = "RRAB",
    max_mag: float | None = 7.06,
    min_mag: float | None = 8.12,
    period: float | None = 0.5668,
    min_is_amplitude: bool = False,
) -> VsxTarget:
    return VsxTarget(
        oid=1, name=name, var_type=var_type,
        max_mag=max_mag, min_mag=min_mag,
        max_band="V", min_band="V", min_is_amplitude=min_is_amplitude,
        period_days=period, spectral_type="A",
        ra_deg=291.366, dec_deg=42.785,
    )


def _observability(
    site_name: str = "Jersey City",
    max_alt: float = 70.0,
    minutes: int = 200,
    galactic_lat: float = 25.0,
) -> Observability:
    return Observability(
        site_name=site_name,
        max_altitude_deg=max_alt,
        minutes_above_minimum=minutes,
        best_local_time=datetime(2026, 5, 6, 22, 0, tzinfo=timezone.utc),
        best_night_date=None,
        galactic_latitude_deg=galactic_lat,
    )


class StaticFilterTests(TestCase):
    def test_rejects_too_faint(self) -> None:
        # prefer_max_mag=14 + tolerance 1.0 = 15 floor; 15.5 fails
        self.assertFalse(passes_static_filters(_target(max_mag=15.5), _filters()))

    def test_rejects_saturated(self) -> None:
        self.assertFalse(passes_static_filters(_target(max_mag=2.0), _filters()))

    def test_accepts_in_range(self) -> None:
        self.assertTrue(passes_static_filters(_target(max_mag=10.0), _filters()))

    def test_rejects_low_amplitude(self) -> None:
        target = _target(max_mag=10.0, min_mag=10.05)  # amp=0.05
        self.assertFalse(passes_static_filters(target, _filters(min_amplitude=0.2)))

    def test_passes_within_faint_tolerance(self) -> None:
        # 14.5 is above prefer_max_mag=14 but within +1.0 tolerance
        self.assertTrue(passes_static_filters(_target(max_mag=14.5), _filters()))

    def test_no_amplitude_information_passes(self) -> None:
        target = _target(max_mag=10.0, min_mag=None)
        self.assertTrue(passes_static_filters(target, _filters()))


class TypeMatchingTests(TestCase):
    def test_uncertain_type_recognizes_modifiers(self) -> None:
        self.assertTrue(is_uncertain_type("EW?"))
        self.assertTrue(is_uncertain_type("M:"))
        self.assertTrue(is_uncertain_type("EW|EA"))
        self.assertTrue(is_uncertain_type(""))
        self.assertTrue(is_uncertain_type("VAR"))
        self.assertTrue(is_uncertain_type("MISC"))

    def test_uncertain_type_rejects_well_defined(self) -> None:
        self.assertFalse(is_uncertain_type("RRAB"))
        self.assertFalse(is_uncertain_type("EW"))
        self.assertFalse(is_uncertain_type("SRA"))
        self.assertFalse(is_uncertain_type("LB"))

    def test_survey_name_detection(self) -> None:
        self.assertTrue(is_survey_name("Gaia DR3 12345"))
        self.assertTrue(is_survey_name("ASASSN-V J123456"))
        self.assertTrue(is_survey_name("ZTF18abc"))
        self.assertFalse(is_survey_name("RR Lyr"))
        self.assertFalse(is_survey_name("V0001 Cyg"))

    def test_gcvs_classical_name_detection(self) -> None:
        self.assertTrue(is_classical_gcvs_name("RR Lyr"))
        self.assertTrue(is_classical_gcvs_name("AB Aur"))
        self.assertTrue(is_classical_gcvs_name("V0001 Cyg"))
        self.assertFalse(is_classical_gcvs_name("Gaia DR3 12345"))
        self.assertFalse(is_classical_gcvs_name(""))


class ScoreCandidateTests(TestCase):
    def test_long_window_bonus_kicks_in(self) -> None:
        long_obs = _observability(minutes=200)
        short_obs = _observability(minutes=60)
        long_score, _ = score_candidate(_target(), SITE, long_obs, CONFIG)
        short_score, _ = score_candidate(_target(), SITE, short_obs, CONFIG)
        self.assertGreater(long_score, short_score)

    def test_uncertain_type_adds_bonus(self) -> None:
        obs = _observability()
        certain_score, _ = score_candidate(_target(var_type="RRAB"), SITE, obs, CONFIG)
        uncertain_score, _ = score_candidate(_target(var_type="EW?"), SITE, obs, CONFIG)
        self.assertEqual(uncertain_score - certain_score, CONFIG.scoring.uncertain_type_bonus)

    def test_clean_field_bonus_at_high_galactic_lat(self) -> None:
        plane_obs = _observability(galactic_lat=15.0)
        high_obs = _observability(galactic_lat=60.0)
        plane_score, _ = score_candidate(_target(), SITE, plane_obs, CONFIG)
        high_score, _ = score_candidate(_target(), SITE, high_obs, CONFIG)
        self.assertEqual(high_score - plane_score, CONFIG.scoring.clean_field_bonus)

    def test_reasons_are_populated(self) -> None:
        _score, reasons = score_candidate(_target(), SITE, _observability(), CONFIG)
        self.assertGreaterEqual(len(reasons), 3)
        # Altitude reason always present
        self.assertTrue(any("altitude" in r for r in reasons))


class ApplyTargetBonusTests(TestCase):
    def _candidate(self) -> Candidate:
        return Candidate(
            target=_target(),
            observabilities=(_observability(),),
            score=50.0,
            reasons=["initial"],
            best_site_name="Jersey City",
            site_scores={"Jersey City": 50.0, "Fairbanks": 60.0},
            site_reasons={"Jersey City": ["initial"], "Fairbanks": ["initial"]},
        )

    def test_apply_bonus_mirrors_to_all_sites(self) -> None:
        candidate = self._candidate()
        apply_target_bonus(candidate, 8.0, "AAVSO sparse")
        self.assertEqual(candidate.score, 58.0)
        self.assertEqual(candidate.site_scores["Jersey City"], 58.0)
        self.assertEqual(candidate.site_scores["Fairbanks"], 68.0)
        self.assertIn("AAVSO sparse", candidate.reasons)
        self.assertIn("AAVSO sparse", candidate.site_reasons["Jersey City"])
        self.assertIn("AAVSO sparse", candidate.site_reasons["Fairbanks"])

    def test_apply_reason_does_not_change_scores(self) -> None:
        candidate = self._candidate()
        apply_target_reason(candidate, "AAVSO matches catalog period")
        self.assertEqual(candidate.score, 50.0)
        self.assertEqual(candidate.site_scores["Jersey City"], 50.0)
        self.assertIn("AAVSO matches catalog period", candidate.site_reasons["Jersey City"])


class CandidateSortKeyTests(TestCase):
    def _make(self, score: float, aavso_recent: int | None) -> Candidate:
        aavso = None if aavso_recent is None else AavsoStats(
            status="ok", recent_observations=aavso_recent,
        )
        return Candidate(
            target=_target(),
            observabilities=(_observability(),),
            score=score,
            reasons=[],
            best_site_name="Jersey City",
            site_scores={"Jersey City": score},
            site_reasons={"Jersey City": []},
            aavso=aavso,
        )

    def test_higher_score_sorts_first(self) -> None:
        a = self._make(70.0, aavso_recent=2)
        b = self._make(50.0, aavso_recent=2)
        self.assertLess(candidate_sort_key(a), candidate_sort_key(b))

    def test_tie_break_by_aavso_sparseness(self) -> None:
        sparse = self._make(60.0, aavso_recent=1)
        dense = self._make(60.0, aavso_recent=20)
        self.assertLess(candidate_sort_key(sparse), candidate_sort_key(dense))

    def test_unknown_aavso_sorts_after_known(self) -> None:
        known = self._make(60.0, aavso_recent=20)
        unknown = self._make(60.0, aavso_recent=None)
        self.assertLess(candidate_sort_key(known), candidate_sort_key(unknown))


class ApplyZtfScoreTests(TestCase):
    def _candidate(self, period: float | None) -> Candidate:
        return Candidate(
            target=_target(period=period),
            observabilities=(_observability(),),
            score=50.0,
            reasons=[],
            best_site_name="Jersey City",
            site_scores={"Jersey City": 50.0},
            site_reasons={"Jersey City": []},
        )

    def test_period_disagreement_bonus(self) -> None:
        candidate = self._candidate(period=0.5668)
        candidate.ztf = ZtfStats(
            status="ok", observations=100,
            derived_period_days=1.1336, period_power=0.7, period_disagrees=True,
        )
        before = candidate.score
        apply_ztf_score(candidate, CONFIG)
        self.assertEqual(candidate.score - before, CONFIG.scoring.period_disagreement_bonus)

    def test_period_discovery_bonus_when_no_catalog(self) -> None:
        candidate = self._candidate(period=None)
        candidate.ztf = ZtfStats(
            status="ok", observations=100,
            derived_period_days=2.5, period_power=0.6, period_disagrees=None,
        )
        before = candidate.score
        apply_ztf_score(candidate, CONFIG)
        self.assertEqual(candidate.score - before, CONFIG.scoring.period_discovered_bonus)

    def test_no_bonus_when_status_not_ok(self) -> None:
        candidate = self._candidate(period=None)
        candidate.ztf = ZtfStats(status="parsed-no-magnitudes", observations=0)
        before = candidate.score
        apply_ztf_score(candidate, CONFIG)
        self.assertEqual(candidate.score, before)
