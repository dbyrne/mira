"""AAVSO VSP (Variable Star Plotter) chart fetcher.

VSP returns the comparison-star sequence for a target. Auto-fetching at
submit time replaces hand-crafted comp-star JSON files: the user just gives
us a target name and we pull the same sequence the AAVSO chart shows.

API: GET https://app.aavso.org/vsp/api/v2/chart/?star=<name>&fov=<arcmin>&maglimit=<mag>&format=json
Docs: https://app.aavso.org/vsp/api/v2/api-help
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .cache import cached_get
from .photometry import CompStar


VSP_BASE_URL = "https://app.aavso.org/vsp/api/v2/chart/"
DEFAULT_FOV_ARCMIN = 60.0
DEFAULT_MAGLIMIT = 14.5
DEFAULT_BAND = "V"
DEFAULT_TIMEOUT = 30


@dataclass
class VspChart:
    chart_id: str
    star_name: str
    target_ra_deg: float | None
    target_dec_deg: float | None
    comps: list[CompStar]
    image_url: str | None = None


def fetch_vsp_chart(
    target_name: str,
    *,
    fov_arcmin: float = DEFAULT_FOV_ARCMIN,
    maglimit: float = DEFAULT_MAGLIMIT,
    band: str = DEFAULT_BAND,
    timeout: int = DEFAULT_TIMEOUT,
) -> VspChart:
    """Fetch the VSP comp-star sequence for a target. Raises ValueError if
    no usable comps come back."""
    params = {
        "star": target_name,
        "fov": str(fov_arcmin),
        "maglimit": str(maglimit),
        "format": "json",
    }
    response = cached_get(VSP_BASE_URL, params=params, timeout=timeout, namespace="vsp")
    response.raise_for_status()
    data = json.loads(response.text)
    return parse_vsp_chart(data, band=band)


def parse_vsp_chart(data: dict[str, Any], *, band: str = DEFAULT_BAND) -> VspChart:
    chart_id = str(data.get("chartid") or "na")
    star_name = str(data.get("star") or "")
    target_ra = _hms_to_deg(str(data.get("ra") or ""))
    target_dec = _dms_to_deg(str(data.get("dec") or ""))

    comps: list[CompStar] = []
    for entry in data.get("photometry") or []:
        mag, _err = _select_band(entry.get("bands") or [], band)
        if mag is None:
            continue
        comp_ra = _hms_to_deg(str(entry.get("ra") or ""))
        comp_dec = _dms_to_deg(str(entry.get("dec") or ""))
        if comp_ra is None or comp_dec is None:
            continue
        label = str(entry.get("label") or "").strip() or f"{mag:.1f}"
        comps.append(
            CompStar(
                label=label,
                ra_deg=comp_ra,
                dec_deg=comp_dec,
                catalog_mag=mag,
                catalog_band=band,
            )
        )
    if not comps:
        raise ValueError(
            f"VSP chart {chart_id} has no comp stars in band {band}"
        )
    return VspChart(
        chart_id=chart_id,
        star_name=star_name,
        target_ra_deg=target_ra,
        target_dec_deg=target_dec,
        comps=comps,
        image_url=data.get("image_uri"),
    )


def filter_comps_for_target(
    comps: list[CompStar],
    target_mag: float | None,
    *,
    max_count: int = 6,
    mag_tolerance: float = 2.0,
) -> list[CompStar]:
    """Pick comps near the target's expected magnitude. Returns the closest
    `max_count` by magnitude distance, capped to comps within ±mag_tolerance.
    If target_mag is None, returns the brightest `max_count` (likely safer
    against noise) but warns nothing — caller should know the target is
    faint or unknown."""
    if target_mag is None:
        return sorted(comps, key=lambda c: c.catalog_mag)[:max_count]
    in_range = [c for c in comps if abs(c.catalog_mag - target_mag) <= mag_tolerance]
    in_range.sort(key=lambda c: abs(c.catalog_mag - target_mag))
    return in_range[:max_count]


def _select_band(
    bands: list[dict[str, Any]], band: str
) -> tuple[float | None, float | None]:
    target = band.upper()
    for b in bands:
        if str(b.get("band") or "").strip().upper() == target:
            mag = b.get("mag")
            err = b.get("error")
            return (
                float(mag) if mag is not None else None,
                float(err) if err is not None else None,
            )
    return (None, None)


def _hms_to_deg(value: str) -> float | None:
    """Parse 'HH:MM:SS.ss' or 'HH MM SS.ss' RA into degrees."""
    if not value:
        return None
    cleaned = value.replace("h", " ").replace("m", " ").replace("s", " ").replace(":", " ")
    parts = cleaned.split()
    if not parts:
        return None
    try:
        h = float(parts[0])
        m = float(parts[1]) if len(parts) > 1 else 0.0
        s = float(parts[2]) if len(parts) > 2 else 0.0
    except ValueError:
        return None
    return (h + m / 60.0 + s / 3600.0) * 15.0


def _dms_to_deg(value: str) -> float | None:
    """Parse '+DD:MM:SS.s' or '-DD MM SS.s' Dec into degrees."""
    if not value:
        return None
    s = value.strip()
    sign = 1.0
    if s.startswith("-"):
        sign = -1.0
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    cleaned = s.replace("d", " ").replace("m", " ").replace("s", " ").replace(":", " ").replace("°", " ").replace("'", " ").replace('"', " ")
    parts = cleaned.split()
    if not parts:
        return None
    try:
        d = float(parts[0])
        m = float(parts[1]) if len(parts) > 1 else 0.0
        sec = float(parts[2]) if len(parts) > 2 else 0.0
    except ValueError:
        return None
    return sign * (d + m / 60.0 + sec / 3600.0)
