from __future__ import annotations

import csv
import io
from pathlib import Path
from urllib.parse import urlencode

import matplotlib.pyplot as plt
import requests

from .cache import cached_get
from .config import ZtfConfig
from .models import Candidate, ZtfStats
from .period_analysis import (
    PERIOD_MAX_DAYS,
    PERIOD_MIN_DAYS,
    assess_period_disagreement,
    estimate_period,
    period_disagreement,
)

ZTF_LIGHT_CURVE_URL = "https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves"


def enrich_with_ztf(candidate: Candidate, config: ZtfConfig, packet_dir: Path) -> ZtfStats:
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for band in config.bands:
        try:
            rows.extend(fetch_ztf_light_curve(candidate.target.ra_deg, candidate.target.dec_deg, band, config))
        except Exception as exc:  # ZTF is an enrichment, not a pipeline blocker.
            errors.append(f"{band}: {exc}")

    if not rows:
        note = "; ".join(errors) if errors else "no ZTF rows returned"
        return ZtfStats(status="unavailable", note=note)

    mags = [_parse_float(row.get("mag") or row.get("MAG")) for row in rows]
    mags = [mag for mag in mags if mag is not None]
    bands = sorted({(row.get("filtercode") or row.get("band") or row.get("BAND") or "").strip() for row in rows})
    if not mags:
        return ZtfStats(status="parsed-no-magnitudes", observations=len(rows), bands=tuple(bands))

    sorted_mags = sorted(mags)
    median_mag = sorted_mags[len(sorted_mags) // 2]
    amplitude = percentile(sorted_mags, 95) - percentile(sorted_mags, 5)
    plot_path = plot_light_curve(candidate, rows, packet_dir)

    derived_period, peak_power, time_span = estimate_period_from_rows(rows)
    catalog_period = candidate.target.period_days
    period_disagrees, gating_note = assess_period_disagreement(
        catalog_period=catalog_period,
        derived_period=derived_period,
        peak_power=peak_power,
        time_span_days=time_span,
        period_min=PERIOD_MIN_DAYS,
        period_max=PERIOD_MAX_DAYS,
        min_peak_power=config.period_min_peak_power,
    )
    folded_plot_path = None
    if derived_period is not None:
        folded_plot_path = plot_folded_light_curve(candidate, rows, derived_period, packet_dir)

    return ZtfStats(
        status="ok",
        observations=len(rows),
        bands=tuple(bands),
        median_mag=median_mag,
        amplitude_mag=amplitude,
        derived_period_days=derived_period,
        period_power=peak_power,
        period_disagrees=period_disagrees,
        plot_path=str(plot_path) if plot_path else None,
        folded_plot_path=str(folded_plot_path) if folded_plot_path else None,
        note=gating_note,
    )


def estimate_period_from_rows(
    rows: list[dict[str, str]],
    period_min: float = PERIOD_MIN_DAYS,
    period_max: float = PERIOD_MAX_DAYS,
    freq_count: int = 5000,
) -> tuple[float | None, float | None, float | None]:
    times: list[float] = []
    mags: list[float] = []
    bands: list[str] = []
    for row in rows:
        mjd = _parse_float(row.get("mjd") or row.get("MJD") or row.get("hmjd") or row.get("HJD"))
        mag = _parse_float(row.get("mag") or row.get("MAG"))
        if mjd is None or mag is None:
            continue
        band = (row.get("filtercode") or row.get("band") or row.get("BAND") or "ZTF").strip()
        times.append(mjd)
        mags.append(mag)
        bands.append(band)
    return estimate_period(times, mags, bands, period_min=period_min, period_max=period_max, freq_count=freq_count)


def plot_folded_light_curve(
    candidate: Candidate,
    rows: list[dict[str, str]],
    period_days: float,
    packet_dir: Path,
) -> Path | None:
    points: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        mjd = _parse_float(row.get("mjd") or row.get("MJD") or row.get("hmjd") or row.get("HJD"))
        mag = _parse_float(row.get("mag") or row.get("MAG"))
        if mjd is None or mag is None:
            continue
        band = (row.get("filtercode") or row.get("band") or row.get("BAND") or "ZTF").strip()
        phase = (mjd / period_days) % 1.0
        points.setdefault(band, []).append((phase, mag))

    if not points:
        return None

    packet_dir.mkdir(parents=True, exist_ok=True)
    safe_name = safe_file_stem(candidate.target.name)
    path = packet_dir / f"{safe_name}_ztf_folded.png"
    plt.figure(figsize=(8, 4.5))
    for band, values in sorted(points.items()):
        x = [item[0] for item in values] + [item[0] + 1.0 for item in values]  # plot two cycles
        y = [item[1] for item in values] * 2
        plt.scatter(x, y, s=10, label=band, alpha=0.6)
    plt.gca().invert_yaxis()
    plt.xlabel(f"Phase (period = {period_days:.4f} d)")
    plt.ylabel("Magnitude")
    plt.title(f"{candidate.target.name} folded")
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    return path


def fetch_ztf_light_curve(ra_deg: float, dec_deg: float, band: str, config: ZtfConfig) -> list[dict[str, str]]:
    radius_deg = config.search_radius_arcsec / 3600.0
    params = {
        "POS": f"CIRCLE {ra_deg:.6f} {dec_deg:.6f} {radius_deg:.7f}",
        "BANDNAME": band,
        "BAD_CATFLAGS_MASK": str(config.bad_catflags_mask),
        "FORMAT": "csv",
    }
    url = f"{ZTF_LIGHT_CURVE_URL}?{urlencode(params)}"
    response = cached_get(ZTF_LIGHT_CURVE_URL, params=params, timeout=config.timeout_seconds, namespace="ztf")
    response.raise_for_status()
    return parse_light_curve_table(response.text)


def parse_light_curve_table(text: str) -> list[dict[str, str]]:
    stripped = text.lstrip()
    if not stripped:
        return []
    if "," in stripped.splitlines()[0]:
        return list(csv.DictReader(io.StringIO(text)))
    return parse_ipac_table(text)


def parse_ipac_table(text: str) -> list[dict[str, str]]:
    lines = [line.rstrip("\n") for line in text.splitlines() if line.strip()]
    header_index = next((index for index, line in enumerate(lines) if line.startswith("|")), None)
    if header_index is None:
        return []
    header = [part.strip() for part in lines[header_index].strip("|").split("|")]
    data_start = header_index + 4
    rows: list[dict[str, str]] = []
    for line in lines[data_start:]:
        if line.startswith("\\") or line.startswith("|"):
            continue
        parts = line.split()
        if len(parts) < len(header):
            continue
        rows.append(dict(zip(header, parts, strict=False)))
    return rows


def plot_light_curve(candidate: Candidate, rows: list[dict[str, str]], packet_dir: Path) -> Path | None:
    points: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        mjd = _parse_float(row.get("mjd") or row.get("MJD") or row.get("hmjd") or row.get("HJD"))
        mag = _parse_float(row.get("mag") or row.get("MAG"))
        if mjd is None or mag is None:
            continue
        band = (row.get("filtercode") or row.get("band") or row.get("BAND") or "ZTF").strip()
        points.setdefault(band, []).append((mjd, mag))

    if not points:
        return None

    packet_dir.mkdir(parents=True, exist_ok=True)
    safe_name = safe_file_stem(candidate.target.name)
    path = packet_dir / f"{safe_name}_ztf.png"
    plt.figure(figsize=(8, 4.5))
    for band, values in sorted(points.items()):
        values.sort()
        x = [item[0] for item in values]
        y = [item[1] for item in values]
        plt.scatter(x, y, s=10, label=band, alpha=0.75)
    plt.gca().invert_yaxis()
    plt.xlabel("MJD")
    plt.ylabel("Magnitude")
    plt.title(candidate.target.name)
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    return path


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * pct / 100.0
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def safe_file_stem(name: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in name).strip("_")[:80] or "target"


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
