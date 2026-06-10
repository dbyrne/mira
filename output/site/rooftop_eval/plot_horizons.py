#!/usr/bin/env python
"""Polar overlay of balcony vs proposed-rooftop horizon silhouettes.
Shaded = blocked sky (must be ABOVE the line to observe). The gap between
the two fills is the sky the rooftop pier opens up.
"""
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from mira.horizon import load_horizon_profile

BAL = load_horizon_profile(Path("config/horizon_balcony_jc.yaml"))
ROOF = load_horizon_profile(Path("config/horizon_rooftop_jc.yaml"))

az = np.linspace(0, 360, 721)
theta = np.radians(az)

def alts(prof):
    return np.array([prof.min_altitude_at(a) for a in az])

fig = plt.figure(figsize=(9, 9))
ax = fig.add_subplot(111, projection="polar")
ax.set_theta_zero_location("N")
ax.set_theta_direction(-1)                       # clockwise: E=90 right side
# radial = altitude, but invert so horizon (0) is the OUTER rim, zenith center.
ax.set_rlim(90, 0)
ax.set_rticks([0, 15, 30, 45, 60, 75])
ax.set_rlabel_position(135)

ab, ar = alts(BAL), alts(ROOF)
# Blocked sky = from the silhouette line out to the horizon (alt 0 = rim).
ax.fill_between(theta, ab, 0, color="firebrick", alpha=0.30, label="balcony blocked")
ax.fill_between(theta, ar, 0, color="seagreen", alpha=0.35, label="rooftop blocked")
ax.plot(theta, ab, color="firebrick", lw=1.6)
ax.plot(theta, ar, color="seagreen", lw=1.6)
ax.axhline  # noqa
# 45-deg science-floor ring for reference
ax.plot(theta, np.full_like(theta, 45), color="navy", lw=1.0, ls="--", alpha=0.7)

ax.set_xticks(np.radians([0, 45, 90, 135, 180, 225, 270, 315]))
ax.set_xticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW"])
ax.set_title("JC horizon: balcony (red) vs proposed rooftop (green)\n"
             "shaded = blocked; dashed navy = 45deg science floor",
             pad=20)
ax.legend(loc="lower right", bbox_to_anchor=(1.12, -0.05))

# annotate the two headline features
ax.text(np.radians(50), 30, "house wall\n+47 GONE",
        color="firebrick", fontsize=9, ha="center", va="center")
ax.text(np.radians(220), 20, "SW tree\n+34 stays",
        color="seagreen", fontsize=9, ha="center", va="center")

out = Path("output/rooftop_eval/horizon_compare.png")
fig.savefig(out, dpi=130, bbox_inches="tight")
print("wrote", out)
