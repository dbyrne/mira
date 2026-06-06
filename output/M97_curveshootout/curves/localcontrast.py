"""localcontrast -- global asinh + structure-gated local enhancement (M97 edition).

ORIGIN: ported from the M51 faint-galaxy run (large-radius masked unsharp mask to lift
M51's outer arms), then re-pointed to M57 (a TINY BRIGHT planetary).  M97 -- the Owl
Nebula -- is a THIRD regime: a LARGE, FAINT, DIFFUSE planetary (~3.4', ~56 px on the S30
at 3.67"/px) dominated almost entirely by OIII (teal); the two dark "owl-eye" cavities
sit inside a soft round disk with NO sharp ring edge.  So the same MATH is re-pointed
again and the params re-tuned.  See "What changed for M97" at the bottom.

The win condition on M97 is DISK COLOR DEPTH -- deepen the existing OIII-teal across the
soft disk -- without blowing the disk toward white, dimming it, or mottling the sky.
Two big differences from M57 drove the re-tune:

  * The base stretch is AGGRESSIVE (a=0.03, matching the M97 baseline) because the disk
    is faint and diffuse -- M57's gentle a=0.15 would leave the Owl buried.  Pinning a to
    the baseline also keeps the SKY bit-for-bit identical to the baseline (the masks are
    0 over background), so sky_noise_lum / sky_noise_chroma never rise above baseline.
  * The luminance MICRO-CONTRAST namesake is DISABLED by default (lc_amount=0).  M97 has
    no sharp ring edge for a band-pass to crisp; on this diffuse disk the band-pass only
    SUBTRACTS halo brightness (lowering halo_contrast) and nudges rim_lum toward the
    ceiling -- a dim-and-no-gain trade.  lin_halo_snr is tiny here, so per the brief we do
    NOT chase halo_contrast.  The honest, dominant lever is pure structure-gated CHROMA.

So the masking machinery (the part that made it special on M51 -- a robust sky-protect
region mask + a signal mask + highlight protection) is re-pointed to drive TWO things:

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
  rlo,rhi   region-mask ramp on the outer-blur neighbourhood (sky-protect fade-in).
            Placed at M97's scale (measured on this frame at a=0.03): the disk
            neighbourhood blurs to ~0.20-0.23, the faint outer disk/halo to ~0.087, the
            sky to ~0.016 -> a ramp in [0.04, 0.10] NULLS the sky (0.016 < 0.04 -> mask=0,
            so sky stays bit-for-bit at baseline) while FULLY passing the disk AND most of
            the Owl's outer teal halo (0.087 -> mask ~0.6, deepening that color too).
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


def apply(x, a=0.03, cgain=1.70, lc_amount=0.0, s_struct=0.0015, s_reg=0.006,
          dcap=0.03, rlo=0.04, rhi=0.10, mlo=0.02, mhi=0.10, hi_prot=2.0):
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


DEFAULTS = {"a": 0.03, "cgain": 1.70, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006,
            "dcap": 0.03, "rlo": 0.04, "rhi": 0.10, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0}

# Sweep around the M97 operating point.  The base a is PINNED to the baseline (a=0.03) so
# the SKY is bit-for-bit identical to asinh a=0.03 (masks are 0 over background) -> sky
# noise can never rise.  The live lever is the chroma gain cgain.  All points are
# chroma-only (lc_amount=0): M97's diffuse disk has no sharp edge, so the luminance
# micro-contrast only dims the halo and pushes rim_lum toward the +15% ceiling without an
# honest structural gain (lin_halo_snr is tiny -- not worth chasing).  The cgain ceiling
# is set by the rim_lum guard: cgain=2.2 -> rim_lum 0.334 (baseline 0.292, +14.5%, just
# under the +15% cap); by eye the disk starts to look electric past ~2.0, so the DEFAULT
# sits at a confident, natural 1.70 (+57% rim_chroma, rim_lum only +5%).
SWEEP = [
    # cgain=1.0 -> EXACTLY the baseline (cgain=1, lc=0 collapses to asinh a=0.03).  Anchor.
    {"a": 0.03, "cgain": 1.00, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.04, "rhi": 0.10, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # conservative deepening
    {"a": 0.03, "cgain": 1.40, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.04, "rhi": 0.10, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # the natural sweet spot (DEFAULT): strong color, rim_lum barely moved
    {"a": 0.03, "cgain": 1.70, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.04, "rhi": 0.10, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # a touch richer, still natural by eye
    {"a": 0.03, "cgain": 1.90, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.04, "rhi": 0.10, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # near the rim_lum ceiling -- metric-max, starts to look electric (kept for the panel)
    {"a": 0.03, "cgain": 2.20, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.04, "rhi": 0.10, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
    # wider region mask (rhi=0.14) -> deepen the Owl's outer teal halo a bit more too
    {"a": 0.03, "cgain": 1.70, "lc_amount": 0.0, "s_struct": 0.0015, "s_reg": 0.006, "dcap": 0.03, "rlo": 0.04, "rhi": 0.14, "mlo": 0.02, "mhi": 0.10, "hi_prot": 2.0},
]
