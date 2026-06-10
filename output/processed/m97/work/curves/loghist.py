"""loghist -- chained / iterative midtones stretch (multi-pass HistogramTransformation).

RE-TUNED FOR M97, the Owl Nebula (bright planetary; contest = DISK/RIM COLOR RETENTION).

The PixInsight "stretch in several gentle passes" workflow, made literal: instead of one
aggressive midtones move, apply N *gentle* MTF passes between a real black point and a
protected highlight rolloff -- the textbook HistogramTransformation loop ("move the black
point just above the noise, raise the midtones to reveal detail, protect the highlights").

Published math (PixInsight HistogramTransformation / Siril, verified against the docs):
  one pass, with shadow s and highlight h clip:
    xp        = clip((x - s) / (h - s), 0, 1)            # linear rescale into the clip window
    MTF(m,xp) = ((m - 1) * xp) / ((2m - 1) * xp - m)     # rational fn through (0,0),(m,1/2),(1,1)
  m < 0.5 lifts faints; m = 0.5 is identity. Special cases xp=0->0, xp=1->1, xp=m->0.5.
  The denominator is bounded away from 0 on [0,1] for m in (0,1) (= -m at xp=0, m-1 at xp=1).

--- What changed from the M57 tune, and WHY (the M97 regime is a faint, low-contrast disk) -
Measured on this M97 master AFTER the harness black-point + 99.99pct white normalize
(normalized [0,1] luminance, center at 168.699/55.019):
  sky (r 60-200):  median ~0.0011, std ~0.012, MAD ~0.0016, p90 ~0.0056  (plus bright field
                   stars -> max 1.0 in the annulus -- a chrominance-noise source)
  halo (r 20-35):  median ~0.006  (faint, near the floor; lin_halo_snr ~0.4 -> DO NOT chase it)
  rim  (r 4-16):   median ~0.049, p10 ~0.036, p90 ~0.064, max ~0.077
  center (r<4):    median ~0.053
This is NOT M57. M97 is a FILLED disk, not a thin bright ring: rim and center sit at nearly
the SAME brightness (~0.05), the whole nebula is squeezed into a narrow 0.035-0.077 band, and
that band is only ~5% of the way up from the floor. M57's ring reached 0.37; M97's "rim" tops
out at 0.077. So the regime inverts the M57 knob placement in two ways:

 1. THE NEBULA NEEDS A STRONG LIFT, NOT A GENTLE ONE. On M57 the ring was already at display
    0.14-0.37 and the job was to *protect* its color from compression. On M97 the disk lands
    at 0.05 and would be near-black without aggressive midtone work. The MTF chain has to pull
    x~0.05 up to display ~0.28-0.31 (baseline asinh a=0.03 lands rim_lum at 0.2917). That means
    a much firmer per-pass midtone (m ~0.20-0.25, was 0.36) over 2 passes. The win comes from
    landing the disk band on the STEEPEST part of the compounded curve, where the slightly
    different R/G/B linear values spread apart in display -> more honest multi-hue chroma at
    equal-or-lower sky noise than asinh (whose steepest slope is at x=0, where it amplifies the
    sky pedestal hardest and is compressive THROUGH the disk band).

 2. THE BLACK POINT IS THE NOISE LEVER AND IT MOVES DOWN, NOT UP. M97's sky std/MAD is far
    larger *relative to the signal* than M57's, and a firm lift will amplify any surviving sky.
    A black point of 0.008 crushes the sky pedestal completely: it sends sky_p90 (~0.0056) to
    0 after the chain (verified) while the disk (>0.035 everywhere) is untouched -- rim frac
    below 0.008 is ~0%. That is what keeps sky_noise_lum / sky_noise_chroma AT OR UNDER the
    asinh baseline despite the firmer lift. Going lower (0.005) leaves sky_p90 lifting to
    ~0.01-0.3 -> sky mottle; going higher (>0.02) starts biting the faint rim edge. 0.008 is
    the floor-just-above-the-noise sweet spot. `shadow_clip` is kept for generality but is a
    no-op here (sky MAD is tiny) and defaults to 0.

 3. THE KNEE MOVED DOWN to ~0.55 (was 0.78). On M97 the disk lands at display ~0.28-0.31 and
    only field stars / a couple of bright disk knots reach toward 1. Placing the knee at ~0.55
    -- just ABOVE the disk band -- means the gamma>1 rolloff tames ONLY those stars/knots
    (rim_clip stays ~0, nothing blown to white) while the entire disk body stays on the steep
    part of the curve where its channels separate -> max chroma. A knee at 0.78 (the M57 value)
    would barely engage here and let bright stars push toward white.

Why this BEATS the asinh baseline on M97:
  asinh a=0.03 is concave with its steepest slope at x=0, so it spends its dynamic range on the
  sky pedestal and is COMPRESSIVE across the 0.035-0.077 disk band -- it squashes the disk's
  inter-channel color difference. loghist does the opposite: black=0.008 flattens the slope at
  the floor (sky stays at/under baseline noise) and the two firm MTF passes put the STEEPEST
  compounded slope right across the disk band, pulling the OIII-teal / H-alpha-red channels
  apart -> more honest disk chroma at equal rim brightness and equal-or-lower sky noise. The
  knee at 0.55 then holds the brightest stars/knots back from white so that chroma is not lost
  to clipping.

Params (the contract knobs; `black` + the firm-midtone regime are the M97 retune):
  black       -- fixed normalized black point, applied ONCE before the passes (PRIMARY noise
                 lever; place it just above the sky pedestal, ~0.006-0.012 on M97).
  passes      -- number of gentle MTF passes (2 is right for M97's needed lift at m~0.2-0.25).
  midtone     -- per-pass midtones balance m in (0, 0.5). FIRMER (toward 0.2) -> more lift +
                 more chroma + more sky noise; gentler (toward 0.3) -> dimmer, safer. M97 sweet
                 spot is ~0.20-0.25 (lands rim near the asinh baseline luminance).
  shadow_clip -- per-pass adaptive black-point clip, in sigmas of the current background. ~0 on
                 M97 (sky MAD tiny -> no-op); kept for other regimes.
  knee        -- display level above which the highlight rolloff engages. On M97 place it just
                 above the lifted disk band (~0.50-0.60) so it tames only stars/knots.
  gamma       -- rolloff exponent above the knee (>1 compresses the bright tail; 1 = off).
"""
import numpy as np

# M97 default: firm 2-pass lift that lands rim_lum near the asinh baseline (~0.29) while
# black=0.008 holds sky_noise at/under baseline. Knee just above the lifted disk band.
DEFAULTS = {"black": 0.008, "passes": 2.0, "midtone": 0.225, "shadow_clip": 0.0,
            "knee": 0.55, "gamma": 3.0}

# Span the M97 frontier: midtone 0.205->0.245 trades chroma (firmer = steeper slope across the
# disk = more channel separation, but brighter + noisier) against staying within ~15% of the
# baseline rim_lum (0.248-0.335). black 0.006->0.010 trades a touch of rim brightness against
# sky-noise headroom (0.008 already zeroes sky_p90 after the chain). knee 0.50->0.60 sets how
# far up the rolloff begins. All vetted to keep rim_clip ~0 and sky_noise at/under baseline.
SWEEP = [
    {"black": 0.008, "passes": 2.0, "midtone": 0.225, "shadow_clip": 0.0, "knee": 0.55, "gamma": 3.0},  # DEFAULT: rim near baseline, max chroma w/ headroom
    {"black": 0.008, "passes": 2.0, "midtone": 0.210, "shadow_clip": 0.0, "knee": 0.55, "gamma": 3.0},  # firmer: more chroma, brighter rim
    {"black": 0.008, "passes": 2.0, "midtone": 0.240, "shadow_clip": 0.0, "knee": 0.55, "gamma": 3.0},  # gentler: dimmer, most noise headroom
    {"black": 0.006, "passes": 2.0, "midtone": 0.225, "shadow_clip": 0.0, "knee": 0.55, "gamma": 3.0},  # lower black: brighter rim, sky at margin
    {"black": 0.010, "passes": 2.0, "midtone": 0.215, "shadow_clip": 0.0, "knee": 0.55, "gamma": 3.0},  # firmer black + firmer midtone: most sky suppression
    {"black": 0.008, "passes": 2.0, "midtone": 0.220, "shadow_clip": 0.0, "knee": 0.50, "gamma": 4.0},  # lower/steeper knee: hardest star protection
]


def _mtf(xp, m):
    """PixInsight midtones transfer function on already-[0,1] input. m in (0,1)."""
    m = float(min(max(m, 1e-4), 1.0 - 1e-4))
    num = (m - 1.0) * xp
    den = (2.0 * m - 1.0) * xp - m
    # den nonzero on [0,1] for m in (0,1): -m at xp=0, m-1 at xp=1, both bounded away from 0.
    return num / den


def _bg_stats(lum):
    """Robust background level + spread from the low end of the luminance field.

    Floor = median of the darkest ~30% of pixels; spread = MAD-ish sigma of that set. Tracks
    the sky pedestal even after a prior pass has lifted it, and is not thrown by the cores.
    """
    flat = lum.reshape(-1)
    lo = flat[flat <= np.quantile(flat, 0.30)]
    if lo.size < 16:
        lo = flat
    med = float(np.median(lo))
    mad = float(np.median(np.abs(lo - med))) * 1.4826
    if mad <= 0:
        mad = float(np.std(lo)) or 1e-6
    return med, mad


def apply(x, black=0.008, passes=2.0, midtone=0.225, shadow_clip=0.0, knee=0.55, gamma=3.0):
    n = int(round(max(1.0, passes)))
    m = float(midtone)
    kclip = float(shadow_clip)
    y = np.clip(x.astype(np.float64), 0.0, 1.0)

    # --- M97 PRIMARY noise lever: a small FIXED black point, applied ONCE up front. ---
    # Crushes the sky pedestal (whose noise the firm MTF passes would otherwise amplify) while
    # leaving the disk (which sits well above it, >0.035) untouched. h = 1.0.
    b = float(min(max(black, 0.0), 0.98))
    if b > 0.0:
        y = np.clip((y - b) / ((1.0 - b) + 1e-12), 0.0, 1.0)

    # --- chained midtone passes, each with an OPTIONAL adaptive shadow clip ---
    # On M97 shadow_clip defaults to 0 (sky MAD tiny -> no-op); kept for generality.
    for _ in range(n):
        if kclip > 0.0:
            lum = y.mean(-1)
            med, mad = _bg_stats(lum)
            s = float(min(max(med + kclip * mad, 0.0), 0.98))   # shadow point in current units
            xp = np.clip((y - s) / ((1.0 - s) + 1e-12), 0.0, 1.0)  # rescale into [0,1] (h = 1.0)
        else:
            xp = y
        y = _mtf(xp, m)

    # --- protected highlight rolloff: compress the bright tail above `knee`, leave the disk ---
    # On M97 the knee sits just above the lifted disk band (~0.55) so this tames only the
    # near-clip field stars / disk knots (rim_clip ~0) and never compresses the disk's color.
    k = float(min(max(knee, 0.0), 0.999))
    g = float(max(gamma, 1.0))
    if g > 1.0 and k < 1.0:
        hi = y > k
        # Apply the power only to the masked subset so a negative base (y<k) never reaches
        # `** g` (that would make NaNs). Continuous at the knee (->k) and at 1 (->1).
        t = (y[hi] - k) / (1.0 - k + 1e-12)
        y[hi] = k + (1.0 - k) * t ** g

    return np.clip(y, 0.0, 1.0)
