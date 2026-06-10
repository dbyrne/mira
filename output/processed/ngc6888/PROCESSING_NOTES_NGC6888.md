# NGC 6888 (Crescent) — combined-night processing, 2026-06-02

## Data — two nights combined
- `captures/ngc6888_20260530`: 190 subs (already solved + culled, 21 rejected).
- `captures/ngc6888_20260601`: 90 subs → solved (90/90) → culled (88 kept, 2 trailed).
- **Both nights LP / gain 80 / 60s** — same filter, so NO cross-night color-cast trap.
- Hardlinked all culled subs into `captures/ngc6888_combined/` (278 subs) → `mira stack`.
- **278 × 60s ≈ 4.6 h** (up from the single-night ~3.2 h). Stronger shell, fuller bubble loop, OIII now visible.

## Pipeline (matches prior recipe)
stack (278) → GraXpert bg-extraction → denoise → **deconv-obj** (inspected vs bg_dn: crisper
shell filaments, no ringing — the shell isn't a planetary-bright rim, so deconv is safe here) →
Siril PCC (303.0,38.35 focal=163 px=2.9) → stretch.

## Stretch — faint emission regime
NGC 6888 is a faint Ha+OIII shell in a dense Cygnus field. Key lesson: **curvelab's default
`white_pct=99.99` crushes the nebula** — the star field monopolizes the dynamic range. Dropping
the white point to **99.6** is what makes the shell read. Final = aggressive asinh:
`a=0.05, white_pct=99.6, sat=2.0` (per-channel sky black → neutral bg; high sat pulls the
Ha-red / OIII-teal apart). Crop = 880px box centered on the nebula.
- asinh a0.05 (clean, clear shell) chosen as **primary**.
- localcontrast (the prior single-night keeper) at the corrected wp99.6 is a near-tie — marginally
  more filament pop, marginally more background noise. Kept as the alternate.

## Revision — StarNet2 starless + teal boost (NEW PRIMARY, 2026-06-02)
The aggressive-saturation asinh version made the **stars garish** (over-saturated red/blue) —
the same sat knob that pulls out the faint Ha/OIII. Fixed by **separating stars from nebula**:
- Installed StarNet2 CLI (`C:\Users\david\tools\StarNet2\...\starnet2.exe`). Fed it a natural
  (sat 1.0) stretched uint16 TIFF → clean `starless` + `stars` (`--unscreen`). (StarNet rejects
  32-bit float; its LZW TIFF output must be read with `cv2`, not `tifffile`.)
- **Starless:** saturation ~2.8 + cyan-weighted teal/OIII boost (no stars to over-saturate) →
  the teal OIII bubble now reads alongside the red Ha crescent.
- **Stars:** gentle saturation (~0.95) → natural, not garish.
- **Recombine:** screen `1-(1-neb)*(1-stars)`.
StarNet starless was far cleaner than the earlier morphological-opening attempt (zero residuals).

**Star-prominence tone (final = "light"):** the combined render looked like it had ~4× more stars
than the single night. Analysis showed it was **not** the extra night — detectable star *count*
rose only 1.13× (the 2nd night adds just ~0.21 mag). The apparent explosion was the **white-point
drop 99.99→99.6** I used to lift the faint nebula: on identical data it takes "bright" stars
(>20% max) from ~174 to ~2900 (~17×). Since StarNet split the stars into their own layer, the fix
is to tone the **star layer independently**: a per-star brightness curve `lum**gamma * scale`
(gamma>1 suppresses faint stars more than bright). Shipped **"light"** (gamma 1.7, scale 0.95):
bright stars 3214→2731, faint field thinned, nebula unchanged. (Heavier moderate/strong variants
saved in `output/ngc6888_work/_stars_*.npy` if a sparser look is wanted later.)

**Ha-blowout fix (final):** the first starless+teal had the bright Ha shell clipping to flat
solid-red blobs (~0.9% of the shell, pure R≥0.99 / G,B<0.5). Diagnosis: the *linear* Ha was
never clipped (brightest knot 0.29 vs global max 0.44), but (a) the StarNet input stretch
clipped ~0.6% of bright shell red, and (b) saturation then pushed it to pure-clip. Two fixes:
(1) a **per-channel highlight rolloff on the StarNet input** (`1-(1-k)·exp(-(y-k)/(1-k))`, k=0.62)
so bright Ha caps ~0.86, never clips — then re-ran StarNet; (2) **brightness-rolloff saturation**
in the recombine — `sat` interpolates from full (`sat_hi` on faint OIII/teal) down to ~1.15 on
bright Ha based on the per-pixel max channel, so the bright shell keeps its gradient/filament
structure instead of flattening. Result: pure-red-blown 0.87% → **0.000%**, OIII teal retained.

## Outputs (in `output/ngc6888/`)
- **`NGC6888_crescent_20260602.png/.tiff`** — **primary** = StarNet starless + teal (strong).
- `NGC6888_crescent_withstars_20260602.png/.tiff` — the prior asinh (with-stars) version, preserved.
- **`NGC6888_widefield_20260602.fit`** — gallery sky-FITS, validated 3.670″/px, in-frame.
- Intermediates regenerated: `ngc6888_stack.fit`, `ngc6888_bg.fits`, `ngc6888_bg_dn.fits`,
  `ngc6888_bg_dn_dc.fits`, `ngc6888_cc.fit`.
- Prior single-night `*_20260531` artifacts left in place for comparison.

## Refinish 2026-06-09 — toe+dig decouple from a re-flattened linear (NEW CANDIDATE)
`NGC6888_crescent_refinish_20260609.png/.tiff` (+`_crop.png`), via `crescent_refinish.py`.

**What changed vs the 06-02 primary:**
1. **Second-pass GraXpert bg-extraction on `ngc6888_cc.fit`** → `ngc6888_cc_flat.fits`.
   The original chain ran bg-extraction BEFORE PCC; PCC's global channel scaling left a
   spatially-varying blue/teal gradient that any deep stretch surfaces (v1–v3 of this
   refinish all went blue-purple until this fix). The flatten dropped the apparent "sky
   pedestal" 0.019 → 0.00125 in normalized units — it was gradient, not sky.
   **Lesson for the recipe: bg-extract AFTER color calibration too** (or instead: PCC
   first, then one bg pass).
2. **StarNet decouple with the M81-shootout toe+dig** (a=0.05 prestretch w/ the June-2
   rolloff k=0.62, starless re-linearized → toe 1.5σ → asinh b=0.03 dig, stars sg=1.0 +
   "light" tone 1.7/0.95), luminance-gated teal boost, brightness-rolloff saturation
   (knots only: 0.62→0.95), gated chroma blur, bg-neutralize, pedestal 0.03.

**Verified vs 06-02 primary (same annuli):** bg speckle 0.0622 → **0.0083** (7.5×),
bg chroma 0.0709 → **0.0201** (3.5×), star garishness 0.172 → **0.079**,
pure-red-clip 0.000% (matched), red-dominant rim 28.3% vs 35.0% (theirs includes
red-tinted noise wash; shell reads cleaner+deeper by eye — see `_compare_0602_vs_0609.png`).

**The teal question (honest finding):** the 06-02 keeper's prominent OIII teal does NOT
survive significance testing on the flattened linear — per-pixel interior teal margin is
−1σ vs background, and a binned test can't be calibrated because the "background" annulus
is itself full of real Cygnus Ha structure (the positive control fails too). So: bold teal
at this depth (4.6h LP dual-band) is stylization, not measurement; this refinish keeps only
the locally-real teal excess (~1% of rim pixels). **A few hours of mono OIII on the Esprit
settles it** — the Crescent already carries an OIII budget in the emission catalog.

## Candidates / scratch (in `output/ngc6888_work/`, yours to delete)
`cr_*.png` (the stretch sweep), `_crescent_stretch_compare.png`, `_asinh_vs_localcon.png`,
the curvelab `localcontrast`/`asinh` outputs, plus `output/ngc6888/_deconv_check.png` and
`output/ngc6888/_ngc6888_full.png/.tiff`. The combined sub dir `captures/ngc6888_combined/` is
hardlinks (no extra disk) — safe to delete to declutter.
