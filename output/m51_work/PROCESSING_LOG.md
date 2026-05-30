# M51 processing log — 2026-05-29 (autonomous run)

**Final images (2nd pass):**
- `M51_final_natural_20260529.png` — natural, PCC-color (= `cand/C_cc3.png`). **Primary.**
- `M51_final_starless_20260529.png` — star-reduced (= `cand/C_cc3_starless2.png`).
- `M51_final_20260529.png` — 1st-pass best (= `cand/C_v5.png`), superseded by `_natural`.

## Data used
| Set | Subs | Sub | Gain | Sky | Notes |
|---|---|---|---|---|---|
| A — tonight (05-28) | 254 culled, solved, dithered | 60s | 80 | 91% moon, LP | full-res but cropped field (1046×1200) from blind-dither wander |
| B — May 17 | 742 culled (`m51_hi`) | 12s | 200 | dark (0% moon) | full-field 2160×3840; **broadband/no-LP → red color cast** |
| C — combined | 996 (A+B), Siril cross-session register | — | — | — | full-field; M51 center = all 996 overlap ≈ 6.7h |

## Experiments + judging (stats: M51 SNR / faint-bridge SNR; plus eye)
- **Tonight-only (A):** GraXpert bg→denoise→deconv + custom asinh/curve. Denoise was the big win (SNR 35.7 raw → 60.7; bridge 4.0σ → 7.1σ). Deconv crisped the arms. Best = `A_v7`. Clean, neutral, but cropped field + shallower.
- **May-17-only (B):** full-res, dark-sky → strongest *faint* contrast (bridge 9.8σ) but a heavy **red cast** (no LP filter to cut urban sodium glow). Color unusable as-is.
- **Combined (C):** deepest of all (SNR 90.4, bridge 10.8σ pre-deconv). The May-17 red contamination was corrected with a per-channel black point + R-reduction / B-boost. Object-deconv for sharpness (trades SNR 90→77 for crisper arms — worth it on the galaxy). **Winner.**

## Final recipe (reproducible)
1. Stack 996 subs (both nights) → `masters/C_combined.fit` (Siril, full-res debayer, star-registration handles the cross-session alignment).
2. GraXpert **background-extraction** → **denoising** → **object-deconvolution** (linear) → `masters/C_bg_dn_dc.fits`.
3. Custom stretch (`tmp/stretch.py`): per-channel black @30% • white @99.94% • **asinh(0.038)** • color balance **R×0.87 G×0.95 B×1.14** (neutralize May-17 red) • S-curve 0.17 • saturation 1.45 • crop 33%/side to frame M51 + NGC 5195.

## SNR progression
raw A 35.7 → A denoised 60.7 → **combined 90.4** (bridge 4.0σ → 7.1σ → **10.8σ**); deconv final 77.2 / 8.5σ.

## Alternatives kept
- `cand/A_v7.png` — tonight-only (most color-pure, no May-17 contamination; shallower).
- `cand/C_v4.png` — combined, more restrained color/contrast.
- Linear masters in `masters/`; all candidates in `cand/`. Re-stretch `C_bg_dn_dc.fits` to taste.

## Second pass (2026-05-29) — squeezing more juice
Three more levers tried; two kept.
- **Faint tidal-tail push** (`cand/C_faint.png`, black 12 / white 99.9 / asinh 0.02):
  **negative result.** Surfaces a faint M51 halo but the distinct tidal tails sit
  below the noise floor (30mm + urban + 6.7h won't reach them); the hard pull just
  lifts background mottle + residual gradient. Dropped.
- **PCC photometric color calibration** (Siril `pcc` on `C_bg_dn_dc`, 1441 stars →
  `masters/C_cc.fit`): **kept — the win.** Catalog-driven color replaces the
  eyeballed R↓/B↑ from pass 1. Gave distinct blue/white/orange star colors and
  physically-correct bluish M51 arms. PCC over-cooled the sky (navy cast); a small
  warm nudge in the stretch (`--rgb 1.08,1.02,0.90`) re-neutralized the background
  while keeping PCC's star color. → `cand/C_cc3.png` = new natural best, replaces C_v5.
  PCC flagged its own solution "imprecise" (multi-night + 91% moon background is hard
  for it) but the result is clearly more accurate than the hand balance.
- **Star reduction** (`tmp/star_reduce.py`, mask-based, no StarNet): dims compact
  stellar excess toward the local background, protects the central galaxy pair with an
  exclusion ellipse. `alpha 0.78 rad 6` → `cand/C_cc3_starless2.png`. Crude vs a neural
  star-removal tool but clean (no holes/halos) and makes M51 the unambiguous subject.
  **A proper StarNet/StarXTerminator pass would be cleaner — not installed.**

## Final recipe (2nd pass, reproducible)
1. `masters/C_combined.fit` (996 subs, both nights) → GraXpert bg → denoise → deconv-obj
   → `masters/C_bg_dn_dc.fits` (as pass 1).
2. Siril `pcc` (platesolve 202.4696,47.1952 -focal=150 -pixelsize=2.9) → `masters/C_cc.fit`.
3. **Natural:** `stretch.py --in masters/C_cc.fit --black 34 --white 99.94 --param 0.038
   --sat 1.45 --rgb 1.08,1.02,0.90 --scurve 0.16 --crop 0.33`.
4. **Star-reduced:** `star_reduce.py cand/C_cc3.png <out> 0.78 6 98.5`.
