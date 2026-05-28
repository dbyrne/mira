"""Bright-transient checking — the `mira transients` path.

A third external-data target source alongside VSX (variable stars) and the
curated DSO/galaxy catalogs: recent *bright transients* (supernovae, novae,
TDEs) worth amateur follow-up. Scrapes Rochester Astronomy's curated
"active supernovae over mag 17" table, then filters by observability from
the configured site(s) and the rig's magnitude reach.

Transients are point sources, which makes them the ideal urban/moonlit
science target — moonlight barely touches a bright stellar point source,
unlike the faint extended galaxies/nebulae — and they're directly
AAVSO-submittable via `mira submit`.
"""
from .catalog import Transient, fetch_active_supernovae, parse_active_supernovae
from .planner import TransientCandidate, build_transient_candidates

__all__ = [
    "Transient",
    "fetch_active_supernovae",
    "parse_active_supernovae",
    "TransientCandidate",
    "build_transient_candidates",
]
