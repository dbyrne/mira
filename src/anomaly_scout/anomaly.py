"""Anomaly assessment for a photometry session.

Compares the user's measured magnitude to (a) the VSX catalog range and
(b) recent AAVSO community observations, and decides whether the result
looks consistent, worth watching, or genuinely anomalous.

This is the loop-closer for the project's stated purpose: the pipeline
flags candidate variables that *might* be doing something interesting,
the user observes them, and now we surface a quantitative call-out about
whether the observation matches expectations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .models import VsxTarget
from .photometry import Observation


# A target observed within ±CATALOG_TOLERANCE_MAG of the catalog range is
# considered consistent. Photometry uncertainty for OSC sensors at short
# exposures is typically 0.1–0.2 mag, so 0.3 mag is the floor noise.
CATALOG_TOLERANCE_MAG = 0.3
# Minimum AAVSO recent observations needed to trust the baseline.
BASELINE_MIN_SAMPLES = 10
# Sigma cutoffs for the AAVSO-baseline deviation check.
WATCH_SIGMA = 2.0
ANOMALY_SIGMA = 3.0


@dataclass
class AnomalyAssessment:
    level: str  # "info", "watch", "anomaly"
    flags: list[str] = field(default_factory=list)
    session_median: float | None = None
    expected_min: float | None = None  # bright end of catalog range (smaller mag)
    expected_max: float | None = None  # faint end of catalog range (larger mag)
    baseline_median: float | None = None
    baseline_sigma: float | None = None
    baseline_n: int = 0
    deviation_sigma: float | None = None

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "flags": list(self.flags),
            "session_median": self.session_median,
            "expected_min": self.expected_min,
            "expected_max": self.expected_max,
            "baseline_median": self.baseline_median,
            "baseline_sigma": self.baseline_sigma,
            "baseline_n": self.baseline_n,
            "deviation_sigma": self.deviation_sigma,
        }


def assess_session_anomaly(
    observations: Iterable[Observation],
    vsx_target: VsxTarget | None,
    aavso_recent: list[tuple[float, float, str]] | None = None,
) -> AnomalyAssessment:
    """Score the session against catalog range and AAVSO baseline.

    Returns an AnomalyAssessment whose `level` rolls up to the strongest
    individual flag: any "anomaly" wins, otherwise any "watch", otherwise
    "info".
    """
    obs_list = [o for o in observations if o.julian_date is not None]
    if not obs_list:
        return AnomalyAssessment(level="info", flags=["no observations to assess"])

    mags = sorted(o.magnitude for o in obs_list)
    session_median = mags[len(mags) // 2]
    assessment = AnomalyAssessment(level="info", session_median=session_median)

    levels: list[str] = []

    if vsx_target is not None:
        bright = vsx_target.max_mag  # smaller magnitude = brighter
        faint = vsx_target.min_mag  # larger magnitude = fainter (or amplitude)
        if bright is not None:
            assessment.expected_min = bright
        if faint is not None and not vsx_target.min_is_amplitude:
            assessment.expected_max = faint
        cat_level, cat_flag = _check_catalog_range(
            session_median, bright, faint, vsx_target.min_is_amplitude
        )
        if cat_flag:
            assessment.flags.append(cat_flag)
            levels.append(cat_level)

    if aavso_recent and len(aavso_recent) >= BASELINE_MIN_SAMPLES:
        baseline_median, baseline_sigma = _baseline_median_and_sigma(aavso_recent)
        assessment.baseline_median = baseline_median
        assessment.baseline_sigma = baseline_sigma
        assessment.baseline_n = len(aavso_recent)
        if baseline_sigma is not None and baseline_sigma > 0:
            deviation = abs(session_median - baseline_median) / baseline_sigma
            assessment.deviation_sigma = deviation
            base_level, base_flag = _check_baseline_deviation(
                deviation, session_median, baseline_median, baseline_sigma
            )
            if base_flag:
                assessment.flags.append(base_flag)
                levels.append(base_level)

    if "anomaly" in levels:
        assessment.level = "anomaly"
    elif "watch" in levels:
        assessment.level = "watch"
    else:
        assessment.level = "info"
        if not assessment.flags:
            assessment.flags.append("Consistent with catalog range and AAVSO baseline.")
    return assessment


def _check_catalog_range(
    session_median: float,
    bright_mag: float | None,
    faint_mag: float | None,
    min_is_amplitude: bool,
) -> tuple[str, str | None]:
    if bright_mag is not None and session_median < bright_mag - CATALOG_TOLERANCE_MAG:
        delta = bright_mag - session_median
        return (
            "anomaly",
            f"Session median {session_median:.2f} is {delta:.2f} mag brighter "
            f"than the catalog maximum ({bright_mag:.2f}).",
        )
    if (
        faint_mag is not None
        and not min_is_amplitude
        and session_median > faint_mag + CATALOG_TOLERANCE_MAG
    ):
        delta = session_median - faint_mag
        return (
            "anomaly",
            f"Session median {session_median:.2f} is {delta:.2f} mag fainter "
            f"than the catalog minimum ({faint_mag:.2f}).",
        )
    return ("info", None)


def _check_baseline_deviation(
    deviation_sigma: float,
    session_median: float,
    baseline_median: float,
    baseline_sigma: float,
) -> tuple[str, str | None]:
    direction = "brighter" if session_median < baseline_median else "fainter"
    if deviation_sigma >= ANOMALY_SIGMA:
        return (
            "anomaly",
            f"Session median {session_median:.2f} is {deviation_sigma:.1f}σ {direction} "
            f"than the AAVSO baseline ({baseline_median:.2f} ± {baseline_sigma:.2f}).",
        )
    if deviation_sigma >= WATCH_SIGMA:
        return (
            "watch",
            f"Session median {session_median:.2f} is {deviation_sigma:.1f}σ {direction} "
            f"than the AAVSO baseline ({baseline_median:.2f} ± {baseline_sigma:.2f}).",
        )
    return ("info", None)


def _baseline_median_and_sigma(
    samples: list[tuple[float, float, str]],
) -> tuple[float, float | None]:
    """Robust median and MAD-based sigma estimate of the magnitude column."""
    mags = sorted(s[1] for s in samples)
    median = mags[len(mags) // 2]
    deviations = sorted(abs(m - median) for m in mags)
    mad = deviations[len(deviations) // 2]
    sigma = mad * 1.4826 if mad > 0 else None
    return median, sigma
