"""arctan -- arctangent / tanh / generalized-hyperbolic soft-knee stretch.

An alternative to asinh from the same "smooth saturating curve" family, but with
a tunable knee that can be made STEEPER at the origin than asinh while still
rolling off gracefully into the highlights -- the regime where it beats asinh for
faint-feature lift without blowing the cores.

----------------------------------------------------------------------------
M97 RE-TUNE (Owl Nebula -- a FAINT, low-contrast OIII planetary; contest is
RIM COLOR RETENTION, the chroma regime)
----------------------------------------------------------------------------
M97 is a different planetary than M57.  M57 is a bright high-contrast ring whose
body lives at normalized x ~0.05-0.35.  M97 is faint and low-contrast: after the
harness's per-channel black + 99.99-pct white normalize, the WHOLE nebula is
crushed down near the floor -- rim luminance ~0.05, center ~0.05, halo ~0.006,
sky ~0.001, with only field stars reaching 1.0.  And the rim is OIII-dominated:
measured per-channel rim means are R~0.027, G~0.057, B~0.064 -- a clean
teal/cyan (B>G>>R), no Ha-red.  So the honest color to lift is the G-vs-B-vs-R
SEPARATION on the rim, and the rim sits an order of magnitude LOWER in x than on
M57.

Three things changed from the M57 tuning:

  1. PIVOT moved WAY down -- 0.13 -> ~0.05.  M57's pivot sat on its bright ring
     base (0.13); on M97 that's ABOVE the entire nebula and would crush it to
     black.  Here the rim is at x~0.05, so the knee's steepest point (max local
     contrast) is centred at pivot~0.05 to land ON the rim, lifting the teal into
     the bright-but-unsaturated high-chroma zone while sky/halo ride the
     suppressed lower branch.

  2. GAIN raised -- ~1.5 -> ~2.6.  The rim is so faint in normalized space that a
     gentle stretch leaves it dim; a stronger D = e^gain-1 is needed to bring
     rim_lum back up to ~baseline (asinh a=0.03 rim_lum ~0.29) while the lower
     branch keeps the sky down.  Because the rim is teal (R~0), the bigger slope
     amplifies the G/B-vs-R separation honestly -- R stays ~0, G and B both rise,
     chroma = max-min grows as real cyan, not a single-channel blowout (verified:
     post-curve rim is 84% B-max / 16% G-max / 0% R-max).

  3. SHADOW toe moved to the SKY scale (~0.02 -> ~0.005).  M97's sky bulk lives
     at x<0.002 and the halo at ~0.006 -- a much lower floor than M57.  The toe is
     placed just above the sky bulk and below the halo so it crushes the sky's
     per-channel mottle (the rim-lifting knee would otherwise amplify it) without
     touching the rim.  shadow=0 is still an exact no-op.

The HIGHLIGHT shoulder (`hl_*`), which was load-bearing on M57 to tame bright
field stars whose colour blew the tiny sky_noise_chroma budget, is NOT needed on
M97: the sky annulus here is ~99.99% faint floor (only 0.014% star pixels) and
the chroma budget is loose (baseline sky_noise_chroma 0.0391 vs M57's 0.0076).
So hl_strength defaults to 0 (exact no-op) and stays an available knob for the
sweep, not a crutch.  The apply() math is unchanged -- pivot + shadow already
span this regime; only DEFAULTS/SWEEP were re-tuned.

----------------------------------------------------------------------------
M57 RE-TUNE (bright planetary -- contest is RING COLOR RETENTION, not faint lift)
----------------------------------------------------------------------------
The M51 tuning was wrong for M57's regime and is documented at the bottom.  Two
things changed for M57:

  1. RE-TUNED knobs.  M57's signal sits an order of magnitude higher than M51's
     faint bridge:  sky ~0 (the bulk under x<0.01), central cavity ~0.10, the
     bright RING body ~0.05-0.35 (luminance; the contest annulus), knots/stars
     clip near 1.  So the knee is no longer pinned to the origin.  The pivot SP
     is moved UP onto the ring-base scale (~0.13-0.17) so the steepest part of
     the knee -- the max-local-contrast point -- lands ON the ring, lifting it
     into the bright-but-unsaturated high-chroma zone, while x < SP (the cavity
     floor and sky) rides the suppressed lower branch.  The curvature b is also
     moved off the M51 high-b "sharp-rolloff" value to a GENTLE hyperbolic
     b~1-2: above SP a gentle roll preserves per-channel separation on the rim
     (a sharp rolloff compresses the rim toward white and flattens its color).

  2. NEW KNOB for the M57 regime -- `shadow`, a soft shadow-foot applied BEFORE
     the GHS knee.  Measured on this master: the sky annulus has per-channel
     std ~0.01 living almost entirely in x < 0.01, while the ring is at x>0.05
     -- a clean gap.  The GHS knee alone couples sky-chroma-noise to rim-chroma
     (the same slope that lifts the rim, applied near 0, amplifies the sky's
     color mottle), so pushing rim_chroma past ~0.24 blew sky_noise_chroma over
     budget.  `shadow` decouples them: a Reinhard-style toe  s(x)=x^2/(x+shadow)
     -- slope 0 at x=0 (kills the noise-floor variance), slope ->1 for x>>shadow
     (passes the ring through untouched as a soft black subtraction).  Placed at
     the SKY scale (~0.02, ABOVE the sky bulk <0.01, BELOW the cavity at 0.08
     and the ring at 0.05) it damps sky luminance AND chroma noise without
     touching the rim -- letting gain/pivot/b be tuned purely for rim color.
     (This is exactly where the M51 masked agent went wrong by putting its
     threshold at ~0.1, above the whole signal; here the floor is at sky scale.)
     shadow=0 is an exact no-op, so the M51 faint-lift behavior is recoverable.

Math (published forms):
  * Arctangent stretch:  the integral of a Lorentzian soft-knee 1/(1+u^2).
        T(u) = arctan(u)              (saturating, slope 1 at u=0, ->pi/2)
  * tanh stretch:        the integral of a sech^2 soft-knee.
        T(u) = tanh(u)
  * Generalised Hyperbolic Stretch (Payne & Cranfield 2021; the family Siril/PI
    expose as GHS). Base transform on [0, inf):
        T(u)  = 1 - (1 + b*D*u)^(-1/b)        (b != 0)
        T'(u) = D*(1 + b*D*u)^(-(1+b)/b)
    with the curve reflected about a symmetry point SP (pivot):
        x >= SP :  raw(x) =  T(  x - SP )
        x <  SP :  raw(x) = -T( SP - x )      (odd reflection through SP)
    then normalised so [0,1] -> [0,1]:
        out(x) = (raw(x) - raw(0)) / (raw(1) - raw(0))
    b selects the curvature regime: b->0+ is exponential 1-e^{-Du};
    b=1 is the pure hyperbolic (tanh-like) integral; b<0 logarithmic-ish.

This module unifies all three under one apply().  The two TUNED knobs are
`gain` and `pivot` (per the technique spec):
    gain  -> stretch strength D = exp(gain) - 1   (bigger gain = harder faint lift)
    pivot -> SP, the symmetry point where the knee is centred (the brightness that
             gets the most local contrast). pivot near 0 puts the whole faint range
             on the steep upper branch.
`b` and `mode` are fixed-form selectors (defaulted to the hyperbolic regime that
out-lifts asinh); the sweep moves gain & pivot, the published primary knobs.
"""
import numpy as np

# M97 winning regime (against baseline asinh a=0.03, harness-measured on this
# master: rim_chroma 0.3132, rim_lum 0.2917, rim_clip 0, center_chroma 0.367,
# sky_noise_lum 0.0292, sky_noise_chroma 0.0391).  "Better" = HIGHER rim_chroma
# with rim_lum within ~15% of baseline (0.248-0.335), rim_clip ~0, and
# sky_noise_lum <= 0.0292 AND sky_noise_chroma <= 0.0391 -- multi-hue honest, not
# a single-channel blowout.
#
# Unlike M57, sky_noise is NOT the binding constraint here (the budget is ~5x
# looser and the sky is almost pure faint floor, only 0.014% star pixels).  The
# binding constraint is rim_lum: the rim is so faint in normalized space (x~0.05)
# that pushing gain/pivot for more chroma also brightens it, and too much gain
# walks rim_lum out past +15%.  So the tuning targets the highest honest
# rim_chroma at rim_lum ~= baseline (~0.29), where the chroma gain is real
# G/B-vs-R separation and not a brightness artifact.
#
# The three M97 levers in concert:
#   pivot 0.05  -- knee centred ON the faint rim (x~0.05), so the rim rides the
#                  steepest high-contrast part of the knee; sky/halo (x<0.006)
#                  ride the suppressed lower branch.
#   gain  2.6   -- strong enough to lift the faint rim back to ~baseline lum; the
#                  big slope amplifies the rim's teal (R~0, G/B high) into honest
#                  cyan chroma (post-curve rim: 84% B-max, 16% G-max, 0% R-max).
#   b     1.5   -- moderately sharp hyperbolic knee: more rim chroma than b=1 at
#                  matched lum, still gentle enough to keep per-channel separation.
#   shadow 0.005 -- sky-scale toe (M97's sky bulk is at x<0.002, halo ~0.006);
#                  crushes the faint floor's mottle so the rim lift doesn't drag
#                  sky_noise up.  hl_* = 0 (no bright-star problem here; no-op).
# DEFAULT = the headline honest winner, harness-verified:
#   rim_chroma 0.4654 (baseline 0.3132 -> +48.6%)
#   rim_lum    0.273  (within 15% of baseline 0.2917; rim not dimmed to win chroma)
#   rim_clip   0.0    (rim not blown to white)
#   center_chroma 0.544,  sky_noise_lum 0.0236 (< 0.0292),  sky_noise_chroma 0.0156 (< 0.0391)
DEFAULTS = {"gain": 2.6, "pivot": 0.05, "b": 1.5, "shadow": 0.005,
            "hl_knee": 0.9, "hl_strength": 0.0}

# Sweep walks the rim_chroma / rim_lum frontier (the binding axis for M97).  Every
# set below was harness-verified to PASS all constraints; they trade rim_chroma
# for rim_lum margin (sets near baseline lum are the honest headline; higher-gain
# sets push chroma further but brighten the rim toward the +15% ceiling).
SWEEP = [
    # rim_chroma-max at ~baseline rim_lum -- the DEFAULT/headline honest winner.
    {"gain": 2.6, "pivot": 0.05, "b": 1.5, "shadow": 0.005, "hl_knee": 0.9, "hl_strength": 0.0},
    # gentler knee (b=1): a touch less chroma, slightly safer rim_lum.
    {"gain": 2.5, "pivot": 0.05, "b": 1.0, "shadow": 0.006, "hl_knee": 0.9, "hl_strength": 0.0},
    # pivot up onto the rim peak + b1: high chroma, rim_lum right at baseline.
    {"gain": 3.0, "pivot": 0.06, "b": 1.0, "shadow": 0.000, "hl_knee": 0.9, "hl_strength": 0.0},
    # higher gain, lower pivot + stronger toe: more chroma, rim brightens (~+15% lum).
    {"gain": 3.0, "pivot": 0.04, "b": 1.0, "shadow": 0.006, "hl_knee": 0.9, "hl_strength": 0.0},
    # conservative near-baseline-lum point: robust PASS, still well over baseline rc.
    {"gain": 2.4, "pivot": 0.05, "b": 1.0, "shadow": 0.005, "hl_knee": 0.9, "hl_strength": 0.0},
    # demo of the highlight knob (no-op-ish here): mild shoulder, sky-scale toe.
    {"gain": 2.6, "pivot": 0.05, "b": 1.5, "shadow": 0.005, "hl_knee": 0.6, "hl_strength": 0.3},
]

_B = 1.5  # M97: moderately sharp hyperbolic knee on the rim -- max honest rim chroma.


def _ghs_base(u, D, b):
    """GHS base transform on u>=0: 1-(1+b D u)^(-1/b); b->0 limit = 1-e^{-Du}."""
    if abs(b) < 1e-6:
        return 1.0 - np.exp(-D * u)
    return 1.0 - np.power(1.0 + b * D * u, -1.0 / b)


def _shadow_toe(x, s):
    """Reinhard-style soft shadow-foot s(x)=x^2/(x+s), renormalised so 1->1.

    Slope 0 at x=0 (suppresses the sky's noise-floor variance), slope ->1 for
    x>>s (passes signal through as a soft black subtraction).  s=0 is an exact
    no-op.  Monotone, smooth, fixes 0->0 and 1->1.  Placed at the sky scale this
    decouples sky chroma/luminance noise from the rim-lifting GHS knee.
    """
    if s <= 0.0:
        return x
    toe = (x * x) / (x + s)
    norm = 1.0 / (1.0 + s)          # s(1) = 1/(1+s); rescale so white stays at 1
    return np.clip(toe * norm, 0.0, 1.0)


def _highlight_shoulder(y, knee, strength):
    """Smooth highlight shoulder above `knee`: flattens the curve's SLOPE in the
    highlights with NO slope discontinuity (so it cannot ring the rim).

    Why this knob matters for M57 colour: post-curve chroma ~ T'(x)*(channel
    spread), so a bright pixel's displayed colour is set by the LOCAL SLOPE at
    its value.  The field stars in the sky annulus (and the rim's brightest
    knots) sit in the highlights; if the curve keeps a steep slope there, the
    fixed downstream saturation blows their channel imbalance into a big chroma
    excursion -- which is what drove sky_noise_chroma over budget.  Holding the
    rim's high chroma therefore costs nothing if we SEPARATELY flatten the slope
    ABOVE the rim: stars get a gentle (asinh-like) shoulder, their chroma noise
    drops, while the rim (y < knee) is left essentially unchanged.

    Construction: for y >= knee, remap with an upward-concave quadratic
    g(t)=(1-s)t + s t^2 on the normalised shoulder coord t=(y-knee)/(1-knee).
    Slope steps DOWN from 1 to 1-s at the knee (a benign soft compression that
    only ever dims highlights -- never a slope INCREASE, which is what would make
    a bright contour/moat), is lowest in the bright-star band just above the knee,
    and returns to 1+s only at pure white where ~no pixels live.  Fixes knee->knee
    and 1->1; strictly monotone for s in [0,1).  strength=0 -> exact no-op; below
    `knee` the input is passed through unchanged.
    """
    if strength <= 0.0 or knee >= 1.0:
        return y
    s = min(strength, 0.95)
    span = 1.0 - knee
    out = y.copy()
    hi = y >= knee                                    # ONLY remap the highlights
    if not np.any(hi):
        return out
    t = (y[hi] - knee) / span                         # 0..1 over the shoulder
    # Upward-concave quadratic g(t) = (1-s)t + s t^2:  g(0)=0, g(1)=1, but
    # g'(0)=1-s (slope REDUCED right at the knee, where the field stars and the
    # rim's brightest knots pile up) rising to g'(1)=1+s only at pure white
    # (almost no pixels).  So the shoulder FLATTENS exactly the bright-star band
    # whose colour the downstream saturation was blowing into the sky chroma
    # budget.  The slope steps DOWN (1 -> 1-s) at the knee -- a benign soft
    # compression (it dims highlights gently), never a brightening contour.
    g = (1.0 - s) * t + s * t * t
    out[hi] = knee + span * g
    return out


def apply(x, gain=2.6, pivot=0.05, b=_B, mode="ghs", shadow=0.005,
          hl_knee=0.9, hl_strength=0.0):
    x = np.clip(x, 0.0, 1.0)

    if mode == "arctan":
        # Arctangent soft-knee. gain scales the input into the knee.
        g = max(gain, 1e-6)
        num = np.arctan(g * x)
        return num / np.arctan(g * 1.0)

    if mode == "tanh":
        g = max(gain, 1e-6)
        return np.tanh(g * x) / np.tanh(g * 1.0)

    # default: generalised-hyperbolic with pivot (odd reflection about SP).
    # M57: a soft shadow-foot first (sky-scale, decouples sky noise from the
    # rim-lifting knee), then the GHS knee centred on the ring-base pivot.
    x = _shadow_toe(x, float(max(shadow, 0.0)))
    D = np.expm1(gain)            # D = e^gain - 1, >0
    sp = float(np.clip(pivot, 0.0, 0.999))

    def raw(t):
        t = np.asarray(t, dtype=np.float64)
        out = np.empty_like(t)
        up = t >= sp
        out[up] = _ghs_base(t[up] - sp, D, b)
        out[~up] = -_ghs_base(sp - t[~up], D, b)
        return out

    lo = float(raw(np.array([0.0]))[0])
    hi = float(raw(np.array([1.0]))[0])
    y = (raw(x) - lo) / (hi - lo + 1e-12)
    y = np.clip(y, 0.0, 1.0)
    # M57 highlight protection: flatten slope above the rim so bright stars/knots
    # don't blow their colour into the sky_noise_chroma budget under saturation.
    y = _highlight_shoulder(y, float(np.clip(hl_knee, 0.0, 0.999)),
                            float(max(hl_strength, 0.0)))
    return np.clip(y, 0.0, 1.0)
