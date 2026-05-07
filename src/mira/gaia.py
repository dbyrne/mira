from __future__ import annotations

import csv
import io
import re

from .cache import cached_get
from .config import GaiaConfig, ScoutConfig
from .models import Candidate, GaiaStats
from .vsx import tokenize_var_type

GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
GAIA_DR3_NAME_RE = re.compile(r"Gaia\s+DR3\s+(\d+)", re.IGNORECASE)


def extract_gaia_dr3_source_id(name: str | None) -> str | None:
    if not name:
        return None
    match = GAIA_DR3_NAME_RE.search(name)
    return match.group(1) if match else None


def enrich_candidates_with_gaia(
    candidates: list[Candidate],
    config: ScoutConfig,
    limit: int | None = None,
    extra_oids: set[int] | None = None,
) -> int:
    if not config.gaia.enabled:
        return 0
    enrich_limit = config.gaia.enrich_top if limit is None else limit
    extra_oids = extra_oids or set()
    targets = [
        candidate
        for index, candidate in enumerate(candidates)
        if index < enrich_limit or candidate.target.oid in extra_oids
    ]
    if not targets:
        return 0

    for candidate in targets:
        candidate.gaia = fetch_gaia_match(
            candidate.target.ra_deg,
            candidate.target.dec_deg,
            config.gaia,
            target_name=candidate.target.name,
        )
        apply_gaia_score(candidate, config)
    return len(targets)


def fetch_gaia_match(
    ra_deg: float,
    dec_deg: float,
    config: GaiaConfig,
    target_name: str | None = None,
) -> GaiaStats:
    source_id = extract_gaia_dr3_source_id(target_name)
    if source_id:
        try:
            return _fetch_gaia_by_source_id(source_id, config)
        except Exception as exc:
            # Fall through to cone search if the source_id query failed.
            cone = _fetch_gaia_by_position(ra_deg, dec_deg, config)
            if cone.status == "ok":
                return cone
            return GaiaStats(status="unavailable", note=f"source_id query failed ({exc}); cone: {cone.note}")
    return _fetch_gaia_by_position(ra_deg, dec_deg, config)


def _fetch_gaia_by_source_id(source_id: str, config: GaiaConfig) -> GaiaStats:
    query = (
        "SELECT source_id, phot_g_mean_mag, bp_rp, parallax, parallax_error, ruwe, "
        "phot_variable_flag, ipd_frac_multi_peak "
        f"FROM gaiadr3.gaia_source WHERE source_id = {int(source_id)}"
    )
    params = {
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "csv",
        "QUERY": query,
    }
    response = cached_get(GAIA_TAP_URL, params=params, timeout=config.timeout_seconds, namespace="gaia")
    response.raise_for_status()
    return parse_gaia_csv(response.text)


def _fetch_gaia_by_position(ra_deg: float, dec_deg: float, config: GaiaConfig) -> GaiaStats:
    radius_deg = config.search_radius_arcsec / 3600.0
    query = f"""
SELECT TOP 1 source_id, phot_g_mean_mag, bp_rp, parallax, parallax_error, ruwe,
phot_variable_flag, ipd_frac_multi_peak,
DISTANCE(POINT('ICRS', ra, dec), POINT('ICRS', {ra_deg:.8f}, {dec_deg:.8f})) AS dist_deg
FROM gaiadr3.gaia_source
WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra_deg:.8f}, {dec_deg:.8f}, {radius_deg:.8f}))
ORDER BY dist_deg ASC
"""
    params = {
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "csv",
        "QUERY": query,
    }
    try:
        response = cached_get(GAIA_TAP_URL, params=params, timeout=config.timeout_seconds, namespace="gaia")
        response.raise_for_status()
        return parse_gaia_csv(response.text)
    except Exception as exc:
        return GaiaStats(status="unavailable", note=str(exc))


def parse_gaia_csv(text: str) -> GaiaStats:
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return GaiaStats(status="no-match")
    row = rows[0]
    return GaiaStats(
        status="ok",
        source_id=_clean(row.get("source_id")),
        g_mag=_parse_float(row.get("phot_g_mean_mag")),
        bp_rp=_parse_float(row.get("bp_rp")),
        parallax_mas=_parse_float(row.get("parallax")),
        parallax_error_mas=_parse_float(row.get("parallax_error")),
        ruwe=_parse_float(row.get("ruwe")),
        photometric_variable=_clean(row.get("phot_variable_flag")).upper() == "VARIABLE",
        separation_arcsec=_arcsec(row.get("dist_deg")),
        ipd_frac_multi_peak=_parse_float(row.get("ipd_frac_multi_peak")),
    )


CROWDING_THRESHOLD = 0.1


def apply_gaia_score(candidate: Candidate, config: ScoutConfig) -> None:
    from .scoring import apply_target_bonus

    gaia = candidate.gaia
    if gaia is None or gaia.status != "ok":
        return
    flag = color_type_disagreement(candidate.target.var_type, gaia.bp_rp)
    if flag:
        gaia.color_anomaly = flag
        apply_target_bonus(
            candidate,
            config.scoring.gaia_color_anomaly_bonus,
            f"Gaia color anomaly: {flag}",
        )
    if gaia.ipd_frac_multi_peak is not None and gaia.ipd_frac_multi_peak > CROWDING_THRESHOLD:
        apply_target_bonus(
            candidate,
            -config.scoring.gaia_crowding_penalty,
            f"Gaia ipd_frac_multi_peak={gaia.ipd_frac_multi_peak:.2f} suggests blended/contaminated PSF",
        )


def color_type_disagreement(var_type: str, bp_rp: float | None) -> str | None:
    if bp_rp is None:
        return None
    tokens = tokenize_var_type(var_type)
    if not tokens:
        return None
    if any(t == "M" for t in tokens) and bp_rp < 1.5:
        return f"VSX type 'M' (Mira) but Gaia BP-RP={bp_rp:.2f} (expected >1.5)"
    if any(t.startswith("SR") for t in tokens) and bp_rp < 1.0:
        return f"VSX type SR-family but Gaia BP-RP={bp_rp:.2f} (expected >1.0 for red giants)"
    if any(t.startswith("L") for t in tokens) and bp_rp < 1.0:
        return f"VSX type L-family but Gaia BP-RP={bp_rp:.2f} (expected >1.0)"
    short_period = {"DSCT", "EA", "EB", "EW"}
    if (any(t.startswith("RR") for t in tokens) or any(t in short_period for t in tokens)) and bp_rp > 1.8:
        return f"VSX type {var_type} (short-period) but Gaia BP-RP={bp_rp:.2f} (expected <1.8)"
    return None


def _clean(value: str | None) -> str:
    return (value or "").strip().strip('"')


def _parse_float(value: str | None) -> float | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _arcsec(value: str | None) -> float | None:
    deg = _parse_float(value)
    return None if deg is None else deg * 3600.0
