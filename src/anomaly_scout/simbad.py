from __future__ import annotations

import csv
import io
from urllib.parse import urlencode

import requests

from .cache import cached_get
from .config import ScoutConfig, SimbadConfig
from .models import Candidate, SimbadStats

SIMBAD_TAP_SYNC_URL = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
SIMBAD_COO_URL = "https://simbad.cds.unistra.fr/simbad/sim-coo"


def enrich_candidates_with_simbad(candidates: list[Candidate], config: ScoutConfig, limit: int | None = None) -> None:
    if not config.simbad.enabled:
        return
    enrich_limit = config.simbad.enrich_top if limit is None else limit
    if enrich_limit <= 0:
        return

    for candidate in candidates[:enrich_limit]:
        candidate.simbad = fetch_simbad_match(candidate.target.ra_deg, candidate.target.dec_deg, config.simbad)


def fetch_simbad_match(ra_deg: float, dec_deg: float, config: SimbadConfig) -> SimbadStats:
    query = _build_region_query(ra_deg, dec_deg, config.search_radius_arcsec / 3600.0)
    params = {
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "tsv",
        "QUERY": query,
    }
    try:
        response = cached_get(SIMBAD_TAP_SYNC_URL, params=params, timeout=config.timeout_seconds, namespace="simbad")
        response.raise_for_status()
        return parse_simbad_rows(response.text, ra_deg, dec_deg, config)
    except Exception as exc:
        return SimbadStats(status="unavailable", url=coordinate_search_url(ra_deg, dec_deg, config), note=str(exc))


def parse_simbad_rows(text: str, ra_deg: float, dec_deg: float, config: SimbadConfig) -> SimbadStats:
    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    if not rows:
        return SimbadStats(status="no-match", url=coordinate_search_url(ra_deg, dec_deg, config))

    first = rows[0]
    identifiers = []
    for row in rows:
        ident = _clean(row.get("id"))
        if ident and ident not in identifiers:
            identifiers.append(ident)

    return SimbadStats(
        status="ok",
        main_id=_clean(first.get("main_id")),
        object_type=_clean(first.get("otype")),
        ra_deg=_parse_float(first.get("ra")),
        dec_deg=_parse_float(first.get("dec")),
        separation_arcsec=(_parse_float(first.get("dist_deg")) or 0.0) * 3600.0,
        identifiers=tuple(identifiers[:8]),
        url=coordinate_search_url(ra_deg, dec_deg, config),
    )


def coordinate_search_url(ra_deg: float, dec_deg: float, config: SimbadConfig) -> str:
    params = urlencode(
        {
            "Coord": f"{ra_deg:.6f} {dec_deg:.6f}",
            "Radius": f"{config.search_radius_arcsec:.1f}",
            "Radius.unit": "arcsec",
        }
    )
    return f"{SIMBAD_COO_URL}?{params}"


def _build_region_query(ra_deg: float, dec_deg: float, radius_deg: float) -> str:
    return f"""
SELECT TOP 20 basic.main_id, basic.otype, basic.ra, basic.dec, ident.id,
DISTANCE(POINT('ICRS', basic.ra, basic.dec), POINT('ICRS', {ra_deg:.8f}, {dec_deg:.8f})) AS dist_deg
FROM basic
LEFT OUTER JOIN ident ON ident.oidref = basic.oid
WHERE CONTAINS(
  POINT('ICRS', basic.ra, basic.dec),
  CIRCLE('ICRS', {ra_deg:.8f}, {dec_deg:.8f}, {radius_deg:.8f})
) = 1
ORDER BY dist_deg ASC
"""


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().strip('"')


def _parse_float(value: str | None) -> float | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
