#!/usr/bin/env python
"""Balcony vs proposed-rooftop horizon: how much observable sky does the
rooftop pier actually buy? Runs Mira's own observability engine for a target
list against each horizon profile, at a LOW global floor (so the per-azimuth
horizon mask governs, not the 45-deg science floor) with the moon relaxed
(identical for both -> the delta is PURE horizon geometry).

Run:  python output/rooftop_eval/compare_horizons.py
"""
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mira.config import (
    ObserverConfig, WindowConfig, FilterConfig, SiteConfig,
)
from mira.horizon import load_horizon_profile
from mira.observability import evaluate_observability_at_coords, azimuth_deg
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

JC = ObserverConfig(latitude_deg=40.7178, longitude_deg=-74.0431,
                    timezone="America/New_York")

# Wide full-night window, low floor, moon relaxed -> isolate horizon geometry.
WINDOW = WindowConfig(
    start_hour_local=21, end_hour_local=4, nights=1, sample_minutes=15,
    min_altitude_deg=15.0,           # low: let the horizon mask govern
    max_sun_altitude_deg=-12.0,
    max_moon_altitude_deg=90.0, max_moon_illumination=1.0,
    min_moon_separation_deg=0.0,     # relaxed: identical both sides
)
FILT = FilterConfig(0, 0, 0, 99, 0)

BALCONY = load_horizon_profile(Path("config/horizon_balcony_jc.yaml"))
ROOFTOP = load_horizon_profile(Path("config/horizon_rooftop_jc.yaml"))

def site(name, horizon):
    return SiteConfig(name=name, observer=JC, observing_window=WINDOW,
                      filters=FILT, horizon_profile=horizon)

S_BAL = site("balcony", BALCONY)
S_ROOF = site("rooftop", ROOFTOP)

# (name, RA deg, Dec deg, note) — the targets actually in play.
TARGETS = [
    ("Veil (NGC6960)",      311.78,  30.72, "Cygnus, SW-setting"),
    ("North America 7000",  314.75,  44.31, "Cygnus, high"),
    ("Crescent (6888)",     303.00,  38.35, "Cygnus"),
    ("Tulip (Sh2-101)",     301.65,  35.27, "Cygnus"),
    ("M57 Ring",            283.40,  33.03, "Lyra"),
    ("M27 Dumbbell",        299.90,  22.72, "Vulpecula"),
    ("M13 globular",        250.42,  36.46, "Hercules, overhead"),
    ("M51 Whirlpool",       202.47,  47.20, "CVn, NW-setting"),
    ("M81/M82",             148.89,  69.07, "circumpolar-ish N"),
    ("M8 Lagoon",           270.92, -24.38, "low S, Sgr"),
    ("M16 Eagle",           274.70, -13.78, "low S, Ser"),
    ("M22 globular",        279.10, -23.90, "low S, Sgr"),
]

def az_at_best(ra, dec, obs):
    if obs.best_local_time is None:
        return None
    utc = obs.best_local_time.astimezone(timezone.utc)
    return azimuth_deg(ra, dec, utc, JC.latitude_deg, JC.longitude_deg)

def run(d):
    print(f"\n{'='*78}\n  NIGHT OF {d}   (floor 15deg, moon relaxed -> pure horizon delta)\n{'='*78}")
    print(f"{'target':<20}{'maxAlt':>7}{'az@pk':>7}  {'balcony min':>12}{'rooftop min':>12}{'delta':>8}")
    print("-"*78)
    for name, ra, dec, note in TARGETS:
        ob = evaluate_observability_at_coords(ra, dec, S_BAL, start_date=d)
        orf = evaluate_observability_at_coords(ra, dec, S_ROOF, start_date=d)
        az = az_at_best(ra, dec, ob if ob.best_local_time else orf)
        azs = f"{az:5.0f}" if az is not None else "  -- "
        dmin = orf.minutes_above_minimum - ob.minutes_above_minimum
        flag = "  <-- gain" if dmin >= 30 else ""
        print(f"{name:<20}{ob.max_altitude_deg:6.1f} {azs:>6}  "
              f"{ob.minutes_above_minimum:10d}m {orf.minutes_above_minimum:10d}m "
              f"{dmin:+6d}m{flag}")
        print(f"{'':<20}{note}")

if __name__ == "__main__":
    run(date(2026, 6, 7))     # tonight
    run(date(2026, 8, 15))    # Cygnus peak season
