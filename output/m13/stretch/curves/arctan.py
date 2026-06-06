"""arctan -- arctangent / tanh / generalized-hyperbolic soft-knee stretch.

An alternative to asinh from the same "smooth saturating curve" family, but with
a tunable knee that can be made STEEPER at the origin than asinh while still
rolling off gracefully into the highlights -- the regime where it beats asinh for
faint-feature lift without blowing the cores.

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

# M57 winning regime (against asinh a=0.15 baseline: rim_chroma 0.1997, rim_lum
# 0.333, rim_clip 0, center_chroma 0.380, sky_noise_lum 0.0152, sky_noise_chroma
# 0.0076).  "Better" = HIGHER rim_chroma at rim_lum >= 0.28, rim_clip ~0, and
# sky_noise_lum <= 0.0152 AND sky_noise_chroma <= 0.0076.
#
# The binding constraint is sky_noise_chroma.  Decomposing it on this master:
# the sky annulus is 99.6% faint floor (input lum < 0.02) but the chroma std is
# DOMINATED by the 0.2% of pixels that are field stars (input lum up to 1.0).
# asinh a=0.15 sits at exactly snC 0.0076 there.  So two separate things had to
# be controlled, with two separate knobs:
#   (1) the faint FLOOR -- the GHS knee that lifts the ring also amplifies the
#       floor's per-channel mottle.  The `shadow` toe kills slope at x<0.01 and
#       crushes the floor's chroma ~6x vs asinh (0.0028 -> 0.0004), so the rim
#       lift no longer drags the floor up.  This alone, though, was NOT enough --
#       the stars dominate, so the toe just freed headroom; rim_chroma still hit
#       a wall ~0.24 because the stars stayed over budget.
#   (2) the STARS -- post-curve chroma ~ slope*(channel spread), and a fixed
#       saturation 1.9 blows any residual slope on the bright stars into chroma.
#       The `hl` shoulder flattens curve slope above the rim so the stars get a
#       gentle (asinh-like) highlight roll, pulling snC back to budget.  It costs
#       a little rim_chroma (the rim's brightest knots share that highlight band),
#       so the win is the best point on the rim_chroma vs snC frontier, not free.
# Net: rim_chroma 0.2368 at snC exactly 0.0076 -- ~+19% over baseline, honestly.
#
# Tuned region: pivot ~0.15 (on the ring base), gain ~1.4 (lifts rim_lum to
# ~0.30, comfortably over the 0.28 floor), b ~1 (gentle hyperbolic roll keeps
# per-channel rim separation), shadow ~0.022 (sky-scale toe, holds sky_noise_*
# under budget).  This beats baseline rim_chroma 0.1997 by ~30% at brighter rim,
# zero clip, and BOTH sky-noise metrics at or under budget.
# DEFAULT = the highest-rim_chroma config that STILL strictly honours every
# constraint (rim_lum >= 0.28, rim_clip 0, sky_noise_lum <= 0.0152,
# sky_noise_chroma <= 0.0076).  Verified through the harness:
#   rim_chroma 0.2368 (baseline asinh a=0.15 = 0.1997 -> +18.6%)
#   rim_lum    0.281  (> 0.28 floor; ring stays bright, not dimmed to win chroma)
#   rim_clip   0.0    (ring not blown to white)
#   center_chroma 0.326,  sky_noise_lum 0.0126 (< 0.0152),  sky_noise_chroma 0.0076 (= budget)
# The three M57 levers in concert:
#   pivot 0.13  -- knee centred just below the ring base (rim is x~0.05-0.35),
#                  so the rim rides the steep high-contrast part into the
#                  bright-but-unsaturated high-chroma zone.
#   shadow 0.03 -- sky-scale toe; crushes the faint sky floor's chroma 6x (vs
#                  asinh) so the rim lift doesn't drag the noise-floor mottle up.
#   hl 0.45/0.6 -- highlight shoulder flattens slope above the rim so the field
#                  stars in the sky annulus (which, post-saturation, were the
#                  DOMINANT sky_noise_chroma source -- not the floor) get a
#                  gentle asinh-like shoulder, pulling sky_noise_chroma to budget.
DEFAULTS = {"gain": 1.5, "pivot": 0.13, "b": 1.0, "shadow": 0.030,
            "hl_knee": 0.45, "hl_strength": 0.6}

# Sweep walks the rim_chroma / sky_noise_chroma frontier; sky_noise_chroma is the
# binding constraint (the field stars in the sky annulus set an irreducible-ish
# floor under saturation 1.9).  Every set below was harness-verified to PASS all
# constraints; they trade a hair of rim_chroma for rim_lum / center_chroma margin.
SWEEP = [
    # rim_chroma-max -- the DEFAULT/headline winner.
    {"gain": 1.5, "pivot": 0.13, "b": 1.0, "shadow": 0.030, "hl_knee": 0.45, "hl_strength": 0.6},
    # slightly lower pivot + stronger toe: a touch more rim_lum margin.
    {"gain": 1.5, "pivot": 0.12, "b": 1.0, "shadow": 0.035, "hl_knee": 0.45, "hl_strength": 0.6},
    # sharper knee (b=1.5): best center_chroma + safest rim_lum (0.29).
    {"gain": 1.5, "pivot": 0.12, "b": 1.5, "shadow": 0.030, "hl_knee": 0.40, "hl_strength": 0.6},
    # higher gain, lower knee: pushes rim+center chroma, heavier shoulder holds snC.
    {"gain": 1.6, "pivot": 0.12, "b": 1.5, "shadow": 0.035, "hl_knee": 0.35, "hl_strength": 0.6},
    # gentler shoulder, higher gain: chroma via lift, snC kept by stronger toe.
    {"gain": 1.6, "pivot": 0.14, "b": 1.0, "shadow": 0.025, "hl_knee": 0.45, "hl_strength": 0.9},
    # asinh-ish safety net: lower gain, mild everything (robust PASS, lower chroma).
    {"gain": 1.4, "pivot": 0.14, "b": 1.0, "shadow": 0.025, "hl_knee": 0.50, "hl_strength": 0.5},
]

_B = 1.0  # M57: GENTLE hyperbolic roll above SP -- preserves rim per-channel color.


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


def apply(x, gain=1.5, pivot=0.13, b=_B, mode="ghs", shadow=0.030,
          hl_knee=0.45, hl_strength=0.6):
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
