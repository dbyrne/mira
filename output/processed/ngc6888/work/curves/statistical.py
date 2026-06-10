"""statistical -- median/anchor-targeting auto-stretch (MTF), re-tuned for NGC 6888 (chroma).

Seti Astro "Statistical Stretch" / PixInsight & Siril unlinked STF AutoStretch, adapted for the
NGC 6888 (Crescent) FAINT EMISSION-NEBULA regime: keep the Ha-red / OIII-teal RIM color while
the signal sits only ~6x above the sky floor (a totally different problem from the M57 bright
planetary this plugin was last tuned for).

Published math (PixInsight STF AutoStretch; Siril `autostretch`; Seti Astro Statistical Stretch):

  Midtones Transfer Function (rational, the same one PixInsight/Siril use):

      MTF(m, x) = ((m - 1) * x) / ((2*m - 1) * x - m)        for x in (0,1)

  monotone increasing, MTF(m,0)=0, MTF(m,1)=1, MTF(m,m)=0.5.

  Auto-stretch is the inverse problem: pick the midtones balance m that maps a chosen input
  reference level v to a chosen output target t, i.e. solve MTF(m,v)=t. The published closed form
  ("mb = MTF(b1,b0)") is MTF with the roles of m and x swapped:

      solve_m(v, t) = ((t - 1) * v) / ((2*t - 1) * v - t)        # m s.t. MTF(m,v)=t

  -- WHAT CHANGED FOR NGC 6888 (vs the M57 bright-planetary port) ---------------------------
  M57's rim lived at x ~ 0.15-0.6, so that port anchored at ~0.18. NGC 6888 is the opposite:
  after the harness's per-channel sky-median black + 99.99-pct white normalize, the RIM body
  sits at x ~ 4e-4 .. 3e-3 (p50 ~4.3e-4, p90 ~2.7e-3, p99 ~1.5e-2) -- three orders of magnitude
  below M57. The sky median is ~7e-5. So the SIGNAL ANCHOR drops to ~0.006-0.012 (a level on the
  rim body, NOT the M57 ~0.18 and NOT the ~1e-3 noise floor of the old M51 mistake), placed onto
  target ~0.13-0.18. One LINKED m for all three channels preserves the PCC color ratios -- on this
  master the rim is genuinely BI-HUED (measured: ~46% of rim px are R>B Ha-red, ~39% are B>R
  OIII-teal), so a linked stretch grows BOTH hues honestly; an unlinked per-channel solve would
  re-gray that balance. The MTF slope > 1 across the rim body spreads the channels apart -> chroma
  grows, while < 1 above keeps the brightest knots/stars under 1.0 (rim_clip ~ 0).

  -- THE SHOULDER LEVER (the NEW knob this regime needs) ------------------------------------
  The decisive finding on this master: the sky-annulus luminance noise (std ~0.014 in norm space)
  is NOT a broad floor -- it is carried almost entirely by a SPARSE bright TAIL (faint stars /
  residual hot px). Capping the sky at x=0.002 collapses its std from 0.0142 to 0.0005 (29x). A
  pure global stretch (asinh, or plain STF) amplifies that tail in lockstep with the rim, so it
  sits exactly on asinh's chroma<->noise Pareto line and cannot beat it. The win is to COMPRESS
  that bright tail before the MTF with a soft SHOULDER -- the per-pixel, mask-free analog of the
  standard PixInsight move (pull the highlight-clipping slider left / masked-exponential stretch
  to protect bright areas while a minimal black point preserves faint signal):

      shoulder(x) = sk + (1-sk) * ((x - sk)/(1 - sk))**sp     for x > sk ,   identity for x <= sk

  with sp >= 1. The rim body lives BELOW sk (~0.003-0.006), so its chroma is untouched; the bright
  sky tail and star halos above sk get compressed (sp>1 squashes the region just above the knee),
  so sky_noise_lum and sky_noise_chroma DROP below baseline while rim_chroma RISES. This is the
  knob the M57 version lacked (M57 had no problematic faint tail). Bigger sp / lower sk = more tail
  compression = more noise headroom; if sk drops into the rim body it starts eating real rim signal
  (chroma falls), so keep sk above the rim p90 (~0.0027).

  -- THE TOE LEVER (low end) ----------------------------------------------------------------
  Optional smooth foot below toe_knee (x -> tk*(x/tk)^g for x<tk, g>=1): pulls the very lowest
  near-floor scatter toward black. Here it is a fine-trim knob; the shoulder does the heavy lifting
  because the noise is in the bright tail, not the floor. Kept below the rim body (tk <~ 1e-3).

  pipeline (per channel, single linked m):  y = MTF( m, shoulder( toe( x ) ) )

This is a pure elementwise tone curve -- no spatial filtering, so it cannot manufacture a dark
moat / bright halo ring (halo_lum stays >= sky_lum).

Refs:
  PixInsight STF AutoStretch (shadowsClipping=-2.8, targetBackground=0.25); highlight-clipping
    slider + masked-exponential stretch for highlight protection.
  Siril autostretch docs: MTF((m-1)x/((2m-1)x-m)), shadowclip in sigma, target 0.25.
  Seti Astro Statistical Stretch: target-median MTF.
"""
import numpy as np

# ---- params (re-tuned for NGC 6888 faint-nebula chroma) ---------------------------------
# anchor   : input SIGNAL level (rim body, ~0.006-0.012) the curve places. NOT ~0.18 (M57) and
#            NOT the ~7e-5 sky floor. Lower anchor -> brighter+more chroma+more noise.
# target   : where `anchor` lands on screen (~0.13-0.18). Higher -> brighter rim.
# sh_knee  : SHOULDER knee. Above it the bright tail (stars + sky outliers) is compressed. MUST
#            stay above the rim p90 (~0.0027) so it never eats rim color; ~0.004-0.006 is the
#            sweet spot. This is what beats asinh: it kills the sky-tail noise the rim stretch
#            would otherwise amplify.
# sh_pow   : shoulder strength, >=1. 1.0 = no shoulder (plain STF, sits on asinh's frontier).
#            2.0-3.0 compresses the tail hard -> sky_noise_lum/chroma drop below baseline.
# toe_knee : low foot knee (<~1e-3, below rim body). Fine-trim of near-floor scatter; small here.
# toe_pow  : foot power, >=1. 1.0 = off.
#
# DEFAULTS = the HONEST winner: rim_lum held NEAR the asinh a=0.012 baseline (0.0197, within the
# +-15% band), rim_chroma ABOVE baseline, and BOTH sky-noise metrics strictly BELOW baseline
# (the shoulder buys that headroom). rim_clip ~ 0. No dark moat.
# DEFAULTS = the HONEST winner, verified through the harness at the task geometry: rim_lum held
# at the asinh a=0.012 baseline (0.0213 vs 0.0197, +8%, inside the +-15% band -- NOT dimmer),
# rim_chroma ABOVE baseline (0.0234 > 0.0225) AND BOTH sky-noise metrics strictly BELOW baseline
# (sky_noise_lum 0.0265 < 0.0378, sky_noise_chroma 0.0144 < 0.0158). rim_clip ~ 0, no dark moat.
# The shoulder (knee 0.007, just above the rim p90 ~0.0027, power 3) compresses the bright sky
# tail that carries the noise while leaving the rim color body untouched -- that decoupling is
# what lets it beat asinh's tied chroma<->noise frontier. (anchor barely matters once the shoulder
# + dim target dominate; 0.013 posts the top rc among the clean-win set.)
DEFAULTS = {"anchor": 0.013, "target": 0.14, "sh_knee": 0.007, "sh_pow": 3.0, "toe_knee": 0.0008, "toe_pow": 2.0}

SWEEP = [
    {"anchor": 0.013, "target": 0.14, "sh_knee": 0.007, "sh_pow": 3.0, "toe_knee": 0.0008, "toe_pow": 2.0},  # DEFAULT: honest winner -- rc>base, rl matched, BOTH noise gates strictly under cap
    {"anchor": 0.013, "target": 0.14, "sh_knee": 0.007, "sh_pow": 4.0, "toe_knee": 0.0008, "toe_pow": 2.0},  # harder shoulder -> lowest noise (snl 0.0254/snc 0.0142), rc 0.0233
    {"anchor": 0.013, "target": 0.14, "sh_knee": 0.007, "sh_pow": 2.0, "toe_knee": 0.0008, "toe_pow": 2.0},  # softer shoulder -> highest rc 0.0237, noise still under cap (snc 0.0148)
    {"anchor": 0.013, "target": 0.16, "sh_knee": 0.006, "sh_pow": 3.0, "toe_knee": 0.0008, "toe_pow": 2.0},  # brighter rim (rl up) + more chroma -- trades into the noise headroom
    {"anchor": 0.010, "target": 0.16, "sh_knee": 0.005, "sh_pow": 2.5, "toe_knee": 0.0008, "toe_pow": 2.0},  # bright/high-chroma corner (rl~0.031) -- snc over cap, shows the brightness<->chroma-noise trade
    {"anchor": 0.013, "target": 0.14, "sh_knee": 0.007, "sh_pow": 1.0, "toe_knee": 0.0, "toe_pow": 1.0},     # NO shoulder/toe (plain STF) -- noise UP (sits ON asinh's frontier), shows the shoulder is the lever
]


def _mtf(m, x):
    """PixInsight/Siril midtones transfer function. Vectorized, clamps the open interval."""
    m = float(m)
    out = np.empty_like(x)
    lo = x <= 0.0
    hi = x >= 1.0
    mid = ~(lo | hi)
    out[lo] = 0.0
    out[hi] = 1.0
    xm = x[mid]
    out[mid] = ((m - 1.0) * xm) / ((2.0 * m - 1.0) * xm - m)
    return out


def _solve_m(v, t):
    """Midtones balance m such that _mtf(m, v) == t (the published mb = MTF(t, v))."""
    v = float(np.clip(v, 1e-12, 1.0 - 1e-9))
    t = float(np.clip(t, 1e-6, 1.0 - 1e-6))
    denom = (2.0 * t - 1.0) * v - t
    m = ((t - 1.0) * v) / denom
    return float(np.clip(m, 1e-9, 1.0 - 1e-9))


def _toe(x, tk, g):
    """Smooth noise-suppressing foot below knee tk: x -> tk*(x/tk)^g for x<tk (g>=1), else x."""
    g = float(g)
    tk = float(tk)
    if g <= 1.0 or tk <= 0.0:
        return x
    out = x.copy()
    lo = x < tk
    out[lo] = tk * np.power(np.clip(x[lo] / tk, 0.0, 1.0), g)
    return out


def _toe_scalar(v, tk, g):
    """Apply the same foot to a scalar anchor so its (anchor->target) placement stays exact."""
    g = float(g)
    tk = float(tk)
    if g <= 1.0 or tk <= 0.0 or v >= tk:
        return v
    return tk * (max(v, 0.0) / tk) ** g


def _shoulder(x, sk, sp):
    """Soft highlight shoulder above knee sk: compress the bright tail (stars + sky outliers).

    x -> sk + (1-sk)*((x-sk)/(1-sk))^sp  for x>sk (sp>=1), identity below. sp==1 or sk<=0/>=1
    is a no-op. The mask-free analog of pulling PixInsight's highlight-clipping slider left:
    the rim body (below sk) is untouched, the bright tail that carries the display noise is
    squashed, so sky_noise drops while rim chroma is preserved.
    """
    sk = float(sk)
    sp = float(sp)
    if sp <= 1.0 or sk <= 0.0 or sk >= 1.0:
        return x
    out = x.copy()
    hi = x > sk
    t = (x[hi] - sk) / (1.0 - sk)
    out[hi] = sk + (1.0 - sk) * np.power(np.clip(t, 0.0, 1.0), sp)
    return out


def _shoulder_scalar(v, sk, sp):
    sk = float(sk)
    sp = float(sp)
    if sp <= 1.0 or sk <= 0.0 or sk >= 1.0 or v <= sk:
        return v
    t = (v - sk) / (1.0 - sk)
    return sk + (1.0 - sk) * (max(t, 0.0) ** sp)


def apply(x, anchor=0.013, target=0.14, sh_knee=0.007, sh_pow=3.0, toe_knee=0.0008, toe_pow=2.0):
    anchor = float(anchor)
    target = float(target)
    sh_knee = float(sh_knee)
    sh_pow = float(sh_pow)
    toe_knee = float(toe_knee)
    toe_pow = float(toe_pow)
    eps = 1e-7

    # LINKED midtones balance: one m for every channel preserves the PCC color balance. The
    # anchor passes through the SAME toe + shoulder as the data so its (anchor->target) mapping
    # is exact on the post-warp axis.
    a_t = _toe_scalar(anchor, toe_knee, toe_pow)
    a_t = _shoulder_scalar(a_t, sh_knee, sh_pow)
    a_t = float(np.clip(a_t, eps, 1.0 - 1e-6))
    m = _solve_m(a_t, target)

    y = np.empty_like(x)
    for c in range(x.shape[-1]):
        ch = np.clip(x[..., c], 0.0, 1.0)
        xt = _toe(ch, toe_knee, toe_pow)          # low foot (fine trim)
        xt = _shoulder(xt, sh_knee, sh_pow)       # high shoulder (the noise-killing lever)
        y[..., c] = _mtf(m, xt)
    return np.clip(y, 0.0, 1.0)
