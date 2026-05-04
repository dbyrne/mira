from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from .cache import cached_get
from .config import AavsoConfig, ScoutConfig
from .models import AavsoStats, Candidate
from .observability import julian_date

AAVSO_VSX_API_URL = "https://vsx.aavso.org/index.php"


def enrich_candidates_with_aavso(candidates: list[Candidate], config: ScoutConfig, limit: int | None = None) -> None:
    if not config.aavso.enabled:
        return
    enrich_limit = config.aavso.enrich_top if limit is None else limit
    if enrich_limit <= 0:
        return

    for candidate in candidates[:enrich_limit]:
        candidate.aavso = fetch_recent_observation_count(candidate.target.name, config.aavso)
        apply_aavso_score(candidate, config)

    candidates.sort(key=lambda item: item.score, reverse=True)


def fetch_recent_observation_count(name: str, config: AavsoConfig) -> AavsoStats:
    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=config.recent_days)
    from_jd = julian_date(from_dt)
    to_jd = julian_date(to_dt)
    params = {
        "view": "api.object",
        "ident": name,
        "data": "50000",
        "fromjd": f"{from_jd:.5f}",
        "tojd": f"{to_jd:.5f}",
        "csv": "",
        "band": ",".join(config.bands),
        "mtype": "std",
    }
    try:
        response = cached_get(AAVSO_VSX_API_URL, params=params, timeout=config.timeout_seconds, namespace="aavso")
        response.raise_for_status()
        count = count_cdata_csv_rows(response.text)
        return AavsoStats(status="ok", recent_observations=count, from_jd=from_jd, to_jd=to_jd)
    except Exception as exc:
        return AavsoStats(status="unavailable", from_jd=from_jd, to_jd=to_jd, note=str(exc))


def count_cdata_csv_rows(xml_text: str) -> int:
    root = ET.fromstring(xml_text)
    data_element = root.find("Data")
    if data_element is None or not data_element.text:
        return 0
    reader = csv.DictReader(io.StringIO(data_element.text))
    return sum(1 for row in reader if any((value or "").strip() for value in row.values()))


def apply_aavso_score(candidate: Candidate, config: ScoutConfig) -> None:
    stats = candidate.aavso
    if stats is None:
        return
    if stats.status != "ok":
        candidate.reasons.append("AAVSO recent-coverage check unavailable")
        return
    if stats.recent_observations <= config.aavso.sparse_recent_threshold:
        candidate.score += config.scoring.sparse_aavso_bonus
        candidate.reasons.append(f"sparse AAVSO coverage ({stats.recent_observations} recent observations)")
    elif stats.recent_observations >= config.aavso.sparse_recent_threshold * 10:
        candidate.score -= config.scoring.well_observed_aavso_penalty
        candidate.reasons.append(f"well-covered in AAVSO recently ({stats.recent_observations} observations)")
    else:
        candidate.reasons.append(f"AAVSO has {stats.recent_observations} recent observations")
