from __future__ import annotations

import csv
import io
import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .cache import cached_get
from .config import AavsoConfig, ScoutConfig
from .models import AavsoStats, Candidate
from .observability import julian_date
from .period_analysis import (
    PERIOD_MAX_DAYS,
    PERIOD_MIN_DAYS,
    assess_period_disagreement,
    estimate_period,
)

AAVSO_VSX_API_URL = "https://vsx.aavso.org/index.php"
AAVSO_CACHE_DIR = Path("data/cache/aavso")


def enrich_candidates_with_aavso(
    candidates: list[Candidate],
    config: ScoutConfig,
    limit: int | None = None,
    extra_oids: set[int] | None = None,
) -> int:
    if not config.aavso.enabled:
        return 0
    enrich_limit = config.aavso.enrich_top if limit is None else limit
    extra_oids = extra_oids or set()
    targets = [
        candidate
        for index, candidate in enumerate(candidates)
        if index < enrich_limit or candidate.target.oid in extra_oids
    ]
    if not targets:
        return 0

    for candidate in targets:
        candidate.aavso = fetch_recent_observation_count(
            candidate.target.name,
            config.aavso,
            catalog_period=candidate.target.period_days,
        )
        apply_aavso_score(candidate, config)

    from .scoring import candidate_sort_key

    candidates.sort(key=candidate_sort_key)
    return len(targets)


def fetch_recent_observation_count(
    name: str,
    config: AavsoConfig,
    catalog_period: float | None = None,
) -> AavsoStats:
    # Floor the query window to whole JDs so the request URL — and therefore
    # the cache key — is stable across runs within the same day. JDs at
    # second resolution made every run's URL unique: the cache never hit
    # (TTL dead) and data/cache/aavso/ grew without bound.
    now_jd = julian_date(datetime.now(timezone.utc))
    from_jd = float(math.floor(now_jd) - config.recent_days)
    to_jd = float(math.ceil(now_jd))
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
        observations = parse_cdata_observations(response.text)
        count = len(observations)
        last_observation_jd = max((obs[0] for obs in observations), default=None)
        recent_median_mag, recent_min_mag, recent_max_mag = _summarize_mags(observations)
        recent_samples = _sample_observations(observations)

        derived_period: float | None = None
        peak_power: float | None = None
        period_disagrees: bool | None = None
        period_note = ""
        if count > 0:
            # Run the period analysis even when VSX has no catalog period:
            # that is the only path to the "period discovered" bonus in
            # apply_aavso_score (gating on catalog_period made it dead code).
            # assess_period_disagreement returns (None, "") when
            # catalog_period is None, so the disagreement logic is unaffected.
            times = [obs[0] for obs in observations]
            mags = [obs[1] for obs in observations]
            bands = [obs[2] for obs in observations]
            derived_period, peak_power, span = estimate_period(times, mags, bands)
            period_disagrees, period_note = assess_period_disagreement(
                catalog_period=catalog_period,
                derived_period=derived_period,
                peak_power=peak_power,
                time_span_days=span,
                period_min=PERIOD_MIN_DAYS,
                period_max=PERIOD_MAX_DAYS,
                min_peak_power=config.period_min_peak_power,
            )
        return AavsoStats(
            status="ok",
            recent_observations=count,
            from_jd=from_jd,
            to_jd=to_jd,
            last_observation_jd=last_observation_jd,
            derived_period_days=derived_period,
            period_power=peak_power,
            period_disagrees=period_disagrees,
            period_note=period_note,
            recent_median_mag=recent_median_mag,
            recent_min_mag=recent_min_mag,
            recent_max_mag=recent_max_mag,
            recent_samples=recent_samples,
        )
    except Exception as exc:
        cached_text = find_cached_response_for_name(name)
        if cached_text is not None:
            count = count_cdata_csv_rows(cached_text)
            return AavsoStats(
                status="ok-cached",
                recent_observations=count,
                from_jd=from_jd,
                to_jd=to_jd,
                note=f"used cached AAVSO response after live request failed: {exc}",
            )
        return AavsoStats(status="unavailable", from_jd=from_jd, to_jd=to_jd, note=str(exc))


def count_cdata_csv_rows(xml_text: str) -> int:
    return len(parse_cdata_observations(xml_text))


def parse_cdata_observations(xml_text: str) -> list[tuple[float, float, str]]:
    """Returns a list of (JD, mag, band) triples from an AAVSO VSX API XML response."""
    root = ET.fromstring(xml_text)
    data_element = root.find("Data")
    if data_element is None or not data_element.text:
        return []
    reader = csv.DictReader(io.StringIO(data_element.text))
    observations: list[tuple[float, float, str]] = []
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        jd = _parse_float(row.get("JD") or row.get("jd"))
        mag = _parse_float(row.get("mag") or row.get("Magnitude") or row.get("magnitude"))
        band = (row.get("band") or row.get("Band") or "V").strip()
        if jd is None or mag is None:
            continue
        observations.append((jd, mag, band))
    return observations


def apply_aavso_score(candidate: Candidate, config: ScoutConfig) -> None:
    from .scoring import apply_target_bonus, apply_target_reason

    stats = candidate.aavso
    if stats is None:
        return
    if stats.status not in ("ok", "ok-cached"):
        apply_target_reason(candidate, "AAVSO recent-coverage check unavailable")
        return
    if stats.recent_observations <= config.aavso.sparse_recent_threshold:
        apply_target_bonus(
            candidate,
            config.scoring.sparse_aavso_bonus,
            f"sparse AAVSO coverage ({stats.recent_observations} recent observations)",
        )
    elif stats.recent_observations >= config.aavso.sparse_recent_threshold * 10:
        apply_target_bonus(
            candidate,
            -config.scoring.well_observed_aavso_penalty,
            f"well-covered in AAVSO recently ({stats.recent_observations} observations)",
        )
    else:
        apply_target_reason(
            candidate,
            f"AAVSO has {stats.recent_observations} recent observations",
        )

    if stats.period_disagrees is True:
        catalog = candidate.target.period_days
        catalog_text = f"{catalog:.3f}" if catalog is not None else "n/a"
        apply_target_bonus(
            candidate,
            config.scoring.period_disagreement_bonus,
            f"AAVSO period {stats.derived_period_days:.4f} d disagrees with catalog {catalog_text} d",
        )
    elif stats.period_disagrees is False:
        apply_target_reason(
            candidate,
            f"AAVSO period {stats.derived_period_days:.4f} d agrees with catalog within tolerance",
        )
    elif (
        candidate.target.period_days is None
        and stats.derived_period_days is not None
        and stats.period_power is not None
        and stats.period_power >= config.aavso.period_min_peak_power
    ):
        apply_target_bonus(
            candidate,
            config.scoring.period_discovered_bonus,
            f"AAVSO discovered period {stats.derived_period_days:.4f} d "
            f"(peak power {stats.period_power:.3f}); VSX has no catalog period",
        )


def _summarize_mags(observations: list[tuple[float, float, str]]) -> tuple[float | None, float | None, float | None]:
    if not observations:
        return None, None, None
    mags = sorted(obs[1] for obs in observations)
    median = mags[len(mags) // 2]
    return median, mags[0], mags[-1]


def _sample_observations(
    observations: list[tuple[float, float, str]],
    sample_count: int = 10,
) -> list[tuple[float, float, str]]:
    """Return up to `sample_count` recent observations, most recent first."""
    if not observations:
        return []
    sorted_obs = sorted(observations, key=lambda obs: obs[0], reverse=True)
    return sorted_obs[:sample_count]


def find_cached_response_for_name(name: str) -> str | None:
    """Fallback used when the live AAVSO API request fails: scan the cache
    directory for a previously-successful response keyed by the same target
    name. Returns the cached XML text or None if nothing usable is on disk.

    The cached URL's query string is parsed and its ``ident`` parameter
    compared exactly. A substring test would let "ident=ZTF J123" match a
    cached "ZTF J1234..." entry and report the WRONG star's observations
    as ok-cached.
    """
    if not AAVSO_CACHE_DIR.exists():
        return None
    for path in sorted(AAVSO_CACHE_DIR.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if payload.get("status_code") != 200:
            continue
        # parse_qs decodes exactly what requests' urlencode produced for the
        # original request ('+' for spaces, %XX escapes), so equality against
        # the raw name is an exact round-trip match.
        query = urlsplit(str(payload.get("url", ""))).query
        if name not in parse_qs(query).get("ident", []):
            continue
        text = str(payload.get("text", ""))
        if text.startswith("<?xml"):
            return text
    return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
