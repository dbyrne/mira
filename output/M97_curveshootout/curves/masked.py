"""masked -- dual / masked stretch (SPATIAL), re-tuned for M97 (Owl) rim-colour retention.

Idea (standard PixInsight "luminance-masked stretch" practice, made rigorous):
build a brightness mask from luminance, blend two per-channel tone curves -- a
contrast-amplifying curve on the body of the signal and a GENTLE curve on the
brightest highlights -- so the bright structure keeps its colour and does not
blow to white.

For M51 (faint-galaxy regime) the strong curve was placed near the SKY to lift a
dim tidal bridge.  M57/M97 are a different problem: a PLANETARY where the win
is RING/DISK COLOUR RETENTION.  So the strong curve is re-conceived as a RIM CHROMA
AMPLIFIER, not a faint-lifter:

M97 (Owl) vs M57 (Ring) -- the SAME amplifier, RE-AIMED for a MUCH FAINTER, LOWER-
CONTRAST disk.  Probing the M97 harness-normalized master (per-channel sky-median
black + 99.99pct white) shows the Owl's rim body sits at lum ~0.049 (R0.027 G0.057
B0.065 -- OIII teal, B>G>>R), the central cavity ~0.053, halo ~0.006, sky ~0.001.
That is ~3x FAINTER than M57's rim (~0.16) and the whole signal lives in x~0.03-0.08.
Consequences for the re-tune vs the M57 numbers (which were SP~0.14, D~3):
  * SP (where GHS slope PEAKS) moves DOWN into the M97 rim body, ~0.03, just BELOW
    the rim's faintest (R) channel so the red floor is LIFTED, not crushed -- the
    M40+/SP0.045 variants drove R->0.000 (a single-hue OIII overdrive the chroma
    metric rewards but the EYE rejects as monochromatic-teal); SP0.03 keeps R~0.18
    so the disk reads as honest layered teal-with-warm-core, multi-hue.
  * D (stretch intensity) rises HARD (~22 vs M57's ~3) because the rim is so dim:
    to reach baseline rim_lum (~0.29) the curve must lift x~0.05 to display ~0.30,
    i.e. a steep low-end -- exactly what asinh a=0.03 does, but GHS concentrates
    that slope at SP and ROLLS OFF above HP so the brightest knots/stars don't blow.
  * HP (roll-off) ~0.16, above the rim tail+cavity so the disk body is amplified but
    field stars compress.  Mask crossover ~0.28 hands only the brightest stars to the
    gentle asinh.
Frontier finding (matched-rim_lum, eye-corroborated): D=22, B=5, SP=0.03, HP=0.16
gives rim_chroma 0.390 (+24.6% vs asinh a=0.03 baseline 0.3132) at rim_lum 0.297
(==baseline 0.292 within 1.8%), rim_clip 0, sky_noise_lum 0.0207 (<0.0292 baseline),
sky_noise_chroma 0.0195 (<0.0391 baseline -- the GHS slope at the sky floor x~0.001
is gentle, so sky is QUIETER than the asinh baseline despite +25% rim colour).  The
red floor survives so the teal is layered, not a flat single-hue wash.

(Historical M57 note retained for context.)
For M57 the strong curve was a RIM CHROMA AMPLIFIER:

The strong curve is the Generalised Hyperbolic Stretch (GHS, hyperbolic branch
b>0), implemented from the exact PixInsight GHS module math (mikec1485/GHS,
lib/GHSStretch.js, section 5d).  GHS concentrates its maximum *slope* at a chosen
"symmetry point" SP.  Placing SP IN THE RING BODY (M57 rim x ~0.16 in the
harness-normalized frame) makes the curve steepest exactly across the rim, which
stretches the per-channel separation (rim is B>G>R teal/H-a) -> HIGHER rim chroma
after the x1.9 saturation.  Crucially GHS rolls its slope OFF above SP (governed
by HP), so the bright rim tail + knots compress gently and rim_clip stays ~0
(the colour-killer is clipping every channel to 1.0).  And because the steep part
is at the rim, the slope DOWN at sky level (x~0.0005) is only ~0.6-0.8 vs the
asinh baseline's ~2.6 -> LESS sky luminance/chroma noise, not more.  That dual
advantage (steep at rim, shallow at sky) is the whole lever.

The gentle highlight curve is a mild asinh (large softening 'a' => nearly linear),
applied via the mask only to the very brightest input (stars + brightest knots),
so those compress smoothly and never clip while the rim body stays on the
amplifier.

  faint_strength      -> GHS stretch intensity D (here: rim contrast/chroma gain)
  b                   -> GHS local stretch intensity (hyperbolic knee sharpness, >0)
  sp                  -> GHS symmetry point (where slope peaks; put IN the ring body ~0.16)
  hp                  -> GHS highlight-protection point (slope rolls off above this -> no blow)
  highlight_strength  -> asinh softening 'a' for the gentle highlight curve (larger=gentler)
  mask_thresh         -> luminance at which mask = 0.5 (amplifier<->gentle crossover)
  mask_soft           -> width of the smooth mask transition (logistic scale)
"""
import numpy as np

# Param scales come from probing the linear-normalized M57 master
# (m57_cc_s15.fit) AFTER the harness black-point + global 99.99pct white:
#   sky lum med ~0.0001 (p90 ~0.001); central cavity med ~0.10; bright RING body
#   med ~0.16 (mask range ~0.04-0.37, channels R0.13 G0.17 B0.19 = teal);
#   brightest knots + field stars clip near 1.  So SP (where GHS slope peaks)
#   belongs IN THE RING BODY ~0.13-0.18 (NOT down at 0.003 -- that M51 placement
#   sat below the entire M57 signal and routed the whole ring to the gentle
#   curve, the documented failure mode).  HP (roll-off) sits just above the rim
#   tail ~0.35-0.45 so knots don't blow.  The mask crossover sits at/above the
#   rim top (~0.32-0.42 luminance) so only the brightest knots+stars take the
#   gentle curve; the rim body rides the chroma amplifier.
# Frontier finding (sweep + sky-pixel decomposition):
#   The binding constraint on M57 is sky_noise_chroma <= 0.0076 (the asinh
#   baseline value). That ceiling is NOT set by sky mottle -- on the genuine
#   faint sky (99.8% of the annulus, lum <= 0.05) THIS curve is ~2x quieter than
#   baseline (0.0019 vs 0.0037), because the GHS slope at the sky floor (~0.0005)
#   is only ~0.7 vs baseline's ~2.6. The ceiling is set by ~189 faint FIELD STARS
#   in the annulus (0.18% of pixels): any rim-chroma amplifier that is steep
#   through x~0.05-0.30 also amplifies those stars' chroma. So rim chroma trades
#   directly against star-outlier chroma, and the feasible rim_chroma tops out
#   ~0.225 (vs baseline 0.1997) at the point where the two effects balance and
#   full sky_noise_chroma == baseline 0.0076.
# Best FEASIBLE set for M97 (all hard gates met, rim not dimmed, multi-hue honest):
# D=22, B=5, SP=0.03, HP=0.16 -> rim_chroma 0.390 (+24.6% vs asinh a=0.03 baseline
# 0.3132), rim_lum 0.297 (==baseline 0.292), rim_clip 0, sky_noise_lum 0.0207
# (<0.0292 baseline), sky_noise_chroma 0.0195 (<0.0391 baseline). SP sits just below
# the rim's R channel so red is LIFTED not crushed (layered teal, not flat OIII wash);
# HP rolls the cavity+star tail off; gentle asinh a=0.4 + mask_thresh 0.28 hand the
# brightest stars to a soft curve.
DEFAULTS = {
    "faint_strength": 22.0,
    "b": 5.0,
    "sp": 0.03,
    "hp": 0.16,
    "highlight_strength": 0.4,
    "mask_thresh": 0.28,
    "mask_soft": 0.05,
}

# 6 sets: a ladder in rim-chroma gain for the M97 (Owl) faint-disk regime. Rows 1-3
# climb D along the SP-in-the-rim axis while holding rim_lum within +/-15% of the
# asinh baseline (0.292) -- row 2 == the DEFAULTS frontier point, the recommended pick
# (matched rim_lum, red floor preserved, sky quieter than baseline). Rows 4-6 push D
# and raise SP for higher rim_chroma (up to ~0.49); they are deliberately included to
# map the frontier, but they BRIGHTEN the rim past +15% AND/OR crush the red channel
# toward 0 (a single-hue OIII overdrive the chroma metric rewards but the EYE rejects),
# so they do NOT count as clean wins. Every row keeps the steep part AT the rim and the
# slope LOW at sky, so sky_noise_lum/chroma stay UNDER baseline and rim_clip stays 0.
# mask_thresh/soft are normalized LUMINANCE.
SWEEP = [
    {"faint_strength": 18.0, "b": 5.0, "sp": 0.03, "hp": 0.16, "highlight_strength": 0.4, "mask_thresh": 0.28, "mask_soft": 0.05},
    {"faint_strength": 22.0, "b": 5.0, "sp": 0.03, "hp": 0.16, "highlight_strength": 0.4, "mask_thresh": 0.28, "mask_soft": 0.05},
    {"faint_strength": 25.0, "b": 5.0, "sp": 0.03, "hp": 0.16, "highlight_strength": 0.4, "mask_thresh": 0.28, "mask_soft": 0.05},
    {"faint_strength": 30.0, "b": 6.0, "sp": 0.04, "hp": 0.16, "highlight_strength": 0.4, "mask_thresh": 0.28, "mask_soft": 0.05},
    {"faint_strength": 40.0, "b": 6.0, "sp": 0.045, "hp": 0.16, "highlight_strength": 0.4, "mask_thresh": 0.28, "mask_soft": 0.05},
    {"faint_strength": 80.0, "b": 8.0, "sp": 0.035, "hp": 0.20, "highlight_strength": 0.4, "mask_thresh": 0.35, "mask_soft": 0.06},
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


def apply(x, faint_strength=22.0, b=5.0, sp=0.03, hp=0.16,
          highlight_strength=0.4, mask_thresh=0.28, mask_soft=0.05):
    x = np.clip(x, 0.0, 1.0)
    lum = x.mean(-1)  # (H, W) brightness field for the mask

    # Strong faint curve (GHS hyperbolic) and gentle highlight curve (mild asinh),
    # each applied per-channel to preserve colour.
    D = float(faint_strength)
    B = max(float(b), 1e-3)
    SP = float(np.clip(sp, 1e-4, 0.95))
    HP = float(np.clip(hp, SP + 1e-3, 1.0))
    faint = _ghs_hyperbolic(x, D, B, SP, 0.0, HP)
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
