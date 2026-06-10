# M81 group reprocess — 2026-06-09 (curve shootout + post-pass)

**Keeper:** `M81_group_20260609.png` / `.tiff` (full frame 2160×3840, 16-bit).
Supersedes `M81_group_20260605.png` (which was a very conservative render —
near-black sky, galaxies as small amber blobs, NGC 3077 invisible).

## How it was made

### 1. process-finish shootout (output/M81_curveshootout/, 11 agents)
Six techniques re-tuned for the M81 group vs the `stretch_m81.py` asinh
baseline, full judge panel + adversarial verify. All six honestly beat the
baseline; panel ranking:

| technique | panel avg | faint_detect (baseline 11.54–12.84) |
|---|---|---|
| **starnet-decouple** | **7.3** | 19.32 |
| chroma-boost-gated | 7.0 | 19.46 |
| chroma-denoise-gated | 7.0 | 14.54 |
| ghs-core-hold | 6.67 | 14.04 |
| localcontrast | 6.67 | 18.57 |
| asinh baseline | 6.17 | — |
| color-recalibration | 5.27 | 15.27 |

**Winner: starnet-decouple** (StarNet2 star/starless decoupling; starless layer
gets a noise-floor toe + deeper asinh dig, stars screened back at the gentle
baseline curve). Adversarial verifier: real improvement, confidence 0.85 —
gain ~75% numerator-driven, structure confirmed by gain-matched control, no
StarNet artifacts (no rings/seams/posterization). Flagged honest costs of the
aggressive DEFAULTS row: sky crushed (~50% zero pixels), stars uniformly
dimmed 11% (sg=0.9), uncorrected yellow-green cast.

### 2. Final keeper composition (verifier-informed)
- Render: **conservative row + no star dimming** — `a=0.025, b=0.014,
  toe=0.003, sg=1.0` (faint_detect 15.79 @ sky_noise 0.0167 ≤ baseline cap
  0.0173, core_clip 0). Full-frame via `curve_lab.py --keep`
  → `M81_curveshootout/variants/_final/`.
- Post-pass (`post_m81.py`): **luminance-preserving SCNR 0.7** (cast removed
  as color, kept as light), background hue neutralization by offset, **gated
  chroma denoise** (bg chroma noise 0.0153 → 0.0090), **display pedestal
  0.045** (fixes the toe's 67%-zero inky floor → 0% zeros, neutral
  0.046/0.046/0.046 sky).
- Structure preservation verified on a fixed mask: detail ratio **95.4%** =
  exactly the pedestal's 0.955 contrast scale → the chroma ops cost nothing.

## vs the 06-05 keeper (`_compare_old_new.png`)
M81 disk properly extended, M82 bright with dust-lane structure, **NGC 3077
visible at all**, more faint stars, sky a natural dark gray with fine grain
instead of pure black.

## Future improvement (noted, not done)
The remaining warm cast is data-borne (no photometric color calibration on
this stack). A Siril PCC/SPCC pass on `m81_bg2.fits` *before* stretching —
like the M51 May recipe — is the proper fix; SCNR here is mitigation.
StarNet decomposition cache (~300MB) in `M81_curveshootout/variants/
starnet-decouple/_cache` — reusable for re-renders at a=0.025.
