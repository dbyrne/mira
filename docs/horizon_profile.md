# Horizon Profile

A **horizon profile** describes which directions of your sky are blocked
by trees, buildings, fences, or terrain. The scheduler uses it to avoid
recommending targets whose best moment puts them behind an obstruction
that the standard altitude floor wouldn't catch.

You map this once for each observing location. It takes about 20
minutes the first time, after dark, with a phone.

---

## Why this matters

The default site config has a single `min_altitude_deg` floor — say, 45°
in Jersey City — and treats the entire sky above it as observable. In
practice, your sky has notches:

```
                        (zenith)
                          90°
                         /  \
        +60°  ╱╲────────╱    ╲────────╱╲       NE chimney
              ╲ ╲                    ╱ ╲
        +45°───────────●─tree────●──────────  global floor
              ╲                       ╲
        +30°──╲                        ╲────  SW tree
              ╲                         ╲
              ╲                          ╲
        +15°──╲                           ╲
              ╲                            ╲
         0°───╲────────────────────────────╲  horizon

         N         E         S         W         N
```

A target whose **peak altitude** is 60° but whose **best moment** puts
it at azimuth 50° at altitude 50° is, in this picture, behind your
chimney for the entire window. The flat-floor scheduler thinks it's
observable; it's not.

A horizon profile fixes this by checking both `target_alt > global_floor`
**and** `target_alt > horizon_at_az(target_az)` per sample.

---

## What you'll need

- **Stellarium Mobile** (free version is enough). Other AR
  astronomy apps work too; the procedure is the same.
- A phone with **compass + tilt sensors** — almost any modern phone.
- About **20 minutes after dark**, at the spot where your scope will sit.

---

## The procedure

### 1. Set up at the imaging spot

Stand exactly where the scope's tripod will go. If the scope is already
set up, hold the phone next to the optical tube (not on it — magnets
in the phone can offset the compass).

### 2. Calibrate the compass

Phones drift. Calibrate by tracing a figure-8 in the air with the
phone, several times. Skipping this gives systematic azimuth errors of
10–20°, which will misalign your entire profile.

A quick way to verify: open Stellarium, find a bright known object
(the Moon, Vega, Polaris). The on-screen label should sit on the
real object. If it's off by more than ~2°, recalibrate.

### 3. Enable AR mode

In Stellarium Mobile, find the **camera/aperture icon** (usually at
the bottom center of the screen). Tap it. The camera turns on and the
celestial grid is drawn over what you can see — stars, constellations,
azimuth labels at the top, altitude labels on the sides.

> ⚠️ **Different from "look at sky" mode.** Pure simulation mode shows
> a generic stock landscape at the bottom, not your actual surroundings.
> If you don't see the camera feed behind the stars, you're not in AR
> mode.

### 4. Walk the perimeter

Aim the phone at each obstruction edge — top of every tree, each roof
corner, the railing top. For each, the screen shows az/alt where the
crosshair (or center) sits.

**Aim for 8–15 well-chosen points** that capture the silhouette:

- Dense clusters around tree gaps (where a small az change matters)
- Sparse spacing where the horizon is clean (one point is enough to
  define a stretch)
- Always the **top edge** of obstructions, not their bases

A typical balcony or backyard takes 8–25 points. More than 50 is
probably overkill at first; you can refine after observing.

### 5. Record the points

Capture the points however works for you:

- **Screenshot every aim**, then read az/alt off the photos later
- **Voice memo**: "twenty-five degrees, ten degrees altitude"
- **Notebook**: just the numbers

The author of this project captured ~13 screenshots covering the full
360° perimeter in about 15 minutes. See `house_photos/` in this repo
for the actual screenshots that produced `config/horizon_balcony_jc.yaml`.

---

## Reading az/alt from screenshots

If you screenshot Stellarium AR rather than read live, you'll need to
extract az/alt from the overlaid grid afterward.

The grid Stellarium draws:

- **Azimuth labels** appear along the top edge of the visible sky
  region. Spacing is typically 5° between minor lines and 15°/30°
  between major labels. North = 0/360°, East = 90°, South = 180°,
  West = 270°.
- **Altitude labels** appear on the left and right edges. Spacing is
  typically 5° or 10° between lines, labeled at 0°, +10°, +20°, etc.

For each obstruction edge in the photo:

1. Trace down the closest vertical (azimuth) gridline; read off the
   azimuth at the top.
2. Trace across the closest horizontal (altitude) gridline; read off
   the altitude on the side.
3. Round to the nearest 5° in azimuth and 2-3° in altitude. Don't
   try to be more precise than that — the AR overlay isn't.

---

## YAML format

Save your readings to `config/horizon_<yoursite>.yaml`. The format:

```yaml
# A descriptive header is helpful for later you.
site: "Backyard, Big Sur"
captured_at: "2026-05-07"

# (azimuth_deg, altitude_deg) pairs. Order doesn't matter — the loader
# sorts them. Azimuth: 0 = North, increasing clockwise (E=90, S=180,
# W=270). Altitude: 0 = horizon, 90 = zenith.
points:
  # North end: clean
  - {az:   0, alt:  5}
  - {az:  30, alt: 15}

  # NE: house
  - {az:  50, alt: 35}
  - {az:  75, alt: 25}

  # ... etc, walking clockwise around the horizon ...

  # Back to North
  - {az: 350, alt:  8}
  - {az: 360, alt:  5}   # closes the loop, can match az:0
```

**Conventions:**

- Azimuth in degrees (0 = N, increases clockwise). Out-of-range values
  are normalized via mod 360°, but stick to [0, 360] for clarity.
- Altitude in degrees (0 = horizon, 90 = zenith). Must be in [0, 90].
- Order doesn't matter — the loader sorts by azimuth.
- The system **linearly interpolates** between adjacent points and
  wraps continuously through 0°/360°.

> 💡 **Conservative is fine.** When in doubt about an obstruction's
> exact top, write down a higher number. Better to skip a marginal
> target than chase one behind a branch.

---

## Wire it up

In your site config (e.g., `config/<yoursite>.yaml`), add the
`horizon_profile_path` line:

```yaml
sites:
  - name: My Backyard
    horizon_profile_path: config/horizon_<yoursite>.yaml
    observer:
      latitude_deg: 37.7749
      longitude_deg: -122.4194
      timezone: America/Los_Angeles
    observing_window:
      ...
    filters:
      ...
```

Re-run `mira tonight --config config/<yoursite>.yaml --hours 4`.
The schedule will silently drop targets that were behind your
obstructions. New southern or low-altitude targets may appear that
were previously rejected by the flat altitude floor.

---

## Verifying the profile

Before relying on it, check the profile against a few known
positions. From the project root:

```python
from datetime import datetime, timezone
from pathlib import Path
from mira.observability import altitude_deg, azimuth_deg
from mira.horizon import load_horizon_profile

now_utc = datetime.now(timezone.utc)
my_lat, my_lon = 37.7749, -122.4194
profile = load_horizon_profile(Path("config/horizon_<yoursite>.yaml"))

# Five test stars covering most of the sky
for name, ra, dec in [
    ("Polaris",   37.95, 89.26),
    ("Vega",     279.23, 38.78),
    ("Arcturus", 213.92, 19.18),
    ("Spica",    201.30, -11.16),
    ("Procyon",  114.83,  5.22),
]:
    alt = altitude_deg(ra, dec, now_utc, my_lat, my_lon)
    az = azimuth_deg(ra, dec, now_utc, my_lat, my_lon)
    floor = profile.min_altitude_at(az)
    if alt < 0:
        verdict = "(below horizon)"
    elif alt >= floor:
        verdict = f"VISIBLE (+{alt - floor:.1f}°)"
    else:
        verdict = f"BLOCKED (-{floor - alt:.1f}°)"
    print(f"{name:<12} az {az:>6.1f}° alt {alt:>6.1f}°  floor {floor:>6.1f}°  {verdict}")
```

Then in Stellarium, point AR mode at each star. If the system says
**VISIBLE**, you should see open sky around that star. If the system
says **BLOCKED**, you should see your obstruction.

The most diagnostic pair is **one star the system says is blocked
behind a known feature** (your house, your tree) and **one star the
system says is visible in a clean direction**. If those match what
you see live, the profile is correctly oriented.

If anything contradicts:

- **Blocked but you can see open sky there**: most likely your compass
  was poorly calibrated when you mapped, or the AR mode azimuth
  convention differs (some apps measure from S not N). Recalibrate
  and re-map a few points.
- **Visible but you see a tree**: you missed that obstruction. Add a
  point.

---

## Refining over time

You don't need a perfect profile on day one. Iterate:

1. **Observe with the current profile**.
2. Note any target the schedule said was visible but you couldn't
   actually photometer (clouded out, behind a tree you missed).
3. Add or adjust horizon points for the offending direction.
4. Commit the YAML change.

After 5–10 sessions, your profile will reflect your real sky.

---

## A real example

This project ships with `config/horizon_balcony_jc.yaml`, captured from
a Jersey City balcony on 2026-05-06 via 13 Stellarium AR screenshots.
The 39-point profile captures:

- A **clean east window** around azimuth 100° (down to +10°)
- A **surprising clean south window** around 195° (down to +5°)
- A **chimney peak** at azimuth 50°, +45° altitude (the worst NE block)
- A **tall tree at azimuth 220°, +40° altitude** (the worst SW block)
- A **second clean gap** between trees at WSW around 240°

The screenshots are checked in under `house_photos/` if you want to
see what real AR captures look like before you do your own.
