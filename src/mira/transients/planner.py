"""Transient planner — filter the bright-transient list by observability
and the rig's magnitude reach, then rank.

Reuses ``evaluate_observability_at_coords`` (same alt/sun/horizon math as
every other Mira path). Two transient-specific choices:

- **Moon gate relaxed.** Transients are point sources; a bright stellar
  target is barely touched by moonlight (unlike a faint extended galaxy),
  so the VSX-style moon filter would wrongly drop perfectly good targets on
  a bright-moon night — exactly when transients shine as the fallback. We
  evaluate observability with the moon filters disabled.
- **Reach is a hard, honest line.** A transient fainter than the rig's
  reach is kept (so the user sees what *would* be reachable on the other
  rig) but flagged ``within_reach=False`` and sorted below the reachable
  ones. Nothing is silently hidden.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from ..config import ScoutConfig, SiteConfig
from ..models import Observability
from ..observability import evaluate_observability_at_coords
from .catalog import Transient


@dataclass(frozen=True)
class TransientCandidate:
    """A transient that's observable from at least one configured site."""
    transient: Transient
    observabilities: tuple[Observability, ...]
    best_observability: Observability
    within_reach: bool
    reasons: tuple[str, ...]

    @property
    def best_site_name(self) -> str:
        return self.best_observability.site_name


def build_transient_candidates(
    transients: list[Transient],
    config: ScoutConfig,
    *,
    start_date: date | None = None,
    max_mag: float | None = None,
) -> list[TransientCandidate]:
    """Keep transients observable from any site; flag reach; rank.

    Sort order: reachable first, then brightest, then most dark-minutes,
    then highest. ``max_mag=None`` treats everything as within reach."""
    candidates: list[TransientCandidate] = []
    for transient in transients:
        observabilities = [
            evaluate_observability_at_coords(
                transient.ra_deg, transient.dec_deg, _relax_moon(site),
                start_date=start_date,
            )
            for site in config.sites
        ]
        viable = [o for o in observabilities if o.minutes_above_minimum > 0]
        if not viable:
            continue  # not observable from anywhere tonight
        best = max(
            viable, key=lambda o: (o.minutes_above_minimum, o.max_altitude_deg),
        )
        within_reach = max_mag is None or transient.magnitude <= max_mag
        candidates.append(TransientCandidate(
            transient=transient,
            observabilities=tuple(observabilities),
            best_observability=best,
            within_reach=within_reach,
            reasons=_build_reasons(transient, best, within_reach, max_mag),
        ))
    candidates.sort(key=lambda c: (
        not c.within_reach,                       # reachable first
        c.transient.magnitude,                    # then brightest
        -c.best_observability.minutes_above_minimum,
        -c.best_observability.max_altitude_deg,
        c.transient.name,
    ))
    return candidates


def _relax_moon(site: SiteConfig) -> SiteConfig:
    """Disable the moon filters — point-source transients tolerate moonlight."""
    relaxed = replace(
        site.observing_window,
        max_moon_altitude_deg=90.0,
        max_moon_illumination=1.01,
        min_moon_separation_deg=0.0,
    )
    return replace(site, observing_window=relaxed)


def _build_reasons(
    transient: Transient,
    best: Observability,
    within_reach: bool,
    max_mag: float | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    host = transient.host if transient.host not in ("?", "none") else "no catalogued host"
    reasons.append(f"{transient.sn_type} in {host}, mag {transient.magnitude:.1f}")
    night = (
        best.best_night_date.isoformat() if best.best_night_date else "tonight"
    )
    reasons.append(
        f"{best.minutes_above_minimum} dark min above floor @ {best.site_name} "
        f"({night}), peak alt {best.max_altitude_deg:.1f}°"
    )
    if transient.mag_stale:
        reasons.append(
            "⚠ last observation > 1 month old — may have faded; verify before imaging"
        )
    if not within_reach and max_mag is not None:
        reasons.append(
            f"beyond this rig's reach (mag {transient.magnitude:.1f} > {max_mag:.1f}) "
            "— deeper rig only"
        )
    return tuple(reasons)
