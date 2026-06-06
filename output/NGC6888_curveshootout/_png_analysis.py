"""Adversarial PNG analysis: co-registered winner vs baseline (both 760x760 crops,
same center, same crop_half -> pixel-aligned). Answers the 6 checks directly in
display space (which is exactly what the eye sees)."""
import numpy as np
from PIL import Image

WIN = "variants/statistical/statistical__anchor0.013_sh_knee0.007_sh_pow3.0_target0.14_toe_knee0.0008_toe_pow2.0.png"
BASE = "variants/asinh/asinh__a0.012.png"

w = np.asarray(Image.open(WIN).convert("RGB"), dtype=np.float64)/255.0
b = np.asarray(Image.open(BASE).convert("RGB"), dtype=np.float64)/255.0
H, W, _ = w.shape
cx, cy = W//2, H//2  # crop centered on target
print("shape", w.shape, "center", cx, cy)

def lum(im): return im.mean(-1)
def chroma(im): return im.max(-1) - im.min(-1)  # same as harness
def sat_hsv(im):
    mx = im.max(-1); mn = im.min(-1)
    return np.where(mx>1e-6, (mx-mn)/(mx+1e-6), 0.0)

yy, xx = np.mgrid[0:H, 0:W]
r = np.hypot(xx-cx, yy-cy)

# --- find the actual nebula rim from the data itself (bright structure not at center)
wl, bl = lum(w), lum(b)
# the crescent: brightest non-star nebulosity. Build a luminance-driven nebula mask.
# Use winner luminance; nebula = moderately bright, spatially extended.
sky_ref = np.median(wl[r>320])
print("corner/outer sky lum  winner=%.4f baseline=%.4f"%(sky_ref, np.median(bl[r>320])))

# Region masks by radius (crop is 380 half; nebula crescent spans most of frame)
inner = r < 60
midann = (r>=60)&(r<240)   # where the crescent arc lives in a centered crop
outer = r >= 300           # sky corners

# === CHECK 5 / general: did the winner DIM the ring? compare luminance ===
print("\n=== LUMINANCE (display) ===")
for name, m in [("inner<60",inner),("crescent-ann 60-240",midann),("outer>300 sky",outer),("whole",np.ones_like(r,bool))]:
    print("  %-20s winner_meanL=%.4f base_meanL=%.4f  d=%+.4f   medianL w=%.4f b=%.4f"%(
        name, wl[m].mean(), bl[m].mean(), wl[m].mean()-bl[m].mean(), np.median(wl[m]), np.median(bl[m])))

# === Identify nebula pixels (bright, not sky) to measure rim color where the signal is ===
# threshold relative to sky in each image independently
def neb_mask(L, rmask):
    sky = np.median(L[outer]); sig = np.std(L[outer])
    return rmask & (L > sky + 4*sig)
wn = neb_mask(wl, midann); bn = neb_mask(bl, midann)
print("\nnebula-px count (4sigma over sky, in 60-240 annulus): winner=%d baseline=%d"%(wn.sum(), bn.sum()))
# common nebula pixels (present in BOTH) -> fairest color comparison on identical structure
common = wn & bn
print("common nebula px:", common.sum())

# === CHECK 1 + 6: real hue separation vs oversaturation. ===
print("\n=== CHROMA & HUE on COMMON nebula pixels (same structure both images) ===")
wc, bc = chroma(w), chroma(b)
wss, bss = sat_hsv(w), sat_hsv(b)
m = common if common.sum()>50 else midann
print("  region used:", "common-nebula" if common.sum()>50 else "full 60-240 annulus", "n=",m.sum())
print("  mean CHROMA(max-min)    winner=%.4f  baseline=%.4f   ratio=%.3f"%(wc[m].mean(), bc[m].mean(), wc[m].mean()/(bc[m].mean()+1e-9)))
print("  mean HSV-SATURATION     winner=%.4f  baseline=%.4f   ratio=%.3f"%(wss[m].mean(), bss[m].mean(), wss[m].mean()/(bss[m].mean()+1e-9)))
print("  mean LUM on region      winner=%.4f  baseline=%.4f   ratio=%.3f"%(wl[m].mean(), bl[m].mean(), wl[m].mean()/(bl[m].mean()+1e-9)))
# DECISIVE: chroma normalized by luminance = hue separation independent of brightness
print("  CHROMA / LUM (hue per brightness) winner=%.4f baseline=%.4f  -> %s"%(
    (wc[m].mean()/(wl[m].mean()+1e-9)), (bc[m].mean()/(bl[m].mean()+1e-9)),
    "MORE real hue sep" if (wc[m].mean()/(wl[m].mean()+1e-9))>(bc[m].mean()/(bl[m].mean()+1e-9))*1.02 else "NOT more (chroma rides luminance)"))

# Hue distribution: red-dominant (Ha) vs blue-dominant (OIII) split among nebula px
def hue_split(im, m):
    R,G,B = im[...,0][m], im[...,1][m], im[...,2][m]
    redish = (R>B+0.02).mean(); blueish = (B>R+0.02).mean(); neutral = 1-redish-blueish
    return redish, blueish, neutral
wr,wb_,wnn = hue_split(w,m); br,bb_,bnn = hue_split(b,m)
print("  hue split winner:  R>B %.2f  B>R %.2f  neutral %.2f"%(wr,wb_,wnn))
print("  hue split baseline:R>B %.2f  B>R %.2f  neutral %.2f"%(br,bb_,bnn))

# === CHECK 2: rim blown white anywhere ===
print("\n=== CLIPPING / blown-white ===")
for name,im in [("winner",w),("baseline",b)]:
    L=lum(im)
    near_white = (im.min(-1) > 0.92)  # all 3 channels high = white, not colored
    chhi = chroma(im)
    print("  %s: px with all-ch>0.92 (white)=%d (%.4f%%)  px L>0.95=%d  max-region chroma at L>0.9: meanC=%.3f"%(
        name, near_white.sum(), 100*near_white.mean(), (L>0.95).sum(),
        chhi[L>0.9].mean() if (L>0.9).sum() else 0))
# nebula-rim specific clip
print("  rim(60-240) white px winner=%d baseline=%d"%(((w.min(-1)>0.92)&midann).sum(), ((b.min(-1)>0.92)&midann).sum()))

# === CHECK 3: dark moat / bright halo ring around rim (radial luminance profile) ===
print("\n=== RADIAL LUMINANCE PROFILE (dark-moat / bright-halo detector) ===")
edges = np.arange(0, 380, 20)
print("  r-bin   winner_medL   base_medL")
for i in range(len(edges)-1):
    mm = (r>=edges[i])&(r<edges[i+1])
    if mm.sum()<20: continue
    print("  %3d-%3d   %.4f      %.4f"%(edges[i],edges[i+1], np.median(wl[mm]), np.median(bl[mm])))

# === CHECK 4: sky chroma mottle ===
print("\n=== SKY CHROMA MOTTLE (outer>300) ===")
for name,im in [("winner",w),("baseline",b)]:
    sm = outer
    print("  %s: sky chroma mean=%.4f std=%.4f ; sky lum std=%.4f ; max chroma in sky=%.3f"%(
        name, chroma(im)[sm].mean(), chroma(im)[sm].std(), lum(im)[sm].std(), chroma(im)[sm].max()))

# fraction of sky pixels that are visibly colored (chroma>0.1) -> mottle you'd see
print("  sky px chroma>0.10  winner=%.4f%%  baseline=%.4f%%"%(
    100*(chroma(w)[outer]>0.10).mean(), 100*(chroma(b)[outer]>0.10).mean()))
print("  sky px chroma>0.20  winner=%.4f%%  baseline=%.4f%%"%(
    100*(chroma(w)[outer]>0.20).mean(), 100*(chroma(b)[outer]>0.20).mean()))
