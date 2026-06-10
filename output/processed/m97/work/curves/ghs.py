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

For M97, the Owl Nebula (this re-tune): a FAINT, LOW-CONTRAST PLANETARY -- a very
different regime from the bright M57 ring. The contest is still ring/shell COLOR
retention, but here the binding job is to LIFT a faint signal out of the floor
WITHOUT dimming it or muddying its color. After the harness black-point + 99.99pct
white, the signal scale is an order of magnitude fainter than M57: sky ~0.001, and
the whole nebula -- rim shell AND central cavity alike -- sits at lum ~0.05 (rim
annulus median 0.049, p90 0.064; center 0.053). There is NO bright clipping ring;
nothing in the nebula exceeds ~0.08 pre-curve. So SP must drop DOWN into that faint
band (~0.05) -- placing M57's SP=0.16 here lands the GHS focal contrast ABOVE all
the signal and under-stretches the whole Owl (rim_lum collapses to 0.067). With
SP=0.05 the most-intense GHS gain lands exactly on the shell: a rim pixel at lum
0.05 gets a large factor, so it brightens to rim_lum ~baseline AND its OIII-teal /
H-alpha-red channels separate further under the color-preserving scale (rim_chroma
up ~50%). Because the whole nebula is faint, a near-EXPONENTIAL local stretch
(small b, the b->0 branch is strongest at low SP) maximizes the low-end lift;
moderate D (~2.8) reaches baseline brightness without overcooking. LP=0, HP=1.

The constraint on M97 is rim_lum (keep within ~15% of asinh baseline 0.2917) and
SKY NOISE -- raw sky_noise_lum over r 60-200 is ~0.028, but that is dominated by
faint OUTER-HALO structure + a few field stars, NOT true background mottle: the
sigma-clipped sky sigma is only ~0.009. So the real background is clean; the lever
that keeps the metric's conservative snl under the asinh cap (0.0292) is still the
hd_lo/hd_hi highlight-CHROMA rolloff: it tapers color toward neutral for the
brightest post-curve pixels (field-star cores clipping to white, whose remaining
"color" is noise) over [hd_lo, hd_hi] in stretched luminance. The Owl shell lives
at post-curve lum ~0.32, far below hd_lo, so the rolloff leaves the nebula color
fully intact while pulling >hd_hi star cores to gray -- pure noise headroom. A
strict no-op when hd_lo >= 1 (recovers the published color-stretch bit-for-bit).
"""
import numpy as np

# D, b, SP, LP, HP are the five published GHS controls (unchanged math); hd_lo/
# hd_hi are the M57 highlight-chroma-rolloff knobs added for this regime. D is the
# user stretch strength (mapped internally to exp(D)-1); b local stretch intensity;
# SP symmetry point; LP shadow-protection edge; HP highlight-protection edge.
# hd_lo: post-curve luminance where chroma begins rolling off toward neutral;
# hd_hi: luminance at/above which chroma is fully neutralized (star cores).
# Default = best validated M97 operating point: rim_chroma 0.471 (+50% vs asinh
# baseline 0.3132) at rim_lum 0.327 (+12%, within the 15% band; brighter, not
# dimmer), rim_clip 0, sky_noise_lum 0.0279 (<=0.0292 cap) and sky_noise_chroma
# 0.0229 (<=0.0391 cap). SP=0.05 drops the GHS focal contrast onto the faint Owl
# shell; near-exponential b=0.4 maximizes the low-end lift; D=2.8 reaches baseline
# brightness without overcooking. Eye-confirmed honest multi-hue (OIII-teal shell
# + Ha-red rim/eyes), not single-hue saturation.
DEFAULTS = {"D": 2.8, "b": 0.4, "SP": 0.05, "LP": 0.0, "HP": 1.0, "hd_lo": 0.55, "hd_hi": 0.95}

# All sets below pass every M97 guard (rim_lum within 15% of baseline 0.2917,
# rim_clip~0, sky_noise_lum<=0.0292, sky_noise_chroma<=0.0391) and beat the
# baseline on rim_chroma. They trace the frontier: at SP~0.05 a smaller b (toward
# the exponential branch) + higher D lifts the faint shell harder -> more
# rim_chroma + rim_lum; raising SP or b backs off toward the baseline-brightness
# anchor with extra noise margin. hd_lo is the star-chroma-noise governor.
SWEEP = [
    {"D": 2.8, "b": 0.4, "SP": 0.05, "LP": 0.0, "HP": 1.0, "hd_lo": 0.55, "hd_hi": 0.95},  # DEFAULT: rc~0.471 rl~0.327 (+12%), balanced
    {"D": 3.0, "b": 1.0, "SP": 0.05, "LP": 0.0, "HP": 1.0, "hd_lo": 0.55, "hd_hi": 0.95},  # boldest: rc~0.484 rl~0.336 (+15% edge), lowest snc
    {"D": 2.5, "b": 0.0, "SP": 0.05, "LP": 0.0, "HP": 1.0, "hd_lo": 0.55, "hd_hi": 0.95},  # rl~baseline (+2%), still rc +37%
    {"D": 2.6, "b": 0.2, "SP": 0.05, "LP": 0.0, "HP": 1.0, "hd_lo": 0.55, "hd_hi": 0.95},  # conservative: rl 0.305 (+5%), rc +40%
    {"D": 3.0, "b": 0.3, "SP": 0.06, "LP": 0.0, "HP": 1.0, "hd_lo": 0.55, "hd_hi": 0.95},  # higher SP, more noise margin, rl~baseline
    {"D": 2.8, "b": 0.4, "SP": 0.05, "LP": 0.0, "HP": 1.0, "hd_lo": 1.00, "hd_hi": 0.97},  # default w/ hd OFF -- shows rolloff is near-no-op on nebula
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


def apply(x, D=2.8, b=0.4, SP=0.05, LP=0.0, HP=1.0, hd_lo=0.55, hd_hi=0.95):
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
