# PixInsight evaluation plan

*Written 2026-06-11. Status: analysis saved for later — no purchase yet, trial not started.
Prices/links verified 2026-06-11.*

## Verdict in one paragraph

Buying PixInsight would confidently improve our results in **four specific areas** —
BlurXTerminator deconvolution, SPCC color calibration, MGC/MARS gradient correction,
and multi-night/mosaic integration — each of which maps to a pain point already
documented in this repo. It would **not** improve stretching/finishing (our
bake-off-validated `mira finish` presets stay) or day-to-day stacking (Siril +
`mira` automation stays). The right move is the **free 45-day trial run as a
falsifiable A/B against our existing keepers** (protocol below), then buy only if
it clearly wins. Budget if it does: **€300 PI + $100 BlurXTerminator** (~$430
all-in); NoiseX/StarX are optional $100 add-ons later, not part of the case.

## Current pipeline (what PI must beat)

`mira solve → cull → stack` (Siril engine, auto-flats) → GraXpert bg-extraction →
Siril PCC (VizieR) → `mira finish --preset` (GHS core-hold / asinh frontier /
gated local chroma / StarNet2 decoupling — adversarially validated in the 2026-06
curve shootout, recipes baked in `finish_presets.py`).

Strengths: fully scripted, reproducible, per-target presets with provenance.
Documented weaknesses (the targets PI aims at):

1. **Gradient vs. real nebulosity** — statistical bg-extraction can't tell Bortle-9
   gradient from extended Ha. The NGC 6888 finding: *"bg-extract AFTER PCC —
   gradient masquerades as sky (94%)"* (`output/processed/ngc6888/PROCESSING_NOTES`).
   On LP widefields where emission fills the frame, GraXpert eats faint signal.
2. **PCC fragility** — VizieR 503'd on 2026-06-06; fallback is hand-balancing
   (recorded in `output/trips/catskills_jun18/reduce_veil.ps1`). Also: generic PCC
   has no concept of the S30's LP dual-band passband.
3. **No real deconvolution** — GraXpert deconv is weak; recipes skip it. S30 data
   is undersampled (3.66"/px) with soft corners; Esprit 80/120 mono data deserves
   PSF correction.
4. **Mosaic seams** — `mosaic_veil.py` is reproject + mean coadd; no
   gradient/scale matching at seams. Fine for a first pass, visible seams likely.
5. **Multi-night sky-level mismatch** — combining JC + dark-site data (e.g. adding
   Catskills OIII to the JC Crescent) has no normalization story beyond Siril
   defaults.

## The four confident wins (ranked)

| # | Tool | Attacks | Cost | Notes |
|---|------|---------|------|-------|
| 1 | **BlurXTerminator** (RC Astro, runs inside PI) | Weakness 3 | $99.95 (30-day trial) | AI PSF correction + deconvolution. Biggest visible per-dollar upgrade in amateur processing. Use *correct-only* first; conservative sharpening after; never trust AI detail not present in the raw — verify at 1:1 against the unprocessed linear (our adversarial-verification ethos applies to our own tools). |
| 2 | **SPCC** (built-in) | Weakness 2 | included | SpectroPhotometric Color Calibration from a **local Gaia DR3 spectral DB** — offline (dark-site friendly), no VizieR, calibrates against actual filter curves, explicit narrowband/dual-band OSC mode (knows what LP is). |
| 3 | **MGC / MARS** (built-in, survey-based) | Weakness 1 | included | Models gradients against an external reference sky survey — no samples, works over extended objects, doesn't eat real Ha. Caveat: **check MARS coverage for our fields first** (survey still growing as of mid-2026): https://pixinsight.com/mars/ |
| 4 | **LocalNormalization + PhotometricMosaic + drizzle** (built-in) | Weaknesses 4, 5 | included | LN for JC+dark-site session combining; PhotometricMosaic for seam-matched 2-panel Veil/Sadr; mature 2× drizzle for dithered undersampled S30 subs (recent Siril has basic drizzle — compare before crediting PI). |

## Non-goals — keep ours

- **Stretch/finish:** `mira finish --preset` stays. PI's GHS is the same math we
  already implement, minus our baked reproducibility. The shootout lesson ("pick
  by EYE", adversarial verifier) cost real effort — don't discard it.
- **Stacking/automation:** Siril via `mira` stays the capture-night path. WBPP is
  GUI convenience we don't need.
- **NoiseX/StarX:** better than GraXpert-denoise/StarNet2 but incremental.
  Re-evaluate only after the core four prove out.

## Integration design (if purchased)

PI becomes a **surgical linear-stage station**, not a pipeline replacement:

```
mira solve/cull/stack ──► PI station (interactive, per target)      ──► mira finish --preset
        (unchanged)         1. SPCC   (replaces Siril PCC step)            (unchanged)
                            2. BlurX  (correct-only → mild sharpen)
                            3. MGC    (replaces GraXpert bg, where MARS covers;
                                       else keep GraXpert via --no-bg juggling)
                            export 32-bit FITS, WCS preserved
```

- Naming: PI-processed linears land next to the stack as
  `<target>_stack_pi.fit` in `output/processed/<target>/work/`.
- Reproducibility: save a PI **process icon set per target** alongside the work
  dir (PI's equivalent of our recipe scripts); note settings in PROCESSING_NOTES.
- One interactive step per target is acceptable — finishing is already per-target
  hands-on.

## Trial protocol (the falsifiable A/B — do this before paying anything)

PI trial: 45 days, full-featured, **single machine** (homebase). BlurX trial: 30
days. Don't start the clock until there's processing time available — ideal
window: **right after a capture trip lands new data** (e.g. Iris LRGB + IC 1396
from the Catskills run would be a perfect fresh test set alongside the archive).

1. Test set (linear masters that already have validated keepers):
   - `output/processed/m81/work/m81_stack.fit` → keeper `M81_group_20260609`
   - NGC 6888 linear (work dir) → keeper `NGC6888_crescent_refinish_20260609`
   - M51 widefield linear → keeper `M51_alllum_refinish_20260609`
2. Per target: SPCC (correct sensor/filter setup; LP = dual-band mode) → BlurX
   correct-only, then stars ~0.25 / nonstellar ~0.25–0.5 max → MGC if covered →
   export → `mira finish --preset <same preset as the keeper>`.
3. Judge **by eye** (the shootout rule), blink at 1:1 plus the contact-sheet
   crops at the same coords as the keepers. Specifically check: star tightness
   without worm artifacts (BlurX), color believability (SPCC), faint-Ha retention
   vs the GraXpert version (MGC).
4. **Buy gates:** ≥2 of the 3 are clear wins → buy PI + BlurX. Only SPCC wins →
   PI alone is defensible (color + offline + mosaics). Nothing clearly wins →
   keep the €300 and revisit when MARS coverage matures.

## Facts checked 2026-06-11

- PI commercial license **€300** one-time (US: no VAT), lifetime updates for the
  major version; activation needs internet once. https://www.pixinsight.com/licenses/
- Trial: 45 days, full-featured, one machine. https://pixinsight.com/trial/
- BlurXTerminator $99.95, 30-day trial, requires PI. https://www.rc-astro.com/
- MARS/MGC docs: https://pixinsight.com/doc/docs/MARS/MARS.html
