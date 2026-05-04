from __future__ import annotations

import csv
import io
import math
import random
import re
import time
from typing import Iterable

import requests

from .cache import cached_get
from .config import VsxQueryConfig
from .models import VsxTarget

VIZIER_ASU_TSV_URL = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
VSX_COLUMNS = (
    "OID",
    "Name",
    "Type",
    "max",
    "min",
    "n_max",
    "f_min",
    "n_min",
    "Period",
    "Sp",
    "RAJ2000",
    "DEJ2000",
)


def fetch_vsx_targets(config: VsxQueryConfig, timeout_seconds: int = 60) -> list[VsxTarget]:
    targets: dict[int, VsxTarget] = {}
    bin_degrees = max(1.0, min(180.0, config.ra_bin_degrees))
    bins = math.ceil(360.0 / bin_degrees)
    per_bin_target = max(1, math.ceil(config.row_limit / bins))
    oversample = max(1, int(config.oversample_factor))
    per_bin_request = per_bin_target * oversample
    half_request = max(1, per_bin_request // 2)

    for index in range(bins):
        ra_min = index * bin_degrees
        ra_max = min(360.0, ra_min + bin_degrees)
        ra_range = f"{ra_min:.6f}..{ra_max:.6f}"

        bin_rows: dict[int, VsxTarget] = {}
        # Pull from both ends of the OID range so the per-bin pool covers
        # GCVS-era classical names AND newer survey discoveries. Either alone
        # would bias the queue toward one population; the other end then
        # disappears from the final sample.
        for sort_value in ("OID", "-OID"):
            params = _base_query_params(config, half_request)
            params["RAJ2000"] = ra_range
            params["-sort"] = sort_value
            response = _get_with_retries(params, timeout_seconds)
            if response is None:
                continue
            for target in parse_vsx_tsv(response.text):
                bin_rows.setdefault(target.oid, target)

        if not bin_rows:
            continue
        sampled = _sample_bin(list(bin_rows.values()), per_bin_target, seed=index)
        for target in sampled:
            targets[target.oid] = target
        if len(targets) >= config.row_limit:
            break

    return list(targets.values())[: config.row_limit]


def _sample_bin(rows: list[VsxTarget], target_count: int, seed: int) -> list[VsxTarget]:
    if len(rows) <= target_count:
        return rows
    rng = random.Random(seed)
    return rng.sample(rows, target_count)


def _get_with_retries(params: dict[str, str], timeout_seconds: int, attempts: int = 3) -> requests.Response | None:
    for attempt in range(1, attempts + 1):
        try:
            response = cached_get(VIZIER_ASU_TSV_URL, params=params, timeout=timeout_seconds, namespace="vsx")
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == attempts:
                return None
            time.sleep(1.5 * attempt)
    return None


def fetch_vsx_target_by_name(name: str, timeout_seconds: int = 30) -> VsxTarget | None:
    params = {
        "-source": "B/vsx/vsx",
        "-out.max": "10",
        "-out": ",".join(VSX_COLUMNS),
        "Name": name,
    }
    response = _get_with_retries(params, timeout_seconds)
    if response is None:
        return None
    targets = list(parse_vsx_tsv(response.text))
    if not targets:
        return None
    needle = name.strip().lower()
    for target in targets:
        if target.name.strip().lower() == needle:
            return target
    return targets[0]


def _base_query_params(config: VsxQueryConfig, row_limit: int) -> dict[str, str]:
    params: dict[str, str] = {
        "-source": "B/vsx/vsx",
        "-out.max": str(row_limit),
        "-out": ",".join(VSX_COLUMNS),
        "DEJ2000": f">{config.min_declination_deg}",
        "max": f"<{config.max_bright_mag}",
    }
    if config.require_period:
        params["Period"] = ">0"
    return params


def parse_vsx_tsv(text: str) -> Iterable[VsxTarget]:
    data_lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if not data_lines:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(data_lines)), delimiter="\t")
    targets: list[VsxTarget] = []
    for row in reader:
        oid = _parse_int(row.get("OID"))
        if oid is None:
            continue
        ra = _parse_float(row.get("RAJ2000"))
        dec = _parse_float(row.get("DEJ2000"))
        if ra is None or dec is None:
            continue

        targets.append(
            VsxTarget(
                oid=oid,
                name=(row.get("Name") or "").strip(),
                var_type=(row.get("Type") or "").strip(),
                max_mag=_parse_float(row.get("max")),
                min_mag=_parse_float(row.get("min")),
                max_band=(row.get("n_max") or "").strip(),
                min_band=(row.get("n_min") or "").strip(),
                min_is_amplitude=bool((row.get("f_min") or "").strip()),
                period_days=_parse_float(row.get("Period")),
                spectral_type=(row.get("Sp") or "").strip(),
                ra_deg=ra,
                dec_deg=dec,
            )
        )
    return targets


_TOKEN_SPLIT_RE = re.compile(r"[/|]")
_UNCERTAINTY_TRAILERS = ":?"


def tokenize_var_type(var_type: str) -> list[str]:
    normalized = (var_type or "").upper().strip()
    if not normalized:
        return []
    tokens: list[str] = []
    for raw in _TOKEN_SPLIT_RE.split(normalized):
        cleaned = raw.strip().rstrip(_UNCERTAINTY_TRAILERS).strip()
        if cleaned:
            tokens.append(cleaned)
    return tokens


def type_matches(var_type: str, include_patterns: tuple[str, ...]) -> bool:
    tokens = tokenize_var_type(var_type)
    if not tokens:
        return any(pattern.strip() == "?" for pattern in include_patterns)
    for token in tokens:
        for pattern in include_patterns:
            pat = pattern.upper().strip()
            if not pat or pat == "?":
                continue
            if pat.endswith("*"):
                prefix = pat[:-1]
                if prefix and token.startswith(prefix):
                    return True
            elif token == pat:
                return True
    return False


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None
