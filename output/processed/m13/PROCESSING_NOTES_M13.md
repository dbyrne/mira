# M13 processing notes — 2026-06-02

## Data
- Combined two nights into `captures/m13_20260531/`: last night's 49 subs + tonight's ~710 good subs, all **IR / gain 80 / 10s**.
- Solve (767/772) → cull (754 kept; cloud block frames 62–72 + 13 total → `_rejected/`) → 759-frame no-flat stack → GraXpert bg-extraction + denoise (no deconv — dense star field) → Siril PCC (focal=163, pixelsize=2.9).
- **~2.1 h integration**, up from last night's ~8 min (≈16×). Deeper field, more resolved outer-halo stars, ~22 background galaxies in-frame (NGC 6207 + IC 4617 confirmed).

## The "blown core" question — it was the STRETCH, not saturation
Checked the linear data: **0.0000% of the image is within 1% of max**, no saturated plateau; the core's brightest pixel is only ~2.6% of the global max (the max is a bright field star), and there are 40+ distinct local maxima resolved in the core. Dithering + 754-frame averaging fully de-saturated it — no sky position has a bright star in *all* frames. So the detail was always there; the first stretch (`asinh --param 0.10 --sat 1.7`) just over-lifted the faint core into white.

## Curve shootout (research-driven)
Globular clusters are HDR point-source fields. Web research (Telescope Live, Siril GHS, Cloudy Nights) points to **GHS with highlight protection (HP<1.0)** or HDRMultiscaleTransform as the way pros hold the core. Ran a warm-pipeline shootout (`output/m13/stretch2.py`, which keeps the per-channel-black + warm-RGB + saturation color handling and swaps the luminance curve):

| variant | core hold | verdict |
|---|---|---|
| asinh 0.10 (delivered) | blown white blob | worst |
| asinh 0.26 | much better | good, simple |
| **GHS D2.0 b1.5 SP0.015 HP0.20** | resolved center, brightest mid-core glow w/ less clipping | **WINNER** |
| GHS HP0.15 | most core resolution, slightly dimmer cluster | alt (max detail) |
| masked / localcontrast (curvelab) | resolved but came out blue/dim (no warm gain) | not used |

GHS wins because the low symmetry point lifts faint cluster stars while HP=0.20 linearizes everything brighter (the dense center + bright stars), holding them from clipping — exactly the published GHS core-protection strategy. Consistent with the prior shootout finding that curves help in the *bright/HDR* regime (cf. M57), unlike faint galaxies where asinh ties.

## FINAL recipe (locked in)
```
python output/m13/stretch2.py --in output/m13/m13_cc.fit --out output/m13/M13_globular_20260602.png \
  --curve ghs --params D=2.0,b=1.5,SP=0.015,HP=0.20 --rgb 1.35,1.02,0.78 --sat 1.6 --crop 0.25 --tiff
```
- `M13_globular_20260602.png/.tiff` — cropped portrait (official, now GHS — replaced the blown asinh0.10 version).
- `M13_widefield_20260602.fit` — gallery sky-FITS, regenerated from the GHS full-frame, validated 3.665″/px.

## Alternatives kept for your pick (in `output/m13_work/`)
- `w_asinh026.png` — the simpler asinh version (very close second).
- `w_ghs_hp15.png` — max core resolution (cluster glows a touch less).
- `w_ghs_hp30.png` — brightest cluster presence, slightly softer center.
- `_warm_core_shootout.png` / `_before_after.png` — the comparisons.
Swap any in by re-running the recipe with that variant's params, or just copy the PNG/TIFF over the official names.

## Scratch to delete when convenient (yours)
`output/m13_work/` (the whole shootout dir), `output/m13/_m13_full*.png/.tiff`, `output/m13/_test_*.png`, `output/m13/_core_*.png`, `output/m13/_galaxy_*.png`.
