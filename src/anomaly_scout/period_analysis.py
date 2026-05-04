from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.signal import lombscargle

PERIOD_MIN_DAYS = 0.1
PERIOD_MAX_DAYS = 1000.0
PERIOD_FREQ_COUNT = 5000
PERIOD_AGREEMENT_TOLERANCE = 0.05  # log10 ratio: ~12% tolerance, plus 1/2x and 2x harmonics
PERIOD_MIN_OBSERVATIONS = 20


def estimate_period(
    times: Sequence[float],
    mags: Sequence[float],
    bands: Sequence[str],
    period_min: float = PERIOD_MIN_DAYS,
    period_max: float = PERIOD_MAX_DAYS,
    freq_count: int = PERIOD_FREQ_COUNT,
) -> tuple[float | None, float | None, float | None]:
    """Returns (derived_period_days, peak_power, time_span_days).

    Each band is centered on its own median before pooling, so the resulting
    Lomb-Scargle is robust to per-band zero-point offsets.
    """
    if not times:
        return None, None, None

    by_band: dict[str, list[tuple[float, float]]] = {}
    for t, m, b in zip(times, mags, bands):
        by_band.setdefault(b or "default", []).append((float(t), float(m)))

    pooled_times: list[float] = []
    pooled_mags: list[float] = []
    for band_values in by_band.values():
        if len(band_values) < 5:
            continue
        band_mags = [v[1] for v in band_values]
        median_band_mag = sorted(band_mags)[len(band_mags) // 2]
        for t, m in band_values:
            pooled_times.append(t)
            pooled_mags.append(m - median_band_mag)

    if len(pooled_times) < PERIOD_MIN_OBSERVATIONS:
        return None, None, None

    time_arr = np.asarray(pooled_times, dtype=float)
    mag_arr = np.asarray(pooled_mags, dtype=float)
    span = float(time_arr.max() - time_arr.min())
    effective_period_max = min(period_max, span / 2.0) if span > 0 else period_max
    if effective_period_max <= period_min:
        return None, None, span
    freqs = np.linspace(1.0 / effective_period_max, 1.0 / period_min, freq_count)
    omegas = 2.0 * np.pi * freqs
    power = lombscargle(time_arr, mag_arr, omegas, normalize=True)
    peak_idx = int(np.argmax(power))
    return float(1.0 / freqs[peak_idx]), float(power[peak_idx]), span


def period_disagreement(
    catalog_period: float | None,
    derived_period: float | None,
    tolerance: float = PERIOD_AGREEMENT_TOLERANCE,
) -> bool | None:
    if catalog_period is None or catalog_period <= 0:
        return None
    if derived_period is None or derived_period <= 0:
        return None
    log_ratio = abs(math.log10(derived_period / catalog_period))
    if log_ratio < tolerance:
        return False
    for alias_factor in (0.5, 2.0):
        log_alias = abs(math.log10(derived_period * alias_factor / catalog_period))
        if log_alias < tolerance:
            return False
    return True


def assess_period_disagreement(
    catalog_period: float | None,
    derived_period: float | None,
    peak_power: float | None,
    time_span_days: float | None,
    period_min: float,
    period_max: float,
    min_peak_power: float,
    tolerance: float = PERIOD_AGREEMENT_TOLERANCE,
) -> tuple[bool | None, str]:
    """Returns (disagrees, gating_note). disagrees is None when the comparison
    can't be made (period out of search range, peak too weak, etc)."""
    if catalog_period is None or catalog_period <= 0:
        return None, ""
    if derived_period is None or derived_period <= 0:
        return None, "Lomb-Scargle did not return a period"
    effective_max = period_max
    if time_span_days is not None and time_span_days > 0:
        effective_max = min(effective_max, time_span_days / 2.0)
    if catalog_period < period_min:
        return None, (
            f"catalog period {catalog_period:.4f} d is below the searched minimum "
            f"({period_min:.2f} d); cannot assess agreement"
        )
    if catalog_period > effective_max:
        return None, (
            f"catalog period {catalog_period:.2f} d exceeds the data baseline / 2 "
            f"({effective_max:.2f} d); cannot assess agreement"
        )
    if peak_power is None or peak_power < min_peak_power:
        return None, (
            f"Lomb-Scargle peak power {peak_power if peak_power is not None else 0.0:.3f} "
            f"is below the confidence threshold {min_peak_power}; period not trusted"
        )
    return period_disagreement(catalog_period, derived_period, tolerance=tolerance), ""
