from __future__ import annotations

import csv
import io
import math
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
    per_bin_limit = max(1, math.ceil(config.row_limit / bins))

    for index in range(bins):
        ra_min = index * bin_degrees
        ra_max = min(360.0, ra_min + bin_degrees)
        params = _base_query_params(config, per_bin_limit)
        params["RAJ2000"] = f"{ra_min:.6f}..{ra_max:.6f}"
        response = _get_with_retries(params, timeout_seconds)
        if response is None:
            continue
        for target in parse_vsx_tsv(response.text):
            targets[target.oid] = target
        if len(targets) >= config.row_limit:
            break

    return list(targets.values())[: config.row_limit]


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


def type_matches(var_type: str, include_patterns: tuple[str, ...]) -> bool:
    normalized = var_type.upper()
    if not normalized:
        return True
    return any(pattern.upper() in normalized for pattern in include_patterns)


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
