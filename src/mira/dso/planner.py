"""DSO planner — observability-aware ranking of catalog targets.

Reuses ``evaluate_observability_at_coords`` for the alt/sun/moon/horizon
math so the VSX and DSO sides give consistent answers. The DSO-specific
bits are:

- Moon-relax for narrowband: Ha/SII punch through moonlight; OIII less so
  but still acceptable. Default behavior is to disable the moon filter
  for any target with narrowband budget. Set the planner's ``relax_moon``
  argument to False to apply the VSX-style moon gate.
- FOV-fit flag: compares ``target.size_arcmin`` against the configured rig
  FOV. Oversized targets are kept in the ranking but down-weighted and
  flagged as mosaic candidates.
- No remote enrichment: the catalog is the source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from ..config import ScoutConfig, SiteConfig
from ..models import Observability
from ..observability import evaluate_observability_at_coords
from .catalog import DsoCatalog, DsoTarget
from .ledger import Ledger, target_completion_fraction


# Default FOV of the Esprit 120 EDX + ASI2600MM Pro: 840mm fl on a 23.5×15.7mm
# sensor gives ~1.6° × 1.07°. Other rigs override via DsoConfig.fov_deg or the
# planner's fov_deg kwarg.
DEFAULT_FOV_DEG = (1.6, 1.07)


@dataclass(frozen=True)
class DsoCandidate:
    """One ranked DSO planning result.

    ``observabilities`` is one Observability per configured site (same
    ordering as ``config.sites``). ``best_observability`` is the one used
    for ranking — the site with the most dark-time above the local floor
    (with max altitude as the tiebreaker).

    Ledger-derived fields (all zero when ledger=None on
    build_dso_candidates, so downstream display code can render them
    harmlessly in both modes): ``captured_minutes`` is total integration
    time already booked, capped per-filter at that filter's budget so
    over-imaging Ha doesn't mask that OIII/SII are still empty;
    ``budget_minutes`` is the sum of the target's per-filter budgets;
    ``completion_fraction`` is captured/budget (may exceed 1 for
    cap-aware purposes but the planner clamps it to 1 internally)."""
    target: DsoTarget
    observabilities: tuple[Observability, ...]
    best_observability: Observability
    fits_fov: bool
    fov_deg: tuple[float, float]
    score: float
    reasons: tuple[str, ...]
    captured_minutes: float = 0.0
    budget_minutes: float = 0.0
    completion_fraction: float = 0.0

    @property
    def best_site_name(self) -> str:
        return self.best_observability.site_name

    @property
    def deficit_minutes(self) -> float:
        return max(0.0, self.budget_minutes - self.captured_minutes)


def build_dso_candidates(
    catalog: DsoCatalog,
    config: ScoutConfig,
    *,
    start_date: date | None = None,
    fov_deg: tuple[float, float] = DEFAULT_FOV_DEG,
    relax_moon: bool = True,
    ledger: Ledger | None = None,
    deficit_weight: float = 1.0,
) -> list[DsoCandidate]:
    """Rank catalog targets by observability + FOV fit + (optionally)
    integration deficit.

    Filters out targets with zero observable minutes at every site. Mosaic
    candidates (size > FOV in either axis) are kept but down-weighted by
    20% so single-frame targets float to the top.

    ``relax_moon=True`` (default) replaces the moon-altitude / moon-illum /
    moon-separation filters with permissive values for any target whose
    ``budget_minutes`` includes a narrowband filter. Broadband-only targets
    (REF/galaxies with L+RGB only) still apply the VSX-style moon gate.

    ``ledger`` (Phase 2): when provided, every candidate's observability
    score is multiplied by ``0.5 + deficit_weight * deficit_fraction``
    (clamped to [0.5, 1.5]). A never-imaged target gets the full 1.5×
    boost; a 100%-complete target gets the 0.5× demotion (visible but
    deprioritized — per the rule that completed targets stay in the
    queue). Pass ``ledger=None`` (or ``deficit_weight=0``) for the
    Phase-1 pure-observability ranking — pinned by test."""
    candidates: list[DsoCandidate] = []
    for target in catalog.targets:
        relax_for_target = relax_moon and target.is_narrowband
        observabilities: list[Observability] = []
        for site in config.sites:
            effective_site = _maybe_relax_moon(site) if relax_for_target else site
            obs = evaluate_observability_at_coords(
                target.ra_deg, target.dec_deg, effective_site,
                start_date=start_date,
            )
            observabilities.append(obs)
        viable = [o for o in observabilities if o.minutes_above_minimum > 0]
        if not viable:
            continue
        best = max(
            viable,
            key=lambda o: (o.minutes_above_minimum, o.max_altitude_deg),
        )
        major_deg = target.size_arcmin[0] / 60.0
        minor_deg = target.size_arcmin[1] / 60.0
        fits_fov = (
            not target.mosaic
            and major_deg <= fov_deg[0]
            and minor_deg <= fov_deg[1]
        )

        # Ledger-derived display fields. The captured_minutes calc caps
        # each filter at its budget so over-imaging Ha doesn't mask that
        # OIII/SII are still empty — same cap used by
        # target_completion_fraction so display and score stay coherent.
        if ledger is not None:
            completion = target_completion_fraction(ledger, target)
            captured = sum(
                min(float(b), ledger.minutes(target.name, f))
                for f, b in target.budget_minutes.items()
            )
        else:
            completion = 0.0
            captured = 0.0
        budget = float(target.total_budget_minutes)

        observability_score = _score_candidate(best, fits_fov)
        score = _apply_deficit_weight(
            observability_score, completion, deficit_weight,
            ledger_active=ledger is not None,
        )
        reasons = _build_reasons(
            target, best, fits_fov, fov_deg, relax_for_target,
            ledger=ledger, completion_fraction=completion,
            captured_minutes=captured, budget_minutes=budget,
        )
        candidates.append(DsoCandidate(
            target=target,
            observabilities=tuple(observabilities),
            best_observability=best,
            fits_fov=fits_fov,
            fov_deg=fov_deg,
            score=score,
            reasons=reasons,
            captured_minutes=captured,
            budget_minutes=budget,
            completion_fraction=completion,
        ))
    candidates.sort(
        key=lambda c: (
            -c.score,
            -c.best_observability.minutes_above_minimum,
            -c.best_observability.max_altitude_deg,
            c.target.name,
        )
    )
    return candidates


def _apply_deficit_weight(
    base_score: float,
    completion_fraction: float,
    deficit_weight: float,
    *,
    ledger_active: bool,
) -> float:
    """Multiply the observability score by a deficit-aware factor.

    Factor = 0.5 + deficit_weight * deficit_fraction, clamped to [0.5, 1.5].
    deficit_fraction = max(0, 1 - completion_fraction). When the ledger
    is inactive OR deficit_weight is 0, the factor is exactly 1.0 —
    Phase-1 behavior preserved bit-for-bit."""
    if not ledger_active or deficit_weight <= 0:
        return base_score
    deficit_fraction = max(0.0, 1.0 - completion_fraction)
    factor = 0.5 + deficit_weight * deficit_fraction
    factor = max(0.5, min(1.5, factor))
    return base_score * factor


def _maybe_relax_moon(site: SiteConfig) -> SiteConfig:
    """Return a SiteConfig clone with moon filters disabled. Narrowband
    targets tolerate bright moons (Ha is least affected, OIII most). We
    don't try to model per-filter moon transmission — just gate it off
    entirely and let the per-night scheduler in Phase 3 weight filter
    choice against moon phase."""
    relaxed_window = replace(
        site.observing_window,
        max_moon_altitude_deg=90.0,
        max_moon_illumination=1.01,
        min_moon_separation_deg=0.0,
    )
    return replace(site, observing_window=relaxed_window)


def _score_candidate(best: Observability, fits_fov: bool) -> float:
    """Score = minutes-above-floor + max-altitude. Mosaic targets get an
    80% multiplier so single-frame targets float to the top by default
    (a mosaic is more work for the same final image — fair to demote)."""
    raw = float(best.minutes_above_minimum) + float(best.max_altitude_deg)
    return raw * (1.0 if fits_fov else 0.8)


def _build_reasons(
    target: DsoTarget,
    best: Observability,
    fits_fov: bool,
    fov_deg: tuple[float, float],
    relax_for_target: bool,
    *,
    ledger: Ledger | None = None,
    completion_fraction: float = 0.0,
    captured_minutes: float = 0.0,
    budget_minutes: float = 0.0,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if best.best_night_date is not None:
        reasons.append(
            f"{best.minutes_above_minimum} dark min above floor @ "
            f"{best.site_name} on {best.best_night_date.isoformat()}, "
            f"peak alt {best.max_altitude_deg:.1f}°"
        )
    else:
        reasons.append(
            f"{best.minutes_above_minimum} dark min above floor @ {best.site_name}, "
            f"peak alt {best.max_altitude_deg:.1f}°"
        )
    if not fits_fov:
        reasons.append(
            f"mosaic: {target.size_arcmin[0]:.0f}'×{target.size_arcmin[1]:.0f}' "
            f"vs rig FOV {fov_deg[0]:.2f}°×{fov_deg[1]:.2f}°"
        )
    if relax_for_target:
        reasons.append("moon-relaxed (narrowband)")
    if ledger is not None and budget_minutes > 0:
        pct = completion_fraction * 100.0
        reasons.append(
            f"ledger: {captured_minutes:.0f}/{budget_minutes:.0f} min "
            f"captured ({pct:.0f}% done)"
        )
    if target.notes:
        reasons.append(target.notes)
    return tuple(reasons)
