from __future__ import annotations

import csv
import io
import math
from urllib.parse import urlencode

import requests

from .cache import cached_get
from .config import GaiaConfig, ScoutConfig
from .models import Candidate, GaiaStats

GAIA_DR3_VIZIER_URL = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
GAIA_COLUMNS = "Source,RA_ICRS,DE_ICRS,Gmag,BP-RP,Plx,e_Plx,RUWE"


def enrich_candidates_with_gaia(candidates: list[Candidate], config: ScoutConfig, limit: int | None = None) -> None:
    if not config.gaia.enabled:
        return
    enrich_limit = config.gaia.enrich_top if limit is None else limit
    if enrich_limit <= 0:
        return

    for candidate in candidates[:enrich_limit]:
        candidate.gaia = fetch_gaia_match(candidate.target.ra_deg, candidate.target.dec_deg, config.gaia)


def fetch_gaia_match(ra_deg: float, dec_deg: float, config: GaiaConfig) -> GaiaStats:
    params = {
        "-source": "I/355/gaiadr3",
        "-out.max": "5",
        "-out": GAIA_COLUMNS,
        "-c": f"{ra_deg:.6f} {dec_deg:.6f}",
        "-c.rs": f"{config.search_radius_arcsec:.1f}",
    }
    try:
        response = cached_get(GAIA_DR3_VIZIER_URL, params=params, timeout=config.timeout_seconds, namespace="gaia")
        response.raise_for_status()
        return parse_gaia_tsv(response.text, ra_deg, dec_deg, config)
    except Exception as exc:
        return GaiaStats(status="unavailable", url=gaia_query_url(ra_deg, dec_deg, config), note=str(exc))


def parse_gaia_tsv(text: str, target_ra_deg: float, target_dec_deg: float, config: GaiaConfig) -> GaiaStats:
    data_lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if not data_lines:
        return GaiaStats(status="no-match", url=gaia_query_url(target_ra_deg, target_dec_deg, config))

    reader = csv.DictReader(io.StringIO("\n".join(data_lines)), delimiter="\t")
    best_row: dict[str, str] | None = None
    best_sep: float | None = None
    for row in reader:
        source_id = _clean(row.get("Source"))
        if not source_id or source_id.lower() == "source":
            continue
        ra = _parse_float(row.get("RA_ICRS"))
        dec = _parse_float(row.get("DE_ICRS"))
        if ra is None or dec is None:
            continue
        sep = angular_separation_arcsec(target_ra_deg, target_dec_deg, ra, dec)
        if best_sep is None or sep < best_sep:
            best_sep = sep
            best_row = row

    if best_row is None:
        return GaiaStats(status="no-match", url=gaia_query_url(target_ra_deg, target_dec_deg, config))

    parallax = _parse_float(best_row.get("Plx"))
    g_mag = _parse_float(best_row.get("Gmag"))
    return GaiaStats(
        status="ok",
        source_id=_clean(best_row.get("Source")),
        g_mag=g_mag,
        bp_rp=_parse_float(best_row.get("BP-RP")),
        parallax_mas=parallax,
        parallax_error_mas=_parse_float(best_row.get("e_Plx")),
        ruwe=_parse_float(best_row.get("RUWE")),
        absolute_g_mag=absolute_g_mag(g_mag, parallax),
        separation_arcsec=best_sep,
        url=gaia_query_url(target_ra_deg, target_dec_deg, config),
    )


def gaia_query_url(ra_deg: float, dec_deg: float, config: GaiaConfig) -> str:
    params = urlencode(
        {
            "-source": "I/355/gaiadr3",
            "-out": GAIA_COLUMNS,
            "-c": f"{ra_deg:.6f} {dec_deg:.6f}",
            "-c.rs": f"{config.search_radius_arcsec:.1f}",
        }
    )
    return f"{GAIA_DR3_VIZIER_URL}?{params}"


def absolute_g_mag(g_mag: float | None, parallax_mas: float | None) -> float | None:
    if g_mag is None or parallax_mas is None or parallax_mas <= 0:
        return None
    distance_pc = 1000.0 / parallax_mas
    return g_mag - 5.0 * math.log10(distance_pc / 10.0)


def angular_separation_arcsec(ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float) -> float:
    ra1 = math.radians(ra1_deg)
    dec1 = math.radians(dec1_deg)
    ra2 = math.radians(ra2_deg)
    dec2 = math.radians(dec2_deg)
    sin_d_dec = math.sin((dec2 - dec1) / 2.0)
    sin_d_ra = math.sin((ra2 - ra1) / 2.0)
    a = sin_d_dec**2 + math.cos(dec1) * math.cos(dec2) * sin_d_ra**2
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


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
