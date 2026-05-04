from __future__ import annotations

from .config import FilterConfig, ScoutConfig
from .models import Candidate, Observability, VsxTarget
from .vsx import type_matches

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


def build_candidates(targets: list[VsxTarget], config: ScoutConfig, start_date=None) -> list[Candidate]:
    from .observability import evaluate_observability

    candidates: list[Candidate] = []
    for target in targets:
        if not type_matches(target.var_type, config.vsx_query.include_types):
            continue
        if not passes_static_filters(target, config.filters):
            continue

        observability = evaluate_observability(target, config.observer, config.observing_window, start_date=start_date)
        if observability.max_altitude_deg < config.observing_window.min_altitude_deg:
            continue
        if observability.minutes_above_minimum <= 0:
            continue
        if abs(observability.galactic_latitude_deg) < config.filters.min_galactic_latitude_abs_deg:
            continue

        score, reasons = score_candidate(target, observability, config)
        candidates.append(Candidate(target=target, observability=observability, score=score, reasons=reasons))

    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates


def passes_static_filters(target: VsxTarget, filters: FilterConfig) -> bool:
    if target.bright_mag is None:
        return False
    if target.bright_mag < filters.reject_saturated_brighter_than_mag:
        return False
    amplitude = target.catalog_amplitude
    if amplitude is not None and amplitude < filters.min_catalog_amplitude_mag:
        return False
    return True


def score_candidate(
    target: VsxTarget,
    observability: Observability,
    config: ScoutConfig,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    altitude_score = min(25.0, max(0.0, observability.max_altitude_deg - config.observing_window.min_altitude_deg))
    score += altitude_score
    reasons.append(f"max altitude {observability.max_altitude_deg:.1f} deg")

    if observability.minutes_above_minimum >= 180:
        score += 12
        reasons.append("long nightly window")
    elif observability.minutes_above_minimum >= 90:
        score += 6
        reasons.append("usable nightly window")

    if is_uncertain_type(target.var_type):
        score += config.scoring.uncertain_type_bonus
        reasons.append(f"uncertain or broad VSX type ({target.var_type or 'blank'})")

    if is_survey_name(target.name):
        score += config.scoring.survey_name_bonus
        reasons.append("survey-designated object, good data-mining follow-up candidate")

    amplitude = target.catalog_amplitude
    if amplitude is not None:
        if amplitude >= config.filters.prefer_amplitude_mag:
            score += config.scoring.high_amplitude_bonus
            reasons.append(f"catalog amplitude about {amplitude:.2f} mag")
        elif amplitude >= config.filters.min_catalog_amplitude_mag:
            score += config.scoring.moderate_amplitude_bonus
            reasons.append(f"modest catalog amplitude about {amplitude:.2f} mag")

    if target.bright_mag is not None and target.bright_mag <= config.filters.prefer_max_mag:
        score += config.scoring.bright_target_bonus
        reasons.append(f"bright enough for urban photometry ({target.bright_mag:.2f})")

    if target.period_days is None:
        score += 4
        reasons.append("no catalog period listed")
    elif target.period_days >= 10:
        score += config.scoring.long_period_bonus
        reasons.append(f"long-period cadence friendly ({target.period_days:.2f} d)")
    elif 0.08 <= target.period_days <= 2:
        score += config.scoring.time_series_bonus
        reasons.append(f"time-series candidate ({target.period_days:.4f} d)")

    if abs(observability.galactic_latitude_deg) >= config.filters.min_galactic_latitude_abs_deg * 2:
        score += config.scoring.clean_field_bonus
        reasons.append(f"well away from Galactic plane (b={observability.galactic_latitude_deg:.1f} deg)")

    return score, reasons


def is_uncertain_type(var_type: str) -> bool:
    normalized = var_type.upper().strip()
    if not normalized:
        return True
    uncertainty_tokens = ("?", "|", ":", "VAR", "MISC", "L", "LB", "SRS", "SR")
    return any(token in normalized for token in uncertainty_tokens)


def is_survey_name(name: str) -> bool:
    normalized = name.upper().strip()
    return any(normalized.startswith(prefix) for prefix in SURVEY_NAME_PREFIXES)
