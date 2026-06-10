"""loghist -- chained / iterative midtones stretch (multi-pass HistogramTransformation).

RE-TUNED FOR M57 (bright planetary; contest = RING COLOR RETENTION, not faint lift).

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

--- What changed from the M51 port, and WHY (the M57 regime is different) ----------------
Measured on this M57 master AFTER the harness black-point + 99.99pct white normalize
(normalized [0,1] luminance): sky median ~0.0001 (sky std ~0.0095), the central CAVITY at
~0.10, the bright RING annulus at 0.14 (median 0.16) up to ~0.37, and only a few knots/field
stars near 1. M57's outer halo is at the noise floor (lin_halo_snr ~0.14) -- so this is a
RING-COLOR shootout, not a faint-lift one.

That inverts two of the M51 knob placements:

 1. THE BLACK POINT IS NOW THE PRIMARY NOISE LEVER (new `black` param). On M51 the
    discriminating "sky noise" was a handful of bright stars inside the background box, tamed
    from the TOP by the highlight rolloff; the per-pass sigma clip (s = med + clip*MAD) was a
    bit player. On M57 the discriminating noise is the genuine SKY PEDESTAL at the BOTTOM, and
    the sigma clip is *useless* here -- the sky is so tight that MAD ~6e-6, so med+clip*MAD
    barely leaves zero (verified). What actually works is a small FIXED black point applied
    once up front: a floor at ~0.02 (normalized) crushes >99% of the sky pedestal (only ~0.4%
    of sky pixels -- contaminating stars -- survive) while the cavity (0% below 0.03) and ~94%
    of the ring sit entirely above it, untouched. This is the knob the M51 version lacked.
    `shadow_clip` is kept (same adaptive math) but defaults LOW -- it is a no-op at this scale
    and only there for generality; `black` does the suppression.

 2. THE KNEE MOVED TO THE TOP OF THE RING (~0.78, was 0.13). On M51 the rolloff at 0.13 was
    ABOVE the faint bridge (~0.01) and protected the galaxy cores. On M57 a knee at 0.13 would
    sit in the MIDDLE of the ring body and COMPRESS the whole ring's luminance + color -- the
    exact opposite of the goal. Re-placed near 0.78 so the gamma>1 rolloff engages ONLY on the
    near-clip knots/field stars (keeps rim_clip ~0, rim never blown to white) and leaves the
    entire ring body (display ~0.3-0.6 after the lift) on the steep part of the curve where its
    OIII-teal / H-alpha-red channels spread apart -> high rim_chroma.

Why this BEATS the asinh baseline on M57:
  asinh's steepest slope is at x=0 (it amplifies the sky pedestal hardest) and it is concave
  THROUGH the ring band (compressive there). loghist does the opposite: the fixed black point
  flattens the slope at the floor (sky noise stays at/under baseline) while the chained gentle
  MTFs put the STEEPEST compounded slope across the ring band (0.10-0.37), pulling the RGB
  channels apart -> more ring chroma at equal-or-lower sky noise. The top rolloff then holds
  the brightest knots back from white so that extra chroma is not lost to clipping.

Params (the contract knobs; `black` is the M57 addition, `shadow_clip` kept for generality):
  black       -- fixed normalized black point, applied ONCE before the passes (PRIMARY noise
                 lever on M57; place it just below the cavity, ~0.01-0.03).
  passes      -- number of gentle MTF passes (iterative count; 2 is right for M57's modest band).
  midtone     -- per-pass midtones balance m in (0, 0.5). Gentler (toward 0.5) -> less lift,
                 less sky-noise amplification. On M57 the sweet spot is ~0.355-0.365.
  shadow_clip -- per-pass adaptive black-point clip, in sigmas of the current background. ~0 on
                 M57 (sky MAD ~6e-6 makes it a no-op); kept for other regimes.
  knee        -- display level above which the highlight rolloff engages. On M57 place it at the
                 TOP of the ring (~0.78) so it tames only knots/stars, never the ring body.
  gamma       -- rolloff exponent above the knee (>1 compresses the bright tail; 1 = off).
"""
import numpy as np

# M57 default: best rim_chroma margin among sets that hold sky_noise_chroma <= baseline
# (0.0076) with comfortable luminance-noise headroom. black just below the cavity, 2 gentle
# passes, knee at the top of the ring.
DEFAULTS = {"black": 0.020, "passes": 2.0, "midtone": 0.360, "shadow_clip": 0.0,
            "knee": 0.78, "gamma": 3.0}

# Span the M57 frontier: black point 0.015->0.022 (noise headroom vs ring brightness), per-pass
# midtone 0.355->0.365 (firmer = more chroma + more sky noise; gentler = safer). Every set was
# vetted on this master to keep rim_clip ~0 AND sky_noise_lum <= 0.0152 AND sky_noise_chroma
# <= 0.0076 (the binding constraints), trading rim_chroma margin against noise headroom. No
# dark-moat / bright-halo ring artifact (the halo is at the noise floor, so there is nothing to
# moat against, and the black point sits below the cavity so the ring transition is untouched).
SWEEP = [
    {"black": 0.020, "passes": 2.0, "midtone": 0.360, "shadow_clip": 0.0, "knee": 0.78, "gamma": 3.0},  # DEFAULT: best chroma w/ skyC headroom
    {"black": 0.017, "passes": 2.0, "midtone": 0.360, "shadow_clip": 0.0, "knee": 0.78, "gamma": 3.0},  # lower black: brighter ring, skyC at margin
    {"black": 0.020, "passes": 2.0, "midtone": 0.365, "shadow_clip": 0.0, "knee": 0.78, "gamma": 3.0},  # gentler midtone: max noise headroom
    {"black": 0.015, "passes": 2.0, "midtone": 0.365, "shadow_clip": 0.0, "knee": 0.78, "gamma": 3.0},  # gentlest lift overall, brightest ring
    {"black": 0.022, "passes": 2.0, "midtone": 0.360, "shadow_clip": 0.0, "knee": 0.80, "gamma": 3.0},  # firmer black: most sky suppression
    {"black": 0.018, "passes": 3.0, "midtone": 0.400, "shadow_clip": 0.0, "knee": 0.80, "gamma": 3.0},  # 3 very-gentle passes (compound-slope variant)
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


def apply(x, black=0.020, passes=2.0, midtone=0.360, shadow_clip=0.0, knee=0.78, gamma=3.0):
    n = int(round(max(1.0, passes)))
    m = float(midtone)
    kclip = float(shadow_clip)
    y = np.clip(x.astype(np.float64), 0.0, 1.0)

    # --- M57 PRIMARY noise lever: a small FIXED black point, applied ONCE up front. ---
    # Crushes the sky pedestal (whose noise the chained MTFs would otherwise amplify) while
    # leaving the cavity + ring (which sit well above it) untouched. h = 1.0.
    b = float(min(max(black, 0.0), 0.98))
    if b > 0.0:
        y = np.clip((y - b) / ((1.0 - b) + 1e-12), 0.0, 1.0)

    # --- chained gentle midtone passes, each with an OPTIONAL adaptive shadow clip ---
    # On M57 shadow_clip defaults to 0 (sky MAD ~6e-6 makes it a no-op); kept for generality.
    for _ in range(n):
        if kclip > 0.0:
            lum = y.mean(-1)
            med, mad = _bg_stats(lum)
            s = float(min(max(med + kclip * mad, 0.0), 0.98))   # shadow point in current units
            xp = np.clip((y - s) / ((1.0 - s) + 1e-12), 0.0, 1.0)  # rescale into [0,1] (h = 1.0)
        else:
            xp = y
        y = _mtf(xp, m)

    # --- protected highlight rolloff: compress the bright tail above `knee`, leave the ring ---
    # On M57 the knee sits at the TOP of the ring (~0.78) so this tames only the near-clip knots
    # / field stars (rim_clip ~0) and never compresses the ring body's luminance or color.
    k = float(min(max(knee, 0.0), 0.999))
    g = float(max(gamma, 1.0))
    if g > 1.0 and k < 1.0:
        hi = y > k
        # Apply the power only to the masked subset so a negative base (y<k) never reaches
        # `** g` (that would make NaNs). Continuous at the knee (->k) and at 1 (->1).
        t = (y[hi] - k) / (1.0 - k + 1e-12)
        y[hi] = k + (1.0 - k) * t ** g

    return np.clip(y, 0.0, 1.0)
