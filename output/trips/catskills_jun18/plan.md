# Catskills dark-site trip — June 18, 2026

**Rig:** ZWO Seestar S30 Pro (LP dual-band), no rotator. FOV 2.196° (E–W, short)
× 3.904° (N–S, long) @ 3.66″/px. Native orientation: **long axis ≈ N–S** (~4°
tilt), confirmed from the M81 frame.

**Site:** Catskills (~lat 42.1, lon −74.4). Confirm a clear **southern horizon**
if you want the low Milky Way targets another night.

## Conditions (Jun 18 → 19)
- **Moon:** 21% waxing crescent, **sets ~23:50 EDT** (thin, low in the W — on LP
  emission targets in the E it's irrelevant; no need to wait for moonset).
- **Astro dark:** ~22:40 → 03:35 EDT.
- **Moonless dark:** 23:50 → 03:35 EDT (~3h45m).
- Cygnus rides overhead all the back half of the night.

## PRIORITY — full-night Veil 2-panel mosaic

The Cygnus Loop is ~3° wide E–W; the S30's 3.9° N–S long axis covers its height
in one frame, so split into **two panels in RA** (no rotator needed — the loop's
wide axis is E–W, matching the S30's short axis split). ~22% overlap.

| Panel | RA | Dec | Covers |
| --- | --- | --- | --- |
| **1 — West** | 311.78° (20h47.1m) | +31.0° | NGC 6960 (Witch's Broom / 52 Cyg) + Pickering's Triangle |
| **2 — East** | 313.78° (20h55.1m) | +31.0° | NGC 6992/6995 (Network / Eastern Veil) |

Seam check: W Veil → panel 1, E Veil → panel 2, northern arc (NGC 6974/79) in
both (overlap). Each panel covers RA ±1.28°, Dec ±1.95°.

### Capture (do West first; East peaks at dawn)
```powershell
# Test frame FIRST: shoot one sub, plate-solve, confirm long axis ~N-S
#   (the whole split assumes it; it's fixed in EQ mode but verify).
# Dark site: try --exposure 120 (check star roundness on the test frame).

# Panel 1 — West  (no --park-at-end: keep the Seestar connected for the handoff)
mira capture --ra 311.78 --dec 31.0 --exposure 60 --gain 80 --filter LP `
  --dest captures/veil_p1_west --platesolve-center

# Panel 2 — East  (last run of the night -> --park-at-end safes the rig at dawn)
mira capture --ra 313.78 --dec 31.0 --exposure 60 --gain 80 --filter LP `
  --dest captures/veil_p2_east --platesolve-center --park-at-end
```
Time split: ~1h50m/panel over the moonless window, or ~2.5h/panel if you start
at astro dark (~22:40). LP_g80 master flat exists → `--auto-flats` works.

## Reduction (after the trip)
Run `output/catskills_jun18/reduce_veil.ps1` (or the steps below). It stacks each
panel, then `mosaic_veil.py` reprojects + coadds them into one WCS mosaic, which
you finish with GraXpert + PCC + stretch.

## Earlier-in-the-night options (decide on-site)
Spring/early-evening sky is galaxies+globulars (no bright nebulae high in the W),
so the early *nebula* options are the rising Cygnus/Lyra ones — start them at
astro dark, don't wait for moonset:
- **Crescent + Tulip** one LP frame — RA 302.71° / +36.82° (covers both + Cyg X-1)
- **M57 Ring** (Lyra) — RA 283.6° / +33.0°, well-placed early
- **M13** (Hercules globular) — overhead ~22:30, best early showpiece if you flex
  off "nebula only"
(These are secondary; the Veil mosaic is the full-night priority.)
