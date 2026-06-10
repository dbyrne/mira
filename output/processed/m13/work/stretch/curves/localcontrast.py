"""localcontrast -- global asinh + structure-gated local enhancement (M57 edition).

ORIGIN: ported from the M51 faint-galaxy run, where this curve used a large-radius
masked unsharp mask on luminance to lift M51's outer arms + the M51<->NGC5195 bridge
above the sky.  M57 is a completely different regime -- a TINY BRIGHT PLANETARY -- so
the same MATH is re-pointed and the scale params are re-tuned.  See "What changed for
M57" at the bottom.

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
  a         asinh softening.  Set so the SKY noise sits at/under the baseline (a=0.15 is
            the baseline itself -> sky exactly at baseline; smaller a lifts sky noise).
  cgain     structure-gated chroma gain (>1 expands ring/cavity colour).  The primary
            M57 lever.  Keep moderate -- too high oversaturates into a flat colour cast.
  lc_amount luminance micro-contrast gain on the capped band-pass detail.  0 disables
            (chroma-only).  Keep LIGHT -- it is the ring-ringing risk.
  s_struct  inner blur sigma (frac of short axis): the few-px ring structure scale.
  s_reg     outer blur sigma (frac of short axis): the ring NEIGHBOURHOOD scale; the
            region mask is built from this.  Must stay SMALL (~ring size) so the mask
            lights up tightly on the ring+cavity and stays 0 on the sky/outer halo.
  dcap      soft-cap on the micro-contrast detail (halo / overshoot guard); <=0 disables.
  rlo,rhi   region-mask ramp on the outer-blur neighbourhood (sky+halo protect fade-in).
            Placed at M57's scale: ring neighbourhood blurs to ~0.11-0.18, halo to
            ~0.03-0.11, sky to ~0.001 -> a ramp in [~0.05, ~0.12] nulls sky+inner-halo
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


def apply(x, a=0.15, cgain=1.40, lc_amount=3.5, s_struct=0.0015, s_reg=0.006,
          dcap=0.03, rlo=0.05, rhi=0.12, mlo=0.02, mhi=0.10, hi_prot=2.0):
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


DEFAULTS = {"a": 0.15, "cgain": 1.40, "lc_amount": 3.5, "s_struct": 0.0015, "s_reg": 0.006,
            "dcap": 0.03, "rlo": 0.05, "rhi": 0.12, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0}

# Sweep around the M57 operating point.  The base a is pinned to where the SKY noise sits
# at/under the baseline (a=0.15); the live lever is the chroma gain cgain, with a couple of
# chroma-only points (lc_amount=0, the artifact-safe ones) and a couple with a LIGHT
# luminance micro-contrast for extra ring crispness.  The tight region mask (rlo=0.05,
# rhi=0.12) keeps the sky bit-for-bit at baseline across all of them.
SWEEP = [
    # chroma-only, conservative -> the safest clean win on rim_chroma (no luminance change)
    {"a": 0.15, "cgain": 1.30, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.05, "rhi": 0.12, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # chroma-only, moderate
    {"a": 0.15, "cgain": 1.45, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.05, "rhi": 0.12, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # chroma + light micro-contrast (the namesake; crisps the ring, no ringing)
    {"a": 0.15, "cgain": 1.35, "lc_amount": 2.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.05, "rhi": 0.12, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # chroma + slightly stronger micro-contrast
    {"a": 0.15, "cgain": 1.40, "lc_amount": 3.5, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.05, "rhi": 0.12, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # push chroma a touch (still natural), tiny micro-contrast
    {"a": 0.15, "cgain": 1.55, "lc_amount": 1.5, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.05, "rhi": 0.12, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # slightly softer base (a=0.13) -- nudges rim into a steeper curve region; verify sky
    {"a": 0.13, "cgain": 1.35, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.05, "rhi": 0.12, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
]
