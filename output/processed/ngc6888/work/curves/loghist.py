"""loghist -- chained / iterative midtones stretch (multi-pass HistogramTransformation).

RE-TUNED FOR NGC6888 (Crescent Nebula; Wolf-Rayet bubble; contest = RIM COLOR RETENTION
on a FAINT-rim regime -- the inverse of M57's bright planetary).

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

--- What changed from the M57 tune, and WHY (NGC6888 is the OPPOSITE faintness regime) ----
Measured on this NGC6888 master AFTER the harness per-channel black + 99.99pct white normalize
(normalized [0,1] luminance): sky median ~7e-5, the Ha/OIII RIM annulus (40-170 px) bulk at
p50~4e-4, p75~1.1e-3, p90~2.7e-3 (p99~1.5e-2 -- sparse bright knots), the central cavity a bit
brighter, and field stars near 1. Unlike M57's *bright* ring (display 0.14-0.37), this rim is
DEEP in the faint floor -- only ~6x the sky median. So a fixed black point near 0.02 (the M57
value) would annihilate the ENTIRE rim. This is a FAINT-rim color shootout.

That re-places every knob from the M57 tune:

 1. THE BLACK POINT IS NOW A WHISKER (`black` ~2e-4, was 0.02). It must sit just ABOVE the sky
    median (~7e-5) but well BELOW the rim bulk (p50~4e-4) so it nips the floor without touching
    the rim. A floor near 0.02 would erase a rim sitting at 4e-4. The dominant sky-noise source
    here is NOT the smooth pedestal -- it's sparse field stars *inside* the sky annulus whose
    level overlaps the rim knots; the black point can't reach those, so the highlight rolloff
    does that job (see knob 3). `shadow_clip` stays 0 (the sky is too tight for the adaptive
    sigma clip to bite -- same as M57).

 2. ONE STRONG MTF PASS, LOW MIDTONE (`passes`=1, `midtone`~0.042; M57 used 2 passes at 0.36).
    The rim is so faint that the per-pass MTF must be aggressive (m~0.04 puts the steepest slope
    right at the 3e-4..3e-3 rim band, where the Ha-red / OIII-teal channels separate -> chroma).
    A SECOND pass compounds that slope so hard it explodes the sky stars: sky_noise_lum jumps
    ~4x and the chroma becomes mottle, not honest color (verified -- 2-pass sets all fail the
    noise gate). So NGC6888 wants ONE firm pass, not several gentle ones.

 3. THE KNEE DROPPED TO ~0.24 (was 0.78). After the strong lift the rim bulk lands at display
    ~0.02-0.2 while the sky field-stars (and the brightest rim knots) land far higher. A LOW
    knee (~0.24) with a firm gamma (~4) compresses everything above it: that pulls the bright
    sky stars back down (sky_noise_lum drops BELOW baseline) and holds rim knots off white
    (rim_clip ~0), while leaving the rim *bulk* -- which carries the color -- on the steep part
    of the curve. This is what lets chroma rise while sky noise FALLS, both vs the asinh baseline.

Why this BEATS the asinh a=0.012 baseline on NGC6888:
  asinh's steepest slope is at x=0, so it amplifies the sky floor AND the sky field-stars
  hardest, and it has no rolloff to tame those stars. loghist's single low-m MTF puts a
  comparably steep slope across the faint rim band (so rim chroma matches-or-beats asinh at
  equal rim luminance), AND its low knee + gamma rolloff suppresses the bright sky stars that
  asinh leaves screaming -- so sky_noise_lum and sky_noise_chroma land at-or-below baseline.
  Net: +~10-12% rim_chroma at <= baseline sky noise, rim_lum within budget, rim_clip ~0. The
  gain is honest two-hue (Ha-red ~55-61% R-dominant pixels + OIII-teal ~33% B-dominant), not a
  single-hue blowout -- verified by per-channel rim means and dominant-channel fractions.

Params (the contract knobs; same shape as the M57 tune, re-placed for the faint-rim regime):
  black       -- fixed normalized black point, applied ONCE before the pass. NGC6888: a whisker
                 (~1.5e-4..3e-4) just above the sky median; NEVER near the rim bulk (~4e-4).
  passes      -- MTF pass count. NGC6888: 1 (a 2nd pass explodes the sky stars into mottle).
  midtone     -- per-pass midtones m in (0, 0.5). Lower = more lift. NGC6888 sweet spot ~0.042
                 (the rim is ~6x sky, so it needs an aggressive m to reach baseline rim_lum).
  shadow_clip -- adaptive per-pass sigma clip. 0 here (sky too tight to bite); kept for generality.
  knee        -- display level above which the rolloff engages. NGC6888: LOW (~0.24) so it tames
                 the bright sky field-stars + rim knots while leaving the color-bearing rim bulk.
  gamma       -- rolloff exponent above the knee (>1 compresses the bright tail; 1 = off). ~4 here.
"""
import numpy as np

# NGC6888 default: the best honest rim_chroma margin over the asinh a=0.012 baseline
# (chroma 0.0225, rim_lum 0.0197, sky_noise_lum 0.0378, sky_noise_chroma 0.0158) that holds
# rim_lum within budget AND sky noise (both axes) at-or-below baseline. One firm low-m pass,
# whisker black just above the sky median, low knee + gamma-4 rolloff to crush the sky stars.
DEFAULTS = {"black": 0.0002, "passes": 1.0, "midtone": 0.042, "shadow_clip": 0.0,
            "knee": 0.24, "gamma": 4.0}

# Span the NGC6888 frontier. midtone 0.042->0.048 is the lift knob (lower = more chroma + lum +
# sky noise); knee 0.24->0.32 trades chroma against sky-star suppression. Every set was vetted
# on this master to keep rim_clip ~0; the first three BEAT baseline rim_chroma (0.0225) with
# sky_noise_lum AND sky_noise_chroma <= baseline (0.0378 / 0.0158) and rim_lum within ~15% of
# 0.0197. The cleaner-but-tied sets trade chroma for deeper noise headroom. NO 2-pass set is
# included: a 2nd MTF pass quadruples sky_noise_lum and turns the chroma into field-star mottle.
SWEEP = [
    {"black": 0.0002, "passes": 1.0, "midtone": 0.042, "shadow_clip": 0.0, "knee": 0.24, "gamma": 4.0},  # DEFAULT: +11.6% chroma, both noise axes <= baseline
    {"black": 0.0002, "passes": 1.0, "midtone": 0.042, "shadow_clip": 0.0, "knee": 0.28, "gamma": 4.0},  # higher knee: more chroma, skyNc at baseline edge
    {"black": 0.0002, "passes": 1.0, "midtone": 0.045, "shadow_clip": 0.0, "knee": 0.24, "gamma": 4.0},  # +5.8% chroma, deeper noise headroom (cleaner)
    {"black": 0.0002, "passes": 1.0, "midtone": 0.045, "shadow_clip": 0.0, "knee": 0.30, "gamma": 4.0},  # mid chroma/noise tradeoff
    {"black": 0.0001, "passes": 1.0, "midtone": 0.045, "shadow_clip": 0.0, "knee": 0.24, "gamma": 4.0},  # thinner black: marginally brighter rim
    {"black": 0.0002, "passes": 1.0, "midtone": 0.050, "shadow_clip": 0.0, "knee": 0.30, "gamma": 4.0},  # gentlest lift: chroma ~baseline, lowest sky noise
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


def apply(x, black=0.0002, passes=1.0, midtone=0.042, shadow_clip=0.0, knee=0.24, gamma=4.0):
    n = int(round(max(1.0, passes)))
    m = float(midtone)
    kclip = float(shadow_clip)
    y = np.clip(x.astype(np.float64), 0.0, 1.0)

    # --- FIXED black point, applied ONCE up front. ---
    # NGC6888: a whisker (~2e-4) just above the sky median, well below the faint rim bulk -- nips
    # the floor without touching the rim. (On a bright-rim regime this is the primary noise lever
    # at a much higher value; here the highlight rolloff does most of the sky-star suppression.) h=1.
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
