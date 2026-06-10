"""ghs -- Generalized Hyperbolic Stretch (Hardy/Payne & Cranfield; the GHS process in
Siril / PixInsight, ghsastro.co.uk).

Faithful port of the published reference math (GHS PixInsight script
`lib/GHSStretch.js`, repo mikec1485/GHS). The transfer function has FIVE distinct
analytic forms selected by the local-stretch exponent b:

    b == -1   logarithmic
    b  <  0   integral
    b ==  0   exponential
    b  >  0   hyperbolic (b==1 is the harmonic special case, same formula)

Built around a symmetry point SP where the stretch is most intense, with two
linear protection regions: shadows below LP and highlights above HP. Output is
the same four-region piecewise function the reference computes:

    x < LP :  a1 + b1*x                       (linear shadow protection)
    x < SP :  lower branch (forms below)      (180-deg-rotational about SP)
    x < HP :  upper branch
    else   :  a4 + b4*x                        (linear highlight protection)

The user-facing stretch strength is D; internally it is mapped exactly as the
reference does, Dint = exp(convFacD * D) - 1 with convFacD = 1.0, so a D value
here means the same thing it does in Siril/PixInsight.

For NGC6888 (this re-tune): a FAINT EXTENDED EMISSION NEBULA (the Crescent),
NOT a bright planetary. The harness calls this "chroma" mode and the contest is
still rim COLOR (OIII-teal arc vs the Ha-red shell), but the regime is the
opposite of M57: the signal sits DOWN IN THE SHADOWS, not in a bright ring body.
After the harness black-point + 99.99pct white, the levels are:
    sky background    ~0.00007   (normalized lum)
    rim annulus median ~0.0004   (the diffuse shell)
    rim p90            ~0.0027    (the brighter filaments)
    rim p99            ~0.015     (the bright OIII arc itself)
    center cavity p90  ~0.004
So the whole signal of interest lives in [0.0004, 0.02] -- four orders of
magnitude below where M57's ring lived (0.16). The baseline asinh a=0.012 is a
STEEP low-end lift tuned for exactly this: it maps rim p99 (0.015) -> 0.20 and
rim p90 (0.0027) -> 0.044.

To beat it on rim_chroma we want GHS's focal contrast placed RIGHT ON the rim
signal band, so SP is dropped to ~0.006 (down in the shadows where the shell
lives) instead of 0.16. A high D (strong stretch) plus a gentle/harmonic b
(b~0.5-1.0) gives a steep but smooth lift through [0.0004, 0.02]: the color-
preserving scale then multiplies each channel by a large factor there, separating
the OIII-blue/green from the Ha-red so the faint shell shows MORE honest color
than asinh's gentler arcsinh slope -- WITHOUT lifting the sky floor enough to
raise sky_noise (SP is above the sky level, so the sub-SP region stays steep-but-
low and the sky stays dark). LP=0 keeps the shadow lift continuous; HP=1.

The binding constraints here are sky_noise_lum / sky_noise_chroma (a faint-lift
curve can easily amplify background + field-star residual into mottle) and NOT
dimming the rim (rim_lum within ~15% of the baseline 0.0197). The hd_lo/hd_hi
highlight-chroma rolloff (added for M57's bright star cores) is retained: the sky
annulus (r 320-500) contains field stars that clip near 1, and neutralizing their
post-curve color trims sky_noise_chroma. It is a strict no-op when hd_lo >= 1.

HONEST RESULT (NGC6888, chroma mode): GHS does NOT beat the asinh a=0.012
baseline here. This is the faint-dominated regime, and asinh already sits on the
Pareto frontier (the documented M51/faint-nebula finding). The mechanism is hard:
rim_chroma and sky_noise (both lum and chroma) rise TOGETHER with lift strength,
and asinh's chroma/noise ratio (rim_chroma 0.0225 / sky_noise_chroma 0.0158 =
1.42) is strictly better than GHS's at every operating point. Matched to the
baseline's sky_noise_lum (~0.038), GHS yields rim_chroma ~0.017 (-24%) and a
dimmer rim. The only GHS points that nominally "beat" rim_chroma do so by pulling
hd_lo very low so the chroma rolloff neutralizes field-star color in the sky
annulus -- but that leaves the amplified luminance mottle untouched
(sky_noise_lum +36%), and the eye plainly rejects the grainy gray sky. That is
metric-gaming, not an honest win. The DEFAULT below is the closest honest
frontier-touching point (noise near baseline, no chroma-rolloff gaming); it is
chosen to be defensible, not to claim a false win.
"""
import numpy as np

# D, b, SP, LP, HP are the five published GHS controls (unchanged math); hd_lo/
# hd_hi are the M57 highlight-chroma-rolloff knobs added for this regime. D is the
# user stretch strength (mapped internally to exp(D)-1); b local stretch intensity;
# SP symmetry point; LP shadow-protection edge; HP highlight-protection edge.
# hd_lo: post-curve luminance where chroma begins rolling off toward neutral;
# hd_hi: luminance at/above which chroma is fully neutralized (star cores).
# Default = best validated M57 operating point: rim_chroma 0.263 (+32% vs asinh
# baseline 0.1997) at rim_lum 0.349 (brighter than baseline 0.333), rim_clip 0,
# sky_noise_lum 0.0150 (<=0.0152 cap) and sky_noise_chroma 0.0075 (<=0.0076 cap).
DEFAULTS = {"D": 2.7, "b": 1.2, "SP": 0.011, "LP": 0.0, "HP": 1.0, "hd_lo": 0.6, "hd_hi": 0.9}

# Frontier for NGC6888's faint-shell chroma regime. All sets place SP down in the
# rim signal band (~0.005-0.012) and use a strong D. The frontier is monotone and
# UNFAVORABLE: more D + lower SP -> more rim_chroma + rim_lum but proportionally
# MORE sky_noise (lum + chroma); asinh dominates the whole curve. The first two
# rows are the closest honest frontier-touching points (sky_noise near baseline);
# the rest illustrate the trade-off (and the gaming trap -- low hd_lo rows lift
# rim_chroma only by neutralizing star chroma while leaving luminance mottle).
SWEEP = [
    {"D": 2.7, "b": 1.2, "SP": 0.011, "LP": 0.0, "HP": 1.0, "hd_lo": 0.6,  "hd_hi": 0.9},   # DEFAULT: honest, sky_noise_lum ~= baseline
    {"D": 2.6, "b": 1.3, "SP": 0.012, "LP": 0.0, "HP": 1.0, "hd_lo": 0.85, "hd_hi": 0.98},  # noise-matched anchor, no rolloff gaming
    {"D": 3.0, "b": 0.7, "SP": 0.006, "LP": 0.0, "HP": 1.0, "hd_lo": 0.85, "hd_hi": 0.98},  # stronger lift, higher rim_chroma + sky_noise
    {"D": 3.2, "b": 0.5, "SP": 0.005, "LP": 0.0, "HP": 1.0, "hd_lo": 0.85, "hd_hi": 0.98},  # harder lift, peak rim_chroma (sky mottles)
    {"D": 2.2, "b": 2.0, "SP": 0.015, "LP": 0.0, "HP": 1.0, "hd_lo": 0.85, "hd_hi": 0.98},  # gentle: clean sky but rim dims/desats
    {"D": 3.2, "b": 0.5, "SP": 0.005, "LP": 0.0, "HP": 1.0, "hd_lo": 0.1,  "hd_hi": 0.3},   # GAMING TRAP: rolloff fakes rim_chroma win
]

_CONV_FAC_D = 1.0


def _coeffs(Dint, B, SP, LP, HP):
    """Compute the (a1,b1, a2,b2,c2,d2,e2, a3,b3,c3,d3,e3, a4,b4) reference
    coefficients for the active b-branch. Mirrors GHSStretch.js calculateVariables
    exactly. Returns a dict plus a 'kind' tag selecting the evaluation form."""
    if B == -1.0:  # logarithmic
        qlp = -1.0 * np.log(1.0 + Dint * (SP - LP))
        q0 = qlp - Dint * LP / (1.0 + Dint * (SP - LP))
        qwp = np.log(1.0 + Dint * (HP - SP))
        q1 = qwp + Dint * (1.0 - HP) / (1.0 + Dint * (HP - SP))
        q = 1.0 / (q1 - q0)
        a1, b1 = 0.0, Dint / (1.0 + Dint * (SP - LP)) * q
        a2, b2, c2, d2, e2 = (-q0) * q, -q, 1.0 + Dint * SP, -Dint, 0.0
        a3, b3, c3, d3, e3 = (-q0) * q, q, 1.0 - Dint * SP, Dint, 0.0
        a4 = (qwp - q0 - Dint * HP / (1.0 + Dint * (HP - SP))) * q
        b4 = q * Dint / (1.0 + Dint * (HP - SP))
        kind = "log"
    elif B < 0.0:  # integral (b<0, b!=-1). Reference flips B to +B for the algebra.
        B = -B
        qlp = (1.0 - np.power((1.0 + Dint * B * (SP - LP)), (B - 1.0) / B)) / (B - 1)
        q0 = qlp - Dint * LP * (np.power((1.0 + Dint * B * (SP - LP)), -1.0 / B))
        qwp = (np.power((1.0 + Dint * B * (HP - SP)), (B - 1.0) / B) - 1.0) / (B - 1)
        q1 = qwp + Dint * (1.0 - HP) * (np.power((1.0 + Dint * B * (HP - SP)), -1.0 / B))
        q = 1.0 / (q1 - q0)
        a1, b1 = 0.0, Dint * np.power(1.0 + Dint * B * (SP - LP), -1.0 / B) * q
        a2 = (1 / (B - 1) - q0) * q
        b2, c2, d2, e2 = -q / (B - 1), 1.0 + Dint * B * SP, -Dint * B, (B - 1.0) / B
        a3 = (-1 / (B - 1) - q0) * q
        b3, c3, d3, e3 = q / (B - 1), 1.0 - Dint * B * SP, Dint * B, (B - 1.0) / B
        a4 = (qwp - q0 - Dint * HP * np.power((1.0 + Dint * B * (HP - SP)), -1.0 / B)) * q
        b4 = Dint * np.power((1.0 + Dint * B * (HP - SP)), -1.0 / B) * q
        kind = "pow"
    elif B == 0.0:  # exponential
        qlp = np.exp(-Dint * (SP - LP))
        q0 = qlp - Dint * LP * np.exp(-Dint * (SP - LP))
        qwp = 2.0 - np.exp(-Dint * (HP - SP))
        q1 = qwp + Dint * (1.0 - HP) * np.exp(-Dint * (HP - SP))
        q = 1.0 / (q1 - q0)
        a1, b1 = 0.0, Dint * np.exp(-Dint * (SP - LP)) * q
        a2, b2, c2, d2, e2 = -q0 * q, q, -Dint * SP, Dint, 0.0
        a3, b3, c3, d3, e3 = (2.0 - q0) * q, -q, Dint * SP, -Dint, 0.0
        a4 = (qwp - q0 - Dint * HP * np.exp(-Dint * (HP - SP))) * q
        b4 = Dint * np.exp(-Dint * (HP - SP)) * q
        kind = "exp"
    else:  # B > 0: hyperbolic / harmonic
        qlp = np.power((1 + Dint * B * (SP - LP)), -1.0 / B)
        q0 = qlp - Dint * LP * np.power((1 + Dint * B * (SP - LP)), -(1.0 + B) / B)
        qwp = 2.0 - np.power(1.0 + Dint * B * (HP - SP), -1.0 / B)
        q1 = qwp + Dint * (1.0 - HP) * np.power((1.0 + Dint * B * (HP - SP)), -(1.0 + B) / B)
        q = 1.0 / (q1 - q0)
        a1, b1 = 0.0, Dint * np.power((1 + Dint * B * (SP - LP)), -(1.0 + B) / B) * q
        a2, b2, c2, d2, e2 = -q0 * q, q, 1.0 + Dint * B * SP, -Dint * B, -1.0 / B
        a3, b3, c3, d3, e3 = (2.0 - q0) * q, -q, 1.0 - Dint * B * SP, Dint * B, -1.0 / B
        a4 = (qwp - q0 - Dint * HP * np.power((1.0 + Dint * B * (HP - SP)), -(B + 1.0) / B)) * q
        b4 = (Dint * np.power((1.0 + Dint * B * (HP - SP)), -(B + 1.0) / B)) * q
        kind = "pow"
    return dict(kind=kind, a1=a1, b1=b1, a2=a2, b2=b2, c2=c2, d2=d2, e2=e2,
                a3=a3, b3=b3, c3=c3, d3=d3, e3=e3, a4=a4, b4=b4)


def _ghs_curve(z, Dint, B, SP, LP, HP):
    """Vectorized forward GHS transfer applied to scalar-field z in [0,1]."""
    z = np.clip(np.asarray(z, dtype=np.float64), 0.0, 1.0)
    if Dint == 0.0:  # identity (D=0 is a no-op stretch in the reference)
        return z
    c = _coeffs(Dint, B, SP, LP, HP)
    k = c["kind"]
    lo = z < LP
    hi = z >= HP
    mid_lo = (~lo) & (z < SP)
    mid_hi = (~hi) & (z >= SP)

    y = np.empty_like(z)
    # linear shadow region
    y[lo] = c["a1"] + c["b1"] * z[lo]
    # linear highlight region
    y[hi] = c["a4"] + c["b4"] * z[hi]
    if k == "log":
        y[mid_lo] = c["a2"] + c["b2"] * np.log(c["c2"] + c["d2"] * z[mid_lo])
        y[mid_hi] = c["a3"] + c["b3"] * np.log(c["c3"] + c["d3"] * z[mid_hi])
    elif k == "exp":
        y[mid_lo] = c["a2"] + c["b2"] * np.exp(c["c2"] + c["d2"] * z[mid_lo])
        y[mid_hi] = c["a3"] + c["b3"] * np.exp(c["c3"] + c["d3"] * z[mid_hi])
    else:  # "pow" -- hyperbolic, harmonic, and integral all share this form
        y[mid_lo] = c["a2"] + c["b2"] * np.power(c["c2"] + c["d2"] * z[mid_lo], c["e2"])
        y[mid_hi] = c["a3"] + c["b3"] * np.power(c["c3"] + c["d3"] * z[mid_hi], c["e3"])
    return y


def apply(x, D=2.7, b=1.2, SP=0.011, LP=0.0, HP=1.0, hd_lo=0.6, hd_hi=0.9):
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    Dint = np.exp(_CONV_FAC_D * D) - 1.0

    # Guard the protection edges so they bracket SP (the reference UI enforces
    # LP <= SP <= HP). Without this the q-constants can divide by zero.
    SP = float(np.clip(SP, 1e-4, 1.0 - 1e-4))
    LP = float(np.clip(LP, 0.0, SP))
    HP = float(np.clip(HP, SP, 1.0))

    # Colour-preserving (RGB-linked) application: stretch the luminance proxy,
    # then scale every channel by the same factor so hue is untouched and only
    # brightness is remapped -- exactly the GHS "Colour" stretch intent. This is
    # why the bright ring keeps (and amplifies) its color instead of desaturating
    # to white: a rim pixel at lum 0.16 gets factor ~3x, so its OIII-teal blue
    # and H-alpha red channels separate further, not collapse.
    lum = x.mean(axis=-1)
    lum_s = _ghs_curve(lum, Dint, b, SP, LP, HP)
    factor = np.where(lum > 1e-8, lum_s / np.maximum(lum, 1e-8), 0.0)
    y = x * factor[..., None]

    # M57 highlight-chroma rolloff: the sky annulus is dominated by field stars
    # whose color-preserving-amplified residual hue is the dominant chroma-noise
    # source (and the brightest star cores are clipping to white anyway, so their
    # remaining color IS noise). Taper chroma toward neutral over [hd_lo, hd_hi]
    # in *stretched* luminance: 0 effect below hd_lo (the whole ring lives there),
    # full neutralization above hd_hi (star cores). This buys the noise headroom
    # that lets D/b push rim chroma. A strict no-op when hd_lo >= 1 (e.g. the M51
    # regime), so the published color-stretch behaviour is recoverable bit-for-bit.
    if hd_lo < 1.0:
        hd_hi = max(hd_hi, hd_lo + 1e-6)
        t = np.clip((lum_s - hd_lo) / (hd_hi - hd_lo), 0.0, 1.0)
        keep = 1.0 - t  # chroma retained: 1 below hd_lo, 0 above hd_hi
        ymean = y.mean(axis=-1, keepdims=True)
        y = ymean + (y - ymean) * keep[..., None]

    return np.clip(np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
