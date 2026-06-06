"""localcontrast -- global asinh + structure-gated local enhancement (NGC6888 edition).

ORIGIN: ported from the M51 faint-galaxy run, where this curve used a large-radius
masked unsharp mask on luminance to lift M51's outer arms + the M51<->NGC5195 bridge
above the sky.  Re-pointed once for M57 (tiny bright planetary), and now re-tuned again
for NGC6888 -- the Crescent Nebula, a Wolf-Rayet wind-blown BUBBLE.  See "What changed
for NGC6888" at the bottom.

NGC6888 is NOT a bright planetary: the H-alpha-red shell rim and the OIII-teal cap/
interior are FAINT, emission-line, and sit at a stretched luminance (~0.007-0.04 under
the baseline a=0.012) that is BELOW or near the sky noise floor.  So this regime is
faint-dominated even though we judge it in "chroma" mode.  The two crucial consequences:

  * The base asinh MUST be as aggressive as the baseline (a ~ 0.012), NOT the gentle
    a=0.15 M57 used -- otherwise the rim is crushed to black and rim_lum collapses (a
    direct violation of the "keep rim_lum within ~15% of baseline" rule).
  * Every mask ramp must be RE-SCALED DOWN by an order of magnitude into the faint
    regime (rim stretched-lum ~0.001-0.04), or the signal gate is identically 0 over
    the whole rim and the curve degenerates to the baseline.

The win condition on NGC6888 is SHELL COLOR RETENTION (keep the H-alpha-red rim + the
OIII-teal honest, multi-hue, instead of a flat single-hue cast or a white-blown rim),
NOT faint structure lift.

The win condition on M57 is RING COLOR RETENTION (keep the OIII-teal body + H-alpha-red
rim instead of blowing it toward white), not faint lift.  So the curve's masking
machinery (the part that made it special on M51 -- a robust sky-protect region mask +
a signal mask + highlight protection) is re-pointed to drive TWO things:

  (1) STRUCTURE-GATED CHROMA ENHANCEMENT (the primary M57 engine).
      A pure luminance unsharp mask does NOT raise chroma -- it raises luminance
      contrast.  And on M57's tiny bright ring a small-radius unsharp mask is exactly
      the deconv-ringing trap (dark-moat / bright-halo around the rim).  So the main
      lever here is a hue-faithful *colour* boost: out = L + cgain*(rgb - L), applied
      ONLY where the masks say there is real ring/cavity signal.  Because it scales the
      colour difference about the luminance, it leaves luminance UNTOUCHED -> it cannot
      create a dark moat or halo (a luminance artifact), and the harness's fixed
      saturation pass then carries the expanded per-channel spread through.  The sky
      (region mask ~ 0) is left bit-for-bit at the baseline, so neither luminance NOR
      colour noise in the background is amplified.

  (2) A CONSERVATIVE, CAPPED, HIGHLIGHT-PROTECTED LUMINANCE MICRO-CONTRAST (the
      namesake).  A SMALL-scale band-pass D = G(L,s_struct) - G(L,s_reg) on the few-px
      ring structure, soft-capped (dcap*tanh) to forbid overshoot, gated by the same
      signal/region masks AND a highlight-protection term, then transferred to colour by
      the luminance ratio.  Tuned LIGHT on purpose: enough to crisp the ring/cavity edge
      without ringing it.  lc_amount=0 disables it entirely (chroma-only mode), which is
      the safest operating point and already beats the baseline.

Real math (published equations, not guessed):
  * Global base:  asinh stretch   f(x) = asinh(x/a) / asinh(1/a)   (the baseline family).
  * Hue-preserving saturation/chroma boost about luminance:  the standard
    out = L + s*(rgb - L)  used by every saturation control (here gated by a mask).
  * Local contrast = large-radius unsharp / band-pass:  out = L + amount*(L - blur(L)),
    band-pass form D = G(L,s_in) - G(L,s_out) to pick the feature scale and exclude the
    noise scale (a-trous / multiscale wavelet idea); soft-cap tanh limits edge overshoot
    (the published halo fix); region/signal/highlight masks are the PixInsight-LHE
    "protect the background, spare the bright cores" rules done robustly on the
    large-scale neighbourhood so a single bright noise pixel can't fool them.

Params:
  a         asinh softening.  PINNED to the baseline (a=0.012) on NGC6888 so the faint rim
            is not crushed -- this curve does NOT win on luminance, only on chroma, so the
            luminance must match the baseline exactly (rim_lum, sky_noise_lum unchanged).
  cgain     structure-gated chroma gain (>1 expands shell colour).  The primary NGC6888
            lever; pushed to ~2.0 here because the tight sky-null gate (see rlo/rhi) costs
            some rim coverage that the higher gain recovers.  Hue-faithful: it expands the
            colour spread about luminance, so red and teal rise together -- it cannot flip
            a pixel's dominant hue or manufacture a single-hue cast.
  lc_amount luminance micro-contrast gain on the capped band-pass detail.  0 disables
            (chroma-only).  Keep LIGHT -- it is the ring-ringing risk.
  s_struct  inner blur sigma (frac of short axis): the few-px ring structure scale.
  s_reg     outer blur sigma (frac of short axis): the ring NEIGHBOURHOOD scale; the
            region mask is built from this.  Must stay SMALL (~ring size) so the mask
            lights up tightly on the ring+cavity and stays 0 on the sky/outer halo.
  dcap      soft-cap on the micro-contrast detail (halo / overshoot guard); <=0 disables.
  rlo,rhi   region-mask ramp on the outer-blur neighbourhood (sky+halo protect fade-in).
            Re-scaled an order of magnitude down for NGC6888's faint regime AND set TIGHT
            (rlo~0.013): the metric's sky annulus (r=320-500) overlaps the nebula's outer
            wisps (outer-blur Lo there reaches ~0.017, same as the rim), so a loose ramp
            leaks the chroma boost onto the sky and lifts sky_noise_chroma above baseline.
            rlo>=0.013 nulls that annulus while still fully passing the bright rim filaments.
            (M57 used a ramp at ~[0.05,0.12]; that scale zeroes the entire NGC6888 rim.)
            and fully passes the ring/cavity.
  mlo,mhi   signal-mask ramp in stretched-luminance units (faint fade-in / sky reject).
  hi_prot   highlight-protection exponent for the luminance micro-contrast only.
"""
import numpy as np
from scipy.ndimage import gaussian_filter


def _asinh(x, a):
    return np.arcsinh(x / a) / np.arcsinh(1.0 / a)


def _smoothstep(x, lo, hi):
    # C1 Hermite ramp 0..1 across [lo,hi]; flat outside.
    if hi <= lo:
        return (x >= hi).astype(np.asarray(x).dtype)
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def apply(x, a=0.012, cgain=2.0, lc_amount=0.0, s_struct=0.004, s_reg=0.020,
          dcap=0.02, rlo=0.013, rhi=0.030, mlo=0.013, mhi=0.032, hi_prot=2.0):
    x = np.clip(x, 0.0, 1.0)
    H, W = x.shape[0], x.shape[1]

    # --- global asinh base (same family as the baseline) ---
    y = _asinh(x, a)                      # (H,W,3) stretched colour
    Lin = y.mean(-1)                      # stretched luminance (H,W)

    ref = float(min(H, W))
    s1 = max(s_struct * ref, 0.6)
    s2 = max(s_reg * ref, s1 + 1e-3)

    # Degenerate / tiny inputs (e.g. the selftest 4x256 ramp): the masks/band-pass add
    # nothing on a smooth gradient -> fall back to the pure global curve, which keeps the
    # selftest monotonic and in-range.
    if H < 8 or W < 8 or s2 < 1.0:
        return np.clip(y, 0.0, 1.0)

    # --- masks built from the small-scale ring neighbourhood (M57 scale) ---
    Li = gaussian_filter(Lin, s1, mode="nearest")    # ring structure scale (denoised)
    Lo = gaussian_filter(Lin, s2, mode="nearest")    # ring NEIGHBOURHOOD (sky/halo gate)
    m_reg = _smoothstep(Lo, rlo, rhi)                # SKY+HALO-PROTECT: 0 over background
    m_sig = _smoothstep(Lin, mlo, mhi)               # faint fade-in / sky reject
    sig_gate = m_reg * m_sig                         # "real ring/cavity signal" mask

    # --- (1) structure-gated CHROMA enhancement (primary): leaves luminance untouched,
    #         so it cannot create a dark moat / halo; sky (gate~0) stays at baseline. ---
    if cgain != 1.0:
        lum = y.mean(-1, keepdims=True)
        boost = 1.0 + (float(cgain) - 1.0) * sig_gate[..., None]
        y = np.clip(lum + (y - lum) * boost, 0.0, 1.0)

    # --- (2) conservative luminance MICRO-CONTRAST (namesake), capped + hi-protected ---
    if lc_amount and lc_amount > 0.0:
        L2 = y.mean(-1)
        detail = gaussian_filter(L2, s1, mode="nearest") - gaussian_filter(L2, s2, mode="nearest")
        if dcap and dcap > 0.0:                       # soft-cap: overshoot / halo guard
            detail = float(dcap) * np.tanh(detail / float(dcap))
        m_hi = np.clip(1.0 - Li, 0.0, 1.0) ** float(hi_prot)   # spare the brightest knots
        gate = sig_gate * m_hi
        Lnew = np.clip(L2 + float(lc_amount) * detail * gate, 0.0, 1.0)
        ratio = (Lnew / (L2 + 1e-6))[..., None]       # hue-preserving luminance transfer
        y = np.clip(y * ratio, 0.0, 1.0)

    return np.clip(y, 0.0, 1.0)


DEFAULTS = {"a": 0.012, "cgain": 2.0, "lc_amount": 0.0, "s_struct": 0.004, "s_reg": 0.020,
            "dcap": 0.02, "rlo": 0.013, "rhi": 0.030, "mlo": 0.013, "mhi": 0.032, "hi_prot": 2.0}

# Sweep around the NGC6888 operating point.  The base a is PINNED to the baseline (a=0.012)
# so the curve cannot dim the already-faint H-alpha rim (the "rim_lum within ~15%" rule);
# the live lever is the structure-gated chroma gain cgain.  All points are chroma-ONLY
# (lc_amount=0): the rim here sits at/under the sky noise floor, so a luminance band-pass
# would ring the filaments and lift sky noise -- exactly what the goal forbids.  The chroma
# engine leaves luminance untouched, so rim_lum and sky_noise_lum stay AT baseline by
# construction; only rim_chroma moves.  The ramps are re-scaled an order of magnitude down
# from M57 into this faint regime (rim stretched-lum ~0.007-0.04).  Two ramp tightnesses are
# swept (looser = more rim coverage but a touch of sky gate; tighter = sky bit-clean) to find
# the honest knee where rim_chroma rises without sky_noise_chroma climbing above baseline.
# IMPORTANT regime note: NGC6888's outer wisps bleed into the metric's "sky" annulus
# (r=320-500 px), so a loose mask ramp leaks the chroma boost onto that annulus and pushes
# sky_noise_chroma ABOVE baseline (0.0158) -- a goal violation -- even though luminance and
# rim_clip stay clean.  The fix is a TIGHT ramp on the outer-blur neighbourhood (rlo>=0.013)
# that nulls the sky annulus while still fully passing the bright rim filaments; the chroma
# gain is then pushed harder (cgain up to 2.4) to recover the rim_chroma win that the tighter
# gate would otherwise cost.  All points are chroma-only (lc_amount=0): the rim sits at/under
# the sky noise floor, so a luminance band-pass would ring it and lift sky_noise_lum.
SWEEP = [
    # safe floor: tight ramp, modest gain -> sky_noise_chroma AT baseline, small honest rim win
    {"a": 0.012, "cgain": 1.55, "lc_amount": 0.0, "s_struct": 0.004, "s_reg": 0.020, "dcap": 0.02, "rlo": 0.013, "rhi": 0.030, "mlo": 0.013, "mhi": 0.032, "hi_prot": 2.0},
    # PRIMARY: tight sky-clean ramp + strong gain -> best rim_chroma at ~baseline sky chroma
    {"a": 0.012, "cgain": 2.00, "lc_amount": 0.0, "s_struct": 0.004, "s_reg": 0.020, "dcap": 0.02, "rlo": 0.013, "rhi": 0.030, "mlo": 0.013, "mhi": 0.032, "hi_prot": 2.0},
    # push gain harder with an even tighter ramp -> rim win held, sky chroma == baseline
    {"a": 0.012, "cgain": 2.40, "lc_amount": 0.0, "s_struct": 0.004, "s_reg": 0.020, "dcap": 0.02, "rlo": 0.016, "rhi": 0.036, "mlo": 0.016, "mhi": 0.038, "hi_prot": 2.0},
    # very strong gain, tightest ramp -> sky bit-clean, rim still well above baseline
    {"a": 0.012, "cgain": 2.00, "lc_amount": 0.0, "s_struct": 0.004, "s_reg": 0.020, "dcap": 0.02, "rlo": 0.018, "rhi": 0.040, "mlo": 0.018, "mhi": 0.042, "hi_prot": 2.0},
    # mid gain, mid ramp -> intermediate operating point
    {"a": 0.012, "cgain": 1.80, "lc_amount": 0.0, "s_struct": 0.004, "s_reg": 0.020, "dcap": 0.02, "rlo": 0.013, "rhi": 0.030, "mlo": 0.013, "mhi": 0.032, "hi_prot": 2.0},
    # conservative reference
    {"a": 0.012, "cgain": 1.40, "lc_amount": 0.0, "s_struct": 0.004, "s_reg": 0.020, "dcap": 0.02, "rlo": 0.013, "rhi": 0.030, "mlo": 0.013, "mhi": 0.032, "hi_prot": 2.0},
]
