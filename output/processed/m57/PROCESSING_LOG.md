# M57 (Ring Nebula) processing log — 2026-05-30 (autonomous run)

**Final images:**
- `M57_final_20260530.png` — ring portrait (= `cand/M57_final_native.png`, 2× Lanczos upscale for display). **Primary.**
- `M57_wide_20260530.png` — M57 in its Lyra star field (context alternative).

## Data
| Set | Subs | Sub | Gain | Sky | Notes |
|---|---|---|---|---|---|
| M57 (05-30) | 152 culled (of 246) | 30s | 80 | 99% moon, LP | ~76 min; solve→cull dropped 97 (early cloud/dew cluster + 3 off-target pointing-fix frames) |

Single night, single filter → **no cross-session color cast** (simpler than the M51 multi-night combine).

## Pipeline (same shape as the M51 2nd pass)
1. Stack 152 frames → `masters/m57.fit` (Siril, full-res debayer, star registration).
2. GraXpert **bg-extraction** (kills the 99%-moon green gradient) → **denoise** → **deconv-obj @ strength 0.15** → `masters/m57_dec015.fits`. **Deconv strength is the whole story here.** The default **0.5 rang the ring's bright rim** — concentrating its two brightest rim points into spiky cores ringed by dark-undershoot moats (per-channel → cyan/orange fringe). Looks like two black "stars" but they're **rim artifacts, NOT field stars** (absent in the raw + non-deconv; deconv manufactured the cores). A strength sweep showed artifacts scale with strength: **0.5 bad, 0.25 borderline, 0.15 clean** — at 0.15 the rim stays smooth and a little ring crispening is retained. User caught the default-strength artifacts on the first delivery; **lesson: on small bright planetaries use low-strength deconv (~0.15), never the default 0.5.**
3. Siril **PCC** color calibration on the strength-0.15 deconv base (`platesolve 283.3962,33.0292 -focal=150 -pixelsize=2.9` → `pcc`) → `masters/m57_cc_s15.fit` (2563 stars). **The win** — turned a white blob into a teal-OIII / red-Hα ring. (Reference bases kept: `m57_cc.fit` = deconv@0.5 with rim artifacts, `m57_cc_nd.fit` = no-deconv.)
4. Custom stretch (`tmp/stretch.py`, M57-adapted: ring/halo-SNR metrics + M57-centered crop): per-channel black @36% • asinh **param 0.17** • sat 1.95 • S-curve 0.04 • 120px-box crop on M57 • 2× Lanczos upscale for display.

## Judging (stats + eye)
- **Stats:** ring_SNR ~458 (very high — bright, clean ring), bg_noise 1.57e-05, **halo_SNR ~0.04** → the faint outer halo is below the noise floor (not recoverable under a 99% moon).
- **Eye:** ~10 variants. Decisive lever was **asinh param = highlight protection**: param 0.09 blew the core white (no color); **0.17 preserved the teal ring + red Hα rim + dark cavity**; 0.21+ over-compressed and faded the red rim. Saturation ~1.9–2.0 pops the emission color; >2.05 runs hot.

## What "best" took
**PCC** + **deconv-obj @ strength 0.15** (the artifact-free sweet spot) + asinh-0.17 (highlight-protected) + sat 1.95 + tight M57-centered crop + 2× upscale. **PCC biggest win** (color); highlight protection second (ring structure); **low-strength deconv a clean third** (mild crispening — the default 0.5 rings the rim, step 2). The ring is only ~21 px (S30 @ ~3.66″/px), so it's a clean color *portrait*, not a detail showcase — **data-limited, not processing-limited.**

## Not pursued (data-limited, by design)
- **Drizzle:** ruled out — FWHM ~2–3 px (adequately sampled, not undersampled), so drizzle would enlarge + add noise without real detail (same conclusion as M51).
- **Faint outer halo:** below the noise floor under the 99% moon (halo_SNR 0.04). Needs a dark-sky night + long Hα.

## Alternatives kept
- `cand/M57_cc8.png` (sat 1.9, slightly wider), `cand/M57_cc9.png` (sat 2.05, tighter), `cand/M57_wide.png` (context). Linear masters in `masters/`; re-stretch `m57_cc.fit` to taste.
