---
name: mira-finish
description: Reduce + finish a deep-sky stack (galaxy/nebula pretty-picture) into a presentable image — the solve→cull→stack→GraXpert→stretch pipeline, multi-night combining, and the hard-won gotchas. Use after a DSO capture to turn raw subs into a final image.
when_to_use: process subs into a final image, stack and finish a galaxy/nebula, combine multiple nights, GraXpert / stretch / color a deep-sky stack
allowed-tools: [Bash, Read, Write, Edit]
shell: powershell
---

# Mira deep-sky finishing

Turn raw subs into a presentable image. **Order matters: solve → cull →
stack → GraXpert → stretch → crop.** Validated on the 2026-05-28/29 M51
(4.3h tonight + a May-17 night, combined to ~6.7h, ~15 experiments).

## Pipeline
1. **Solve first** — `mira solve --lights <dir>`. API-capture FITS carry no
   WCS; ASTAP writes it (guided off the sidecar RA/Dec; fov default 4.6 for
   the S30). Exits 2 if some frames fail — **that's a signal, not an
   error**: unsolvable frames are the genuinely bad ones.
2. **Cull** — `mira cull --lights <dir> --from-fits`. MUST follow solve: the
   solve-failed gate only fires when *some* frames have a WCS, and it
   catches trailed/clouded frames the star/HFR metrics keep (M51: caught 2
   good-metric-but-unsolvable subs the no-WCS cull had kept). Rejects move
   to `_rejected/` (reversible). Dry-run first on a big dataset.
3. **Stack** — `mira stack --lights <dir> --out X.fit`. Full-res
   `-debayer`, registers by stars. `--auto-flats` **hard-aborts on a gain
   mismatch**; for a *centered galaxy* a **no-flat** stack is fine
   (vignetting is an edge effect, GraXpert handles the gradient). Only shoot
   matching flats if you need clean field edges.
4. **GraXpert** (linear, in this order; each: `graxpert -cmd <cmd> <in>
   -output <stem> -gpu false -cli`, stem gets `.fits`, first run downloads
   models):
   - **background-extraction** — removes the gradient/LP/moon and flattens
     the "edge shadow" (which is mostly a stretch-*exaggerated* mild
     vignette — only ~6–10% in linear data; not a flat problem).
   - **denoising** — the single biggest lever. ~halves noise, ~doubles SNR;
     on M51 it took the faint bridge from 4σ→7σ. Check it didn't plasticize.
   - **deconv-obj** — sharpens the subject, trades a little SNR for crispness.
     **Strength matters — the default 0.5 rings ultra-bright, high-contrast
     edges.** On M57 it overshot the Ring's bright rim into dark-moat
     artifacts that masquerade as black "stars" (a `-strength` sweep: 0.5 bad,
     0.25 borderline, **0.15 clean** with mild crispening kept). Fine at
     default on a galaxy; on a **small bright planetary use `-strength 0.15`**
     (or skip). Watch the rim, not just the stars.
5. **Color-calibrate (PCC), then stretch + crop.** **PCC is the biggest color
   win — do it, don't eyeball channel gains.** In Siril on the linear
   GraXpert'd master: `platesolve <ra>,<dec> -focal=<mm> -pixelsize=<µm>`,
   then `pcc` → catalog-accurate star color + neutral background. (Beat the
   hand R↓/B↑ on M51; turned a white blob into a teal-OIII/red-Hα ring on
   M57. Save → re-load for the stretch.) Then stretch: bundled `stretch.py`
   for full manual control, or Siril `autostretch -linked` for the quick
   path. `mira finish` chains GraXpert+Siril+crop automatically by hand-off.

## Multi-night combine
- **Let Siril do the cross-session registration** (its strength): hardlink
  each night's *culled* subs into one dir (`os.link`, no 16GB copy) and
  `mira stack` it. Siril aligns/normalizes/weights all subs → one deeper
  master. ~doubling integration ≈ sqrt(t) SNR gain (M51 raw SNR 36→90).
- **Filter-mismatch color trap:** nights shot through different filters
  (e.g. LP vs none) have different spectral response, so the combined image
  inherits a **color cast** (the no-LP May-17 night added a red/sodium
  cast). Fix with a per-channel black point + channel gains (R↓/B↑), OR go
  **LRGB**: luminance from the combined deep data, color from the clean (LP)
  night only. Dark-sky frames help the *faint end* disproportionately even
  if shorter — combining is usually worth it once color is handled.

## Hα blending (the dual-band LP trick — LP + no-LP)
The Seestar LP filter is **dual-band (Hα+OIII)**, so an LP stack's **red
channel ≈ continuum-suppressed Hα** — the HII / star-forming regions. Pair it
with a **no-LP broadband** stack to blend the HII into a galaxy (pink
star-forming knots down the arms). Tool: **`ha_blend.py`** (bundled here) —
reprojects the LP-Hα onto the broadband base via the plate solutions,
thresholds to real HII, and boosts red; `K` sets strength.
- **Threshold the Hα** (a few σ over its own sky) before boosting, or you
  amplify background noise into a red flood. And scale **modestly** — matching
  Hα to the base's bright 99.5th-percentile catastrophically over-boosts (the
  whole frame goes red — learned the hard way). Add a controlled fraction of a
  mid-bright reference instead.
- **K ≈ 0.4** balances pink HII + blue young stars (the true galaxy look);
  ≈ 0.6 goes mostly-pink.
- **A moony LP night gives a soft HII *tint*, not crisp knots** — a *dark*-night
  LP pass is what makes this sing. (M51 2026-05-30: kept as a variant, but the
  broadband-natural stayed primary — the 91%-moon Hα was only a modest lift.)
- Deps: `pip install reproject`; both stacks need a WCS — use
  `WCS(header, naxis=2)` for the 3-layer RGB FITS, and the LP stack must be solved.

## Manual stretch tool (`stretch.py`, bundled in this skill dir)
`python stretch.py --in <bg-flat linear FITS> --out x.png [opts]`. Run it on
the **GraXpert-processed** FITS (the per-channel black point needs a flat
background). Opts: `--black/--white` (percentile points), `--mode
asinh|log|power|mtf --param`, `--rgb R,G,B` (color balance / cast removal),
`--scurve` (contrast), `--sat`, `--gamma`, `--crop` (frac/side), and `--tiff`
(also write a **16-bit lossless TIFF** next to the PNG — use it on the
keeper/final, not every iteration: the PNG is 8-bit + quantized, the TIFF
preserves the full-depth stretch for archival/re-editing). It prints
stats (bg noise, target SNR, faint-bridge SNR, corner flatness). Target
region is located via WCS — edit the two coords at the top of the file for a
different object.

## Judge both ways (the brief is: stats AND eye)
- **Stats:** background noise, target SNR, a *faint-feature* SNR (e.g. the
  M51–NGC 5195 bridge), corner/center flatness. Track across variants.
- **Eye:** actually `Read` the PNG. Watch for walking-noise streaks (dither
  check), denoise plastic/blotch, deconv ringing (stars *or* bright nebula
  rims), color cast,
  over-saturation, a clipped core.

## What "best" took on M51
Combined both nights (deeper than either alone) → bg → denoise → deconv →
asinh + per-channel black + R↓/B↑ (kill the cross-night cast) + mild S-curve
+ saturation ~1.4 + tight crop. **Denoise was the biggest single win;
deconv a close second for galaxy crispness.** Keep a restrained-color
alternative and the single-best-night version around — they're legitimate
different "bests."

## What "best" took on M57 (small bright planetary)
PCC + **low-strength deconv (`-strength 0.15`)** + GraXpert denoise + asinh
with **strong highlight protection (param ~0.17)** + sat ~1.95 + tight
target-centered crop + 2× Lanczos upscale. **Highlight protection is the
planetary-specific lever:** the ring is intensely bright, so a normal stretch
blows its core white and kills the OIII-teal / Hα-red color — a high asinh
param holds the core back so the color reads. Faint outer halo was below the
noise floor under a 99% moon (data-limited, not processing). At ~21 px on the
S30 it's a clean *color portrait*, not a detail showcase. PCC was the biggest
win (color), highlight protection second, low-strength deconv a clean third.
(Validated 2026-05-30, M57, 152 subs / ~76 min.)
