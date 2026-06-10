"""Catskills trip ephemeris: nights of Sat Jun 13 and Sat Jun 20, 2026 (EDT).

Astro-dark window (sun < -18), moon illum + rise/set, hourly altitude tracks
for the candidate targets. Low-precision (get_body) is plenty for planning.
"""
import numpy as np
from astropy.time import Time
from astropy.coordinates import EarthLocation, AltAz, get_body, get_sun, SkyCoord
import astropy.units as u

site = EarthLocation(lat=42.1 * u.deg, lon=-74.4 * u.deg, height=500 * u.m)
EDT = -4 / 24  # days

TARGETS = {
    "IC1396 (Elephant Trunk)": (324.78, 57.5),
    "NGC7023 Iris": (315.40, 68.16),
    "M101": (210.80, 54.35),
    "NGC7000 (NA neb)": (314.70, 44.50),
    "Cocoon IC5146": (328.35, 47.27),
    "M16 Eagle": (274.70, -13.78),
}

def night(date_evening):  # 'YYYY-MM-DD' local evening
    # scan 18:00 EDT -> 06:00 EDT next day, 5-min grid
    t0 = Time(f"{date_evening} 18:00:00") - EDT  # UT
    grid = t0 + np.arange(0, 12 * 60 + 1, 5) / (24 * 60)
    aa = AltAz(obstime=grid, location=site)
    sun_alt = get_sun(grid).transform_to(aa).alt.deg
    moon = get_body("moon", grid, location=site)
    moon_alt = moon.transform_to(aa).alt.deg

    def local(t):
        return (t + EDT).iso[11:16]

    dark = sun_alt < -18
    if dark.any():
        i0, i1 = np.argmax(dark), len(dark) - 1 - np.argmax(dark[::-1])
        print(f"  astro dark: {local(grid[i0])} -> {local(grid[i1])} EDT")
    # moon illumination at local midnight
    tm = t0 + 6 / 24
    m, s = get_body("moon", tm, location=site), get_sun(tm)
    elong = m.separation(s)
    illum = (1 - np.cos(elong.rad)) / 2 * 100
    print(f"  moon: {illum:.0f}% illuminated (at local midnight)")
    # moon rise/set crossings
    for j in range(1, len(grid)):
        if moon_alt[j - 1] < 0 <= moon_alt[j]:
            print(f"  moonrise: {local(grid[j])} EDT")
        if moon_alt[j - 1] >= 0 > moon_alt[j]:
            print(f"  moonset:  {local(grid[j])} EDT")
    if (moon_alt < 0).all():
        print("  moon below horizon all night")

    # hourly altitude table 22:00 -> 04:00 EDT
    hrs = t0 + np.arange(4, 10.01, 1) / 24
    aa_h = AltAz(obstime=hrs, location=site)
    hdr = "  " + f"{'target':26s}" + "".join(f"{local(h):>7s}" for h in hrs)
    print(hdr)
    for name, (ra, dec) in TARGETS.items():
        c = SkyCoord(ra * u.deg, dec * u.deg)
        alts = c.transform_to(aa_h).alt.deg
        print("  " + f"{name:26s}" + "".join(f"{a:7.0f}" for a in alts))
    # moon row
    moon_h = get_body("moon", hrs, location=site).transform_to(aa_h).alt.deg
    print("  " + f"{'(moon)':26s}" + "".join(f"{a:7.0f}" for a in moon_h))

for d in ["2026-06-13", "2026-06-20"]:
    print(f"\n=== Night of Sat {d} ===")
    night(d)
