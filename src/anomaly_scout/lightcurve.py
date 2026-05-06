"""Light-curve plots for the user's photometry sessions.

Generates two PNGs in the target's captures directory:
- lightcurve.png: tonight's measurements (JD vs mag, with error bars)
- lightcurve_folded.png: phase-folded against the catalog period (if known)

Both optionally overlay recent AAVSO community observations for context, so
the user can see at a glance whether their points land where the rest of
AAVSO has been seeing the target.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .photometry import Observation


def plot_session_light_curve(
    observations: Iterable[Observation],
    target_name: str,
    output_path: Path,
    aavso_recent: list[tuple[float, float, str]] | None = None,
    prior_sessions: list[tuple[float, float, str]] | None = None,
) -> Path | None:
    """Plot the night's observations as JD vs magnitude with error bars,
    optionally overlaid on (a) recent AAVSO submissions and (b) the user's
    own prior sessions of this target. Returns the path written, or None
    if there's nothing plottable."""
    obs_list = [o for o in observations if o.julian_date is not None]
    if not obs_list:
        return None
    jds = [o.julian_date for o in obs_list]
    mags = [o.magnitude for o in obs_list]
    errors = [o.magnitude_error for o in obs_list]
    band = obs_list[0].band

    fig, ax = plt.subplots(figsize=(8, 4.5))
    if aavso_recent:
        ax.scatter(
            [s[0] for s in aavso_recent],
            [s[1] for s in aavso_recent],
            color="gray",
            alpha=0.45,
            s=18,
            label=f"AAVSO recent ({len(aavso_recent)})",
        )
    if prior_sessions:
        ax.scatter(
            [s[0] for s in prior_sessions],
            [s[1] for s in prior_sessions],
            color="tab:orange",
            alpha=0.7,
            s=22,
            marker="s",
            label=f"Your prior sessions ({len(prior_sessions)})",
        )
    ax.errorbar(
        jds,
        mags,
        yerr=errors,
        fmt="o",
        color="tab:blue",
        markersize=6,
        capsize=3,
        label=f"This session ({len(obs_list)}× {band})",
    )
    ax.invert_yaxis()
    ax.set_xlabel("Julian Date")
    ax.set_ylabel("Magnitude")
    ax.set_title(f"{target_name} — light curve")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return output_path


def plot_phase_folded(
    observations: Iterable[Observation],
    target_name: str,
    period_days: float,
    output_path: Path,
    aavso_recent: list[tuple[float, float, str]] | None = None,
    prior_sessions: list[tuple[float, float, str]] | None = None,
) -> Path | None:
    """Plot tonight's points + AAVSO history + user's prior sessions
    phase-folded at period_days. Two cycles drawn for visual continuity.
    Returns the path or None."""
    obs_list = [o for o in observations if o.julian_date is not None]
    if not obs_list or period_days <= 0:
        return None
    jds = [o.julian_date for o in obs_list]
    mags = [o.magnitude for o in obs_list]
    errors = [o.magnitude_error for o in obs_list]
    epoch = sum(jds) / len(jds)
    session_phases = [((jd - epoch) / period_days) % 1.0 for jd in jds]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    if aavso_recent:
        aavso_phases = [((s[0] - epoch) / period_days) % 1.0 for s in aavso_recent]
        for offset in (0.0, 1.0):
            ax.scatter(
                [p + offset for p in aavso_phases],
                [s[1] for s in aavso_recent],
                color="gray",
                alpha=0.35,
                s=18,
                label=f"AAVSO recent ({len(aavso_recent)})" if offset == 0.0 else None,
            )
    if prior_sessions:
        prior_phases = [((s[0] - epoch) / period_days) % 1.0 for s in prior_sessions]
        for offset in (0.0, 1.0):
            ax.scatter(
                [p + offset for p in prior_phases],
                [s[1] for s in prior_sessions],
                color="tab:orange",
                alpha=0.7,
                s=22,
                marker="s",
                label=f"Your prior sessions ({len(prior_sessions)})" if offset == 0.0 else None,
            )
    for offset in (0.0, 1.0):
        ax.errorbar(
            [p + offset for p in session_phases],
            mags,
            yerr=errors,
            fmt="o",
            color="tab:blue",
            markersize=6,
            capsize=3,
            label=f"This session ({len(obs_list)})" if offset == 0.0 else None,
        )
    ax.invert_yaxis()
    ax.set_xlabel(f"Phase (period = {period_days:.4f} d)")
    ax.set_ylabel("Magnitude")
    ax.set_title(f"{target_name} — phase folded")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.2)
    ax.set_xlim(0, 2)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120)
    plt.close(fig)
    return output_path
