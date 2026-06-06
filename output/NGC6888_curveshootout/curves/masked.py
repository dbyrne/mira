"""masked -- dual / masked stretch (SPATIAL), re-tuned for NGC6888 rim-colour retention.

Idea (standard PixInsight "luminance-masked stretch" practice, made rigorous):
build a brightness mask from luminance, blend two per-channel tone curves -- a
contrast-amplifying curve on the body of the signal and a GENTLE curve on the
brightest highlights -- so the bright structure keeps its colour and does not
blow to white.

REGIME (NGC6888, Crescent Nebula -- chroma mode, but NOT the M57 planetary regime):
M57 was a BRIGHT compact ring (rim at x~0.16 in the harness-normalized frame).
NGC6888 is a LARGE, FAINT emission nebula: after the harness black-point + 99.99pct
white-normalize, the entire crescent rim lives in the DEEP SHADOWS --
  rim lum median ~0.0004, p90 ~0.0027, p99 ~0.015  (vs M57 rim ~0.16),
  sky floor ~0.00007, halo ~0.0001.
Per-channel rim medians: R 0.00046, G 0.00036, B 0.00048 -- i.e. R and B both sit
ABOVE G (Ha-red + OIII-teal, with the green channel as the trough). The chroma we
want to keep is that R>G and B>G separation, all living at x ~ 0.0003-0.005.

So unlike M57 (SP placed UP in the bright ring body) here the GHS symmetry point SP
belongs DOWN AT THE RIM SIGNAL BAND ~0.001-0.002, where the curve's maximum slope
falls exactly across the per-channel rim values and stretches the R/B-over-G
separation -> higher rim chroma after the x1.9 saturation. The knee sharpness B is
the real lever in this faint regime: a sharper hyperbolic knee (B~4) concentrates
more slope into the narrow rim band, so at a given rim brightness the per-channel
spread is larger.

HONEST FRONTIER FINDING (this is the M51/M57 lesson restated for a faint nebula):
A GLOBAL tone curve cannot raise the chroma-per-luminance EFFICIENCY (rim_chroma /
rim_lum) above the asinh baseline in this faint-dominated regime -- the data sets
that ratio (~1.14), and asinh sits on the frontier. The sky chroma/lum noise lives
in the SAME low-x band as the rim signal (sky p99 ~0.01 overlaps the rim), so there
is no LP/foot trick that suppresses sky without also flattening the rim. The only
honest headroom is the small rim_lum tolerance (~15%): a sharp-knee GHS with SP in
the rim band buys a few % more ABSOLUTE rim_chroma by lifting the rim a few % AND
keeping BOTH sky-noise stats at/under baseline (the GHS slope at the true sky floor
x~0.00007 is shallower than asinh's, so sky stays quiet). That is a real, gated win
-- not a chroma-efficiency miracle. Pushing D/B harder only rides higher rim_lum and
then breaches the sky-noise gates (all from faint field stars in the annulus, not
sky mottle), so those rows are mapped but do NOT count as clean wins.

  faint_strength      -> GHS stretch intensity D (rim contrast/chroma gain)
  b                   -> GHS local stretch intensity (hyperbolic knee sharpness, >0)
  sp                  -> GHS symmetry point (where slope peaks; put IN the rim band ~0.001-0.002)
  lp                  -> GHS shadow-protection point (x<lp is linear; tiny, sits below the rim)
  hp                  -> GHS highlight-protection point (slope rolls off above this -> no blow)
  highlight_strength  -> asinh softening 'a' for the gentle highlight curve (larger=gentler)
  mask_thresh         -> luminance at which mask = 0.5 (amplifier<->gentle crossover)
  mask_soft           -> width of the smooth mask transition (logistic scale)
"""
import numpy as np

# Best FEASIBLE set (all hard gates met vs asinh a=0.012 baseline: rim_chroma 0.0225,
# rim_lum 0.0197, sky_noise_lum 0.0378, sky_noise_chroma 0.0158, rim_clip 0.0003):
#   D=13, B=4, SP=0.001, HP=0.45 -> rim_chroma 0.0236 (+4.9%), rim_lum 0.0209
#   (+6.1%, well inside the 15% tolerance), rim_clip 0.0003 (==baseline, ~0),
#   sky_noise_lum 0.0375 (<0.0378), sky_noise_chroma 0.0157 (<0.0158),
#   center_chroma ~0.038. SP sits in the rim signal band so the sharp B=4 knee
#   stretches the R/B-over-G teal/Ha separation across the crescent; HP rolls the
#   bright-star tail off; the gentle asinh + mask hand the brightest stars to a
#   soft curve so rim_clip stays ~0. Both sky-noise gates strictly below baseline.
DEFAULTS = {
    "faint_strength": 13.0,
    "b": 4.0,
    "sp": 0.001,
    "lp": 0.0,
    "hp": 0.45,
    "highlight_strength": 0.45,
    "mask_thresh": 0.30,
    "mask_soft": 0.10,
}

# 6 sets: a ladder in rim-chroma gain along the SP-in-the-rim-band axis. Rows 1-3 are
# at/under the hard sky-noise gates (row 3 == the DEFAULTS frontier point, the
# recommended pick). Rows 4-6 push D/B harder for higher absolute rim_chroma but
# breach sky_noise_lum / sky_noise_chroma (the extra noise is faint annulus FIELD
# STARS, not sky mottle) -- mapped to show the frontier, NOT clean wins. Every row
# keeps the steep part AT the rim band and SP below it, so rim_clip stays ~0.
# mask_thresh/soft are normalized LUMINANCE.
SWEEP = [
    {"faint_strength": 11.0, "b": 4.0, "sp": 0.001, "lp": 0.0, "hp": 0.45, "highlight_strength": 0.45, "mask_thresh": 0.30, "mask_soft": 0.10},
    {"faint_strength": 12.0, "b": 4.0, "sp": 0.001, "lp": 0.0, "hp": 0.45, "highlight_strength": 0.45, "mask_thresh": 0.30, "mask_soft": 0.10},
    {"faint_strength": 13.0, "b": 4.0, "sp": 0.001, "lp": 0.0, "hp": 0.45, "highlight_strength": 0.45, "mask_thresh": 0.30, "mask_soft": 0.10},
    {"faint_strength": 14.0, "b": 4.0, "sp": 0.001, "lp": 0.0, "hp": 0.45, "highlight_strength": 0.45, "mask_thresh": 0.30, "mask_soft": 0.10},
    {"faint_strength": 16.0, "b": 4.0, "sp": 0.002, "lp": 0.0, "hp": 0.45, "highlight_strength": 0.45, "mask_thresh": 0.30, "mask_soft": 0.10},
    {"faint_strength": 16.0, "b": 8.0, "sp": 0.002, "lp": 0.0, "hp": 0.45, "highlight_strength": 0.45, "mask_thresh": 0.30, "mask_soft": 0.10},
]


def _ghs_hyperbolic(z, D, B, SP, LP, HP):
    """Exact GHS forward transform, hyperbolic branch (b>0), vectorized.

    Mirrors mikec1485/GHS lib/GHSStretch.js coefficient derivation (5d) and the
    piecewise forward evaluation (section 5, B != -1 && B != 0).  D!=0, B>0,
    0<=LP<=SP<=HP<=1.  z in [0,1] -> y in [0,1].
    """
    # --- normalization constants (q-values) ---
    qlp = (1.0 + D * B * (SP - LP)) ** (-1.0 / B)
    q0 = qlp - D * LP * (1.0 + D * B * (SP - LP)) ** (-(1.0 + B) / B)
    qwp = 2.0 - (1.0 + D * B * (HP - SP)) ** (-1.0 / B)
    q1 = qwp + D * (1.0 - HP) * (1.0 + D * B * (HP - SP)) ** (-(1.0 + B) / B)
    q = 1.0 / (q1 - q0)

    # --- piecewise coefficients ---
    # x < LP : linear
    a1 = 0.0
    b1 = D * (1.0 + D * B * (SP - LP)) ** (-(1.0 + B) / B) * q
    # LP <= x < SP
    a2 = -q0 * q
    b2 = q
    c2 = 1.0 + D * B * SP
    d2 = -D * B
    e2 = -1.0 / B
    # SP <= x <= HP
    a3 = (2.0 - q0) * q
    b3 = -q
    c3 = 1.0 - D * B * SP
    d3 = D * B
    e3 = -1.0 / B
    # x > HP : linear
    a4 = (qwp - q0 - D * HP * (1.0 + D * B * (HP - SP)) ** (-(B + 1.0) / B)) * q
    b4 = D * (1.0 + D * B * (HP - SP)) ** (-(B + 1.0) / B) * q

    z = np.clip(z, 0.0, 1.0)
    y = np.empty_like(z)

    m_lo = z < LP
    m_mid1 = (z >= LP) & (z < SP)
    m_mid2 = (z >= SP) & (z <= HP)
    m_hi = z > HP

    y[m_lo] = a1 + b1 * z[m_lo]
    # power-form branches; bases are guaranteed positive by construction for z in range
    base2 = np.maximum(c2 + d2 * z[m_mid1], 1e-12)
    y[m_mid1] = a2 + b2 * base2 ** e2
    base3 = np.maximum(c3 + d3 * z[m_mid2], 1e-12)
    y[m_mid2] = a3 + b3 * base3 ** e3
    y[m_hi] = a4 + b4 * z[m_hi]
    return y


def _gentle_asinh(z, a):
    """Mild asinh highlight curve -- gentle on cores, never clips."""
    return np.arcsinh(z / a) / np.arcsinh(1.0 / a)


def apply(x, faint_strength=13.0, b=4.0, sp=0.001, lp=0.0, hp=0.45,
          highlight_strength=0.45, mask_thresh=0.30, mask_soft=0.10):
    x = np.clip(x, 0.0, 1.0)
    lum = x.mean(-1)  # (H, W) brightness field for the mask

    # Strong faint curve (GHS hyperbolic) and gentle highlight curve (mild asinh),
    # each applied per-channel to preserve colour.
    D = float(faint_strength)
    B = max(float(b), 1e-3)
    SP = float(np.clip(sp, 1e-4, 0.95))
    LP = float(np.clip(lp, 0.0, SP - 1e-5)) if SP > 1e-5 else 0.0
    HP = float(np.clip(hp, SP + 1e-3, 1.0))
    faint = _ghs_hyperbolic(x, D, B, SP, LP, HP)
    highlight = _gentle_asinh(x, max(float(highlight_strength), 1e-3))

    # Brightness mask: 1 where faint (use the strong curve), 0 where bright
    # (use the gentle curve).  Smooth logistic crossover at mask_thresh with
    # width mask_soft, computed from luminance so all 3 channels blend together
    # (no colour fringing at the boundary).
    soft = max(float(mask_soft), 1e-4)
    w_faint = 1.0 / (1.0 + np.exp((lum - float(mask_thresh)) / soft))
    w_faint = w_faint[..., None]  # broadcast over channels

    y = w_faint * faint + (1.0 - w_faint) * highlight
    return np.clip(y, 0.0, 1.0)
