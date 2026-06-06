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

## Gallery export — wide-field sky-FITS (do this for EVERY promoted keeper)
The sky-viewer app is fed **wide-field FITS-with-WCS** display assets, not the
tight portrait crop. So once a keeper is chosen, ALSO emit a gallery asset from
its **full-frame** stretched TIFF (the `--keep` / `--tiff` output — NOT a
cropped preview):

```
python tiff_to_skyfits.py --tiff <KEEPER>.tiff --master <obj>_cc.fit \
    --out output/<obj>/<OBJ>_widefield_<YYYYMMDD>.fit \
    --object "<NAME>" --ra <deg> --dec <deg>
```

Copies the TAN-SIP WCS from the linear PCC master onto the stretched pixels,
writes a `(3,H,W)` uint16 cube, and **validates** (round-trips the object pixel,
prints scale + corners — scale must read ~3.66″/px on the S30; object must be
in-frame). If the keeper was cropped off the full frame, pass the trimmed
`--top-frac/--left-frac` so CRPIX shifts to match. Naming convention
`<OBJ>_widefield_<date>.fit`, **stretch BAKED IN** — the viewer shows it 1:1 by
WCS and must NEVER re-stretch it; the linear `*_cc.fit` is the re-processing
source only. Tool bundled here (`tiff_to_skyfits.py`). (M97 owleyes + Crescent
localcontrast shipped this way 2026-05-31.)

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

## Star removal (StarNet2) — decouple nebula color from star color
**StarNet2 CLI is installed:** `C:\Users\david\tools\StarNet2\starnet2_win_2.5.1-0205_ORT_x64_cli\starnet2.exe`
(keep the bundled `.onnx` + DLLs beside it). Use when a stretch that brings out faint
emission (Ha/OIII) also over-saturates the stars — process them separately.
- **Input must be a STRETCHED uint16 TIFF** (StarNet is trained on non-linear data and
  **rejects 32-bit float**): stretch the linear `*_cc.fit` to a natural (sat 1.0) 16-bit TIFF first.
- `starnet2.exe --input in.tif --output starless.tif --unscreen stars.tif --upsample`
  (`--unscreen` = the star layer; `--upsample` = better quality; default stride 256).
- **GOTCHA: outputs are LZW-compressed TIFF** → `tifffile.imread` fails ("requires imagecodecs");
  read with `cv2.imread(p, cv2.IMREAD_UNCHANGED)` (16-bit BGR → flip to RGB).
- **Recombine:** process **starless** with high saturation + a teal/OIII boost (cyan-weighted
  extra chroma where min(G,B)>R — no stars to over-saturate now); process **stars** with gentle
  saturation (natural, not garish); combine by **screen** `1-(1-neb)*(1-stars)`. Validated on the
  dual-band Crescent (NGC 6888, 2026-06-02) — far cleaner than a morphological-opening starless
  (StarNet leaves zero star residuals). Siril 1.4.3 can also drive StarNet, but the CLI is simplest.

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

## Curve choice — a well-tuned asinh is hard to beat (6-curve shootout)
A multi-agent `process-finish` shootout (the `curve_lab.py` harness + GHS, statistical/MTF,
arctan/tanh, multi-pass-MTF, masked-dual, and local-contrast curves — each researched +
implemented + swept, then judged on 3 lenses + adversarially verified; 2026-05-30, M51
`C_cc`) found **no custom GLOBAL curve cleanly beats a well-tuned asinh** on faint-dominated,
denoised galaxy data. Why: the post-denoise histogram is "everything in the bottom ~2%"
(faint bridge and sky nearly coincident), and asinh's slope is maximal exactly at 0 — already
on the noise-vs-lift frontier; any shadow protection that quiets the sky also flattens the
faint structure (GHS/statistical/arctan independently converged on this). GHS came out
pixel-near-identical (only marginally bluer cores). Curves that scored high on a faint-lift
*metric* (masked, multi-pass MTF: +65–78%) bought it with amplified background/chrominance
noise + halo rings — the panel and the eye reject them (near-perfect inversion: higher
faint-lift metric → lower panel score). **The one lever with real headroom is
SPATIAL/local-contrast** (CLAHE / multiscale unsharp on luminance): it isn't bound by the
global-curve frontier, so it adds arm/inter-arm detail without the noise penalty — modest, and
it haloes if pushed. So spend effort on denoise + integration + careful local contrast, not
exotic global curves. **Regime caveat — this is for *faint-dominated* histograms (galaxies
post-denoise). A *bright planetary* is the OPPOSITE: tested on M57 (2026-05-30), ALL 6 curves
beat asinh — for a bright HDR ring, curve shape genuinely helps. But pick by EYE, not the metric:
the chroma metric crowned GHS, which oversaturated the dominant OIII-teal and bleached the red
Ha rim toward white; the faithful winners (keeping BOTH hues) were arctan + local-contrast.
Lesson — a max-min-RGB chroma metric credits single-hue saturation as "more color", so judge
multi-hue color by eye.** **Third regime — GLOBULAR CLUSTERS (HDR star fields), M13 2026-06-02:**
a "blown" core is almost always the STRETCH, not saturation — dithered many-frame stacks
de-saturate (M13's linear had 0% clipped, 40+ resolved core maxima, core peak only ~2.6% of
global max). Hold the core with **GHS `D=2.0 b=1.5 SP=0.015 HP=0.20`**: low SP lifts faint
cluster/field stars while **HP<1.0 linearizes everything brighter** (dense center + bright stars),
restraining them from clipping. asinh `--param 0.26` is a close, simpler second; asinh `0.10`
blows to a white blob. So globulars side with the bright/HDR regime (curves help), not faint
galaxies. Color: warm-RGB + neutral bg + sat for star color, skip deconv on the dense field. The
warm-pipeline GHS variant lives at `output/m13/stretch2.py` (curvelab `ghs.apply`, `hd_lo=1.0`).
**Formalized tool (no longer scratch):** the harness lives here at `curvelab/curve_lab.py`,
curve library in `curvelab/curves/` (asinh, mtf, ghs, statistical, arctan, loghist,
localcontrast, masked). Target-parameterized, two metric modes:
`python curvelab/curve_lab.py --in <linear FITS> --curve <name> --mode faint|chroma --ra <deg> --dec <deg> [--sweep]`
(`faint` = galaxies, faint-feature detect; `chroma` = planetaries, rim color + chrominance noise).
Full bake-off (re-tune all 6 curves in parallel → 3-lens judge panel → adversarial verify vs an
asinh baseline) is the saved workflow `.claude/workflows/process-finish.js`:
`Workflow({name:'process-finish', args:{target, baseFits, mode, ra, dec, baseline:{params}}})`.
**Input is always a *linear* (bg-extracted/denoised/PCC) FITS** — the harness applies the stretch.
The per-target scratch copies under `output/m{51,57}_work/tmp/curvelab/` were the prototype.

## Judge both ways (the brief is: stats AND eye)
- **Stats:** background noise, target SNR, a *faint-feature* SNR (e.g. the
  M51–NGC 5195 bridge), corner/center flatness. Track across variants.
  **But beware the proxy:** a `(feature−sky)/σ_sky` ratio is gameable — a curve
  can win it by *lowering displayed sky-noise* (the denominator) without adding
  signal, and a luminance-only σ misses color mottle. Always corroborate with the
  eye, and measure a genuinely faint *outer* feature, not a bright core-overlap.
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
