from __future__ import annotations

import re

from .config import FilterConfig, ScoutConfig, SiteConfig
from .models import Candidate, Observability, VsxTarget
from .vsx import tokenize_var_type, type_matches

SURVEY_NAME_PREFIXES = (
    "GAIA",
    "ASASSN",
    "ASAS-SN",
    "ZTF",
    "WISE",
    "NSVS",
    "CSS",
    "CRTS",
)

GCVS_NAME_RE = re.compile(r"^(?:[A-Z]{1,2}|V\d{1,4})\s+[A-Z]{3}$")


def build_candidates(targets: list[VsxTarget], config: ScoutConfig, start_date=None) -> list[Candidate]:
    from .observability import evaluate_observability

    candidates: list[Candidate] = []
    for target in targets:
        if not type_matches(target.var_type, config.vsx_query.include_types):
            continue

        viable: list[tuple[SiteConfig, Observability, float, list[str]]] = []
        for site in config.sites:
            if not passes_static_filters(target, site.filters):
                continue
            observability = evaluate_observability(target, site, start_date=start_date)
            if observability.max_altitude_deg < site.observing_window.min_altitude_deg:
                continue
            if observability.minutes_above_minimum <= 0:
                continue
            if abs(observability.galactic_latitude_deg) < site.filters.min_galactic_latitude_abs_deg:
                continue
            site_score, site_reasons = score_candidate(target, site, observability, config)
            viable.append((site, observability, site_score, site_reasons))

        if not viable:
            continue

        # observabilities ordered by minutes/altitude (the geometric ranking)
        observabilities = sorted(
            (item[1] for item in viable),
            key=lambda obs: (obs.minutes_above_minimum, obs.max_altitude_deg),
            reverse=True,
        )

        site_scores = {item[0].name: item[2] for item in viable}
        site_reasons = {item[0].name: list(item[3]) for item in viable}

        # The "best" site for the global score is the one with the highest score,
        # not necessarily the one with the most observable minutes.
        best_index = max(range(len(viable)), key=lambda i: viable[i][2])
        best_site = viable[best_index][0]
        best_site_name = best_site.name
        global_score = viable[best_index][2]
        global_reasons = list(viable[best_index][3])

        all_site_names = [item[0].name for item in viable]
        if len(all_site_names) > 1:
            for site_name, reasons in site_reasons.items():
                others = [name for name in all_site_names if name != site_name]
                if others:
                    reasons.append(f"also observable from {', '.join(others)}")
            others_for_global = [name for name in all_site_names if name != best_site.name]
            if others_for_global:
                global_reasons.append(f"also observable from {', '.join(others_for_global)}")

        candidates.append(
            Candidate(
                target=target,
                observabilities=observabilities,
                score=global_score,
                reasons=global_reasons,
                best_site_name=best_site_name,
                site_scores=site_scores,
                site_reasons=site_reasons,
            )
        )

    candidates.sort(key=candidate_sort_key)
    return candidates


def build_single_candidate(
    target: VsxTarget,
    config: ScoutConfig,
    start_date=None,
) -> Candidate:
    """Build a Candidate without filtering. Used by `target` subcommand."""
    from .observability import evaluate_observability

    site_observabilities: list[tuple[SiteConfig, Observability]] = []
    for site in config.sites:
        obs = evaluate_observability(target, site, start_date=start_date)
        site_observabilities.append((site, obs))

    site_scores: dict[str, float] = {}
    site_reasons: dict[str, list[str]] = {}
    viable_names: list[str] = []
    for site, obs in site_observabilities:
        if obs.minutes_above_minimum > 0 and obs.max_altitude_deg > -90.0:
            score, reasons = score_candidate(target, site, obs, config)
            site_scores[site.name] = score
            site_reasons[site.name] = list(reasons)
            viable_names.append(site.name)

    observabilities = sorted(
        (obs for _, obs in site_observabilities),
        key=lambda obs: (obs.minutes_above_minimum, obs.max_altitude_deg),
        reverse=True,
    )

    best_site_name = ""
    if viable_names:
        if len(viable_names) > 1:
            for site_name, reasons in site_reasons.items():
                others = [n for n in viable_names if n != site_name]
                if others:
                    reasons.append(f"also observable from {', '.join(others)}")
        best_site_name = max(site_scores, key=site_scores.get)
        global_score = site_scores[best_site_name]
        global_reasons = list(site_reasons[best_site_name])
    else:
        global_score = 0.0
        global_reasons = ["target is not observable from any configured site under current darkness/altitude rules"]

    return Candidate(
        target=target,
        observabilities=observabilities,
        score=global_score,
        reasons=global_reasons,
        best_site_name=best_site_name,
        site_scores=site_scores,
        site_reasons=site_reasons,
    )


def candidate_sort_key(candidate: Candidate) -> tuple:
    aavso = candidate.aavso
    aavso_known = aavso is not None and aavso.status == "ok"
    aavso_recent = aavso.recent_observations if aavso_known else 10**9
    obs = candidate.best_observability
    amplitude = candidate.target.catalog_amplitude
    return (
        -candidate.score,
        not aavso_known,
        aavso_recent,
        -obs.minutes_above_minimum,
        -obs.max_altitude_deg,
        amplitude is None,
        -(amplitude or 0.0),
    )


FAINT_TOLERANCE_MAG = 1.0


def passes_static_filters(target: VsxTarget, filters: FilterConfig) -> bool:
    if target.bright_mag is None:
        return False
    if target.bright_mag < filters.reject_saturated_brighter_than_mag:
        return False
    if target.bright_mag > filters.prefer_max_mag + FAINT_TOLERANCE_MAG:
        return False
    amplitude = target.catalog_amplitude
    if amplitude is not None and amplitude < filters.min_catalog_amplitude_mag:
        return False
    return True


def score_candidate(
    target: VsxTarget,
    site: SiteConfig,
    observability: Observability,
    config: ScoutConfig,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    filters = site.filters
    window = site.observing_window

    altitude_score = min(25.0, max(0.0, observability.max_altitude_deg - window.min_altitude_deg))
    score += altitude_score
    reasons.append(
        f"max altitude {observability.max_altitude_deg:.1f} deg from {site.name}"
    )

    if observability.minutes_above_minimum >= 180:
        score += 12
        reasons.append(f"long nightly window from {site.name}")
    elif observability.minutes_above_minimum >= 90:
        score += 6
        reasons.append(f"usable nightly window from {site.name}")

    if is_uncertain_type(target.var_type):
        score += config.scoring.uncertain_type_bonus
        reasons.append(f"uncertain or broad VSX type ({target.var_type or 'blank'})")

    if is_survey_name(target.name):
        score += config.scoring.survey_name_bonus
        reasons.append("survey-designated object, good data-mining follow-up candidate")
    elif is_classical_gcvs_name(target.name):
        score += config.scoring.classical_name_bonus
        reasons.append("classical GCVS variable, suitable for practice and follow-up")

    amplitude = target.catalog_amplitude
    if amplitude is not None:
        if amplitude >= filters.prefer_amplitude_mag:
            score += config.scoring.high_amplitude_bonus
            reasons.append(f"catalog amplitude about {amplitude:.2f} mag")
        elif amplitude >= filters.min_catalog_amplitude_mag:
            score += config.scoring.moderate_amplitude_bonus
            reasons.append(f"modest catalog amplitude about {amplitude:.2f} mag")

    if target.bright_mag is not None and target.bright_mag <= filters.prefer_max_mag:
        score += config.scoring.bright_target_bonus
        reasons.append(
            f"bright enough for {site.name} ({target.bright_mag:.2f})"
        )

    if target.period_days is None:
        score += 4
        reasons.append("no catalog period listed")
    elif target.period_days >= 10:
        score += config.scoring.long_period_bonus
        reasons.append(f"long-period cadence friendly ({target.period_days:.2f} d)")
    elif 0.08 <= target.period_days <= 2:
        score += config.scoring.time_series_bonus
        reasons.append(f"time-series candidate ({target.period_days:.4f} d)")

    if abs(observability.galactic_latitude_deg) >= filters.min_galactic_latitude_abs_deg * 2:
        score += config.scoring.clean_field_bonus
        reasons.append(
            f"well away from Galactic plane (b={observability.galactic_latitude_deg:.1f} deg)"
        )

    return score, reasons


def is_uncertain_type(var_type: str) -> bool:
    normalized = (var_type or "").upper().strip()
    if not normalized:
        return True
    if any(modifier in normalized for modifier in "?:|"):
        return True
    tokens = tokenize_var_type(normalized)
    return any(token in {"VAR", "MISC"} for token in tokens)


def is_survey_name(name: str) -> bool:
    normalized = name.upper().strip()
    return any(normalized.startswith(prefix) for prefix in SURVEY_NAME_PREFIXES)


def is_classical_gcvs_name(name: str) -> bool:
    return bool(GCVS_NAME_RE.match(name.strip().upper()))


def apply_target_bonus(candidate: Candidate, bonus: float, reason: str) -> None:
    """Apply a target-level (site-independent) score change. Updates the global
    score+reasons AND every per-site score+reasons so the per-site CSVs remain
    honest after AAVSO/Gaia/ZTF enrichment."""
    candidate.score += bonus
    candidate.reasons.append(reason)
    for site_name in candidate.site_scores:
        candidate.site_scores[site_name] += bonus
        candidate.site_reasons[site_name].append(reason)


def apply_target_reason(candidate: Candidate, reason: str) -> None:
    """Append a reason without changing scores. Mirrors to per-site reasons."""
    candidate.reasons.append(reason)
    for site_name in candidate.site_reasons:
        candidate.site_reasons[site_name].append(reason)


def apply_ztf_score(candidate: Candidate, config: ScoutConfig) -> None:
    ztf = candidate.ztf
    if ztf is None or ztf.status != "ok":
        return
    if ztf.period_disagrees is True:
        catalog = candidate.target.period_days
        catalog_text = f"{catalog:.3f}" if catalog is not None else "n/a"
        apply_target_bonus(
            candidate,
            config.scoring.period_disagreement_bonus,
            f"ZTF period {ztf.derived_period_days:.4f} d disagrees with catalog {catalog_text} d",
        )
    elif ztf.period_disagrees is False:
        apply_target_reason(
            candidate,
            f"ZTF period {ztf.derived_period_days:.4f} d agrees with catalog within tolerance",
        )
    elif (
        candidate.target.period_days is None
        and ztf.derived_period_days is not None
        and ztf.period_power is not None
        and ztf.period_power >= config.ztf.period_min_peak_power
    ):
        apply_target_bonus(
            candidate,
            config.scoring.period_discovered_bonus,
            f"ZTF discovered period {ztf.derived_period_days:.4f} d "
            f"(peak power {ztf.period_power:.3f}); VSX has no catalog period",
        )
