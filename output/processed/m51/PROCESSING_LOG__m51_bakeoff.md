# M51 all-lum refinish — 2026-06-09

**Keeper:** `M51_alllum_refinish_20260609.png` / `.tiff` (16-bit). Replaces
`M51_alllum_finish.png` as the presentation render of the bakeoff's all-lum stack.

## Diagnosis of the previous finish
`M51_alllum_finish.png` was stretched into the noise floor with no chroma
control: background level 0.239 (8-bit 61/255 — bright murk), background
chroma noise 0.0597 (the red/green mottle), residual gradient at the frame
edges. The galaxy itself was fine; the background made it read as
over-processed. Classic case of the curve-shootout finding: the fix is not a
better global curve, it's a **gated local chroma op**.

## Recipe (reproducible)
1. `all_lum.fit` → GraXpert **background-extraction** → `all_lum_bg.fits`
   (via `mira.finishing.run_graxpert_step`; NOTE: pass **absolute** paths —
   GraXpert joins relative `-output` onto the input dir and doubles the path).
2. `refinish_m51.py --in all_lum_bg.fits --param 0.030 --bp-soft 4.0
   --bg-target 0.075 --scnr 0.7 --rgb 1.02,1.0,1.05 --sat 1.40 --scurve 0.08
   --gamma 1.04 --lc-amount 0.12 --lc-radius 30 --trim 0.006,... --tiff`

The ops that did the work, in order of impact:
- **Gated chroma denoise** (lum < 0.10→0.22 fade): blur+attenuate chroma in the
  background only. Bg chroma noise 0.0597 → **0.0109** (5.5×). Galaxy/stars
  untouched by construction.
- **Background neutralization by offset** (not scale) to a 0.075 target —
  kills the olive cast without shifting star/galaxy color.
- **Soft black point** (percentile − 4σ): keeps the noise floor alive,
  clip_lo 0.69% (vs crunchy hard-bp alternatives).
- **SCNR 0.7** + tiny channel gains: removes OSC green excess (v1 was green).
- **Gated local contrast** (lum > 0.12→0.25, r=30px, 0.12): arm presence
  without bg lift.

## Verification (same-mask, anti-metric-gaming)
Same 5,787 galaxy-signal pixels measured in both renders:
| | shipped | refinish |
|---|---|---|
| structure gradient (detail) | 0.0314 | **0.0535** (+70%) |
| chroma amplitude | 0.0495 | 0.0418 |
| own bg chroma-noise floor | 0.0597 | 0.0109 |

The shipped render's chroma amplitude sits **below its own noise floor** —
its "color" is mottle. The refinish's 0.0418 is ~4× above its floor: real,
and visibly differentiated (yellow NGC 5195 vs cooler M51 disk).

## Files
- `refinish_m51.py` — the engine (extends `stretch_m81.py` with bg-neutralize,
  SCNR, gated chroma denoise, gated local contrast, honest metrics + --compare).
- `all_lum_bg.fits` — GraXpert bg-extracted linear (re-stretchable).
- `refinish_v1/v2/v3.png`, `_gal_*.png`, `_compare_v2.png` — iteration trail.
- Linear-domain M51 SNR (pre-stretch): 55.6 — unchanged by definition; all
  gains are presentation-honest.
