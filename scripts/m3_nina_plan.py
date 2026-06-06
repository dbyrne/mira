"""One-off: observability check + NINA Target Scheduler plan for M3.

M3 is a globular cluster, not a VSX variable, so `mira tonight` will
never schedule it. This builds the same NINA-importable CSV + a phone
plan for it directly, reusing Mira's own format helpers.
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from astropy.coordinates import EarthLocation, SkyCoord, AltAz, get_sun
from astropy.time import Time
import astropy.units as u

from mira.session_plan import (
    ra_to_target_scheduler_hms,
    dec_to_target_scheduler_dms,
)

# --- M3 (NGC 5272), J2000 ---
M3 = SkyCoord("13h42m11.62s", "+28d22m38.2s", frame="icrs")
NAME = "M3 (NGC 5272)"

# --- Jersey City / s30_pro_jc.yaml ---
LAT, LON = 40.7178, -74.0431
TZ = ZoneInfo("America/New_York")
ALT_FLOOR = 45.0          # observing_window.min_altitude_deg
SUN_MAX = -12.0           # max_sun_altitude_deg (nautical dark)
WIN_START_H, WIN_END_H = 20, 1   # local window 20:00 -> 01:00

site = EarthLocation(lat=LAT * u.deg, lon=LON * u.deg, height=10 * u.m)

today = datetime(2026, 5, 16, tzinfo=TZ)
start = today.replace(hour=WIN_START_H, minute=0, second=0, microsecond=0)
end = (today + timedelta(days=1)).replace(hour=WIN_END_H, minute=0,
                                          second=0, microsecond=0)

step = timedelta(minutes=10)
rows = []
t = start
while t <= end:
    at = Time(t.astimezone(ZoneInfo("UTC")))
    aa = AltAz(obstime=at, location=site)
    alt = float(M3.transform_to(aa).alt.deg)
    sun_alt = float(get_sun(at).transform_to(aa).alt.deg)
    rows.append((t, alt, sun_alt))
    t += step

dark_good = [(tt, a) for tt, a, s in rows if s <= SUN_MAX and a >= ALT_FLOOR]
print(f"M3 from Jersey City, night of {today:%Y-%m-%d}")
print(f"  RA/Dec  : {ra_to_target_scheduler_hms(M3.ra.deg)}  "
      f"{dec_to_target_scheduler_dms(M3.dec.deg)}")
print(f"  altitude floor {ALT_FLOOR:.0f}deg, sun <= {SUN_MAX:.0f}deg\n")
print("  local      alt   sun")
for tt, a, s in rows:
    flag = " <= observable" if (s <= SUN_MAX and a >= ALT_FLOOR) else ""
    print(f"  {tt:%H:%M}   {a:5.1f} {s:6.1f}{flag}")

if dark_good:
    w0, w1 = dark_good[0][0], dark_good[-1][0]
    peak_t, peak_a = max(((tt, a) for tt, a, s in rows
                          if s <= SUN_MAX), key=lambda x: x[1])
    mins = int((w1 - w0).total_seconds() // 60) + 10
    print(f"\n  Observable (dark + above floor): "
          f"{w0:%H:%M} -> {w1:%H:%M} local  (~{mins} min)")
    print(f"  Transit/peak in window: {peak_t:%H:%M} at {peak_a:.1f}deg")
else:
    print("\n  NOT observable above the 45deg floor during darkness tonight.")
    w0 = w1 = peak_t = None
    peak_a = mins = 0

# --- exposure plan ---
# M3 is an extended cluster (integ. mag ~6.2). Mira's recommended_exposure_plan
# is tuned for point-source variable photometry and would pick 5s; for a
# globular you want to resolve members + reach the field, so go longer.
EXP_S, FRAMES = 20, 90          # 30 min, dither every 10
out_dir = Path("output/m3_nina")
out_dir.mkdir(parents=True, exist_ok=True)

csv_path = out_dir / "nina_targets.csv"
with csv_path.open("w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["Type", "Name", "Ra", "Dec",
                                       "Rotation", "ROI"])
    w.writeheader()
    w.writerow({
        "Type": "Globular Cluster",
        "Name": NAME,
        "Ra": ra_to_target_scheduler_hms(M3.ra.deg),
        "Dec": dec_to_target_scheduler_dms(M3.dec.deg),
        "Rotation": 0,
        "ROI": 100,
    })

plan = out_dir / "m3_plan.md"
win_txt = (f"{w0:%H:%M}–{w1:%H:%M} local (~{mins} min above {ALT_FLOOR:.0f}°, "
           f"transit {peak_t:%H:%M} @ {peak_a:.0f}°)"
           if dark_good else
           f"NOT above {ALT_FLOOR:.0f}° during darkness tonight")
plan.write_text(f"""# M3 — NINA session plan (night of {today:%Y-%m-%d})

**Target:** {NAME} — globular cluster, NGC 5272
**Coordinates (J2000):** {ra_to_target_scheduler_hms(M3.ra.deg)}  {dec_to_target_scheduler_dms(M3.dec.deg)}
**Site:** Jersey City (s30_pro_jc profile), altitude floor {ALT_FLOOR:.0f}°

## Observability tonight
{win_txt}

(Altitude + nautical-dark only; the balcony horizon mask in
`config/horizon_balcony_jc.yaml` is NOT applied here — eyeball the
real horizon for the azimuth M3 sits at during the window.)

## Capture recipe (S30 Pro OSC, EQ wedge)
- Exposure: **{EXP_S} s**, **{FRAMES} frames** (~{EXP_S*FRAMES//60} min total)
- Binning 1×1, dither every 10 frames
- **Plate-solve & sync before capture** (Center on Target) — required so
  the FITS carry a WCS. Without it the photometry pipeline bails.
- Why 20 s and not Mira's 5 s default: M3 is an extended cluster, not a
  point source. Longer subs resolve members and reach the field; 5 s
  would only catch the bright core.

## Steps
1. NINA → Target Scheduler → Targets → Import CSV →
   `output/m3_nina/nina_targets.csv`, project **Mira**,
   template **S30 Pro OSC** (override exposure to {EXP_S} s).
2. Run the Target Scheduler sequence. Confirm a plate solve succeeds
   before the first light frame.
3. FITS land in `captures/M3/<date>/`. These are real linear FITS with
   WCS — unlike the phone JPEGs, these stack properly and prove the
   tracking/polar-alignment fix.

## Note
M3 is a globular cluster — there's no AAVSO single-star photometry
target here, so `mira submit` doesn't apply. This run is for a proper
stacked image + a polar-alignment check (the phone subs showed ~150 px
drift over 39 s; verify that's gone with NINA-logged guiding/plate solves).
""", encoding="utf-8")

print(f"\nWrote {csv_path}")
print(f"Wrote {plan}")
