"""Decisive adversarial decomposition, in the harness's exact space (sat=1.9, correct geom).
_win.npy / _base.npy are the post-saturation [0,1] RGB full-frame renders."""
import os, numpy as np
from astropy.io import fits
from astropy.wcs import WCS
HERE=r"C:/mira/output/NGC6888_curveshootout"
RA,DEC=303.0,38.35; RIM=(40,170); HALO=(170,250); SKY=(320,500); SAT=1.9

win=np.load(HERE+"/_win.npy"); base=np.load(HERE+"/_base.npy")
hd=fits.open(r"C:/mira/output/ngc6888/ngc6888_cc.fit")[0]; hdr=hd.header
H,W,_=win.shape
w=WCS(hdr,naxis=2); cx,cy=w.world_to_pixel_values(RA,DEC); cx,cy=int(round(float(cx))),int(round(float(cy)))
yy,xx=np.mgrid[0:H,0:W]; r=np.hypot(xx-cx,yy-cy)
rim=(r>=RIM[0])&(r<RIM[1]); halo=(r>=HALO[0])&(r<HALO[1]); sky=(r>=SKY[0])&(r<SKY[1]); cen=r<RIM[0]
print("center px",cx,cy,"  rim n=%d"%rim.sum())

def L(im): return im.mean(-1)
def C(im): return im.max(-1)-im.min(-1)
wl,bl=L(win),L(base); wc,bc=C(win),C(base)

# ---- 1. UN-SATURATE both to remove the sat=1.9 multiplier, measure native chroma/hue ----
def desat(im, sat):
    lum=im.mean(-1,keepdims=True)
    # saturate did: out = clip(lum + (im-lum)*sat). Inverting where unclipped: pre = lum + (im-lum)/sat
    return lum + (im-lum)/sat   # may exceed [0,1] where clip happened; fine for hue/ratio
win0=desat(win,SAT); base0=desat(base,SAT)

print("\n=== Q6/Q1: is rim chroma gain REAL hue separation? ===")
# (a) post-sat chroma (the metric)
print("post-sat rim chroma   winner=%.4f base=%.4f  d=%+.1f%%"%(wc[rim].mean(),bc[rim].mean(),100*(wc[rim].mean()/bc[rim].mean()-1)))
# (b) post-sat rim luminance
print("post-sat rim lum      winner=%.4f base=%.4f  d=%+.1f%%"%(wl[rim].mean(),bl[rim].mean(),100*(wl[rim].mean()/bl[rim].mean()-1)))
# (c) CHROMA NORMALIZED BY LUMINANCE = saturation = hue purity independent of brightness
rs_w=(wc[rim]/(wl[rim]+1e-9)).mean(); rs_b=(bc[rim]/(bl[rim]+1e-9)).mean()
print("rim chroma/lum (hue purity) winner=%.4f base=%.4f  d=%+.1f%%   <-- if ~0, the chroma 'gain' is purely the +lum"%(rs_w,rs_b,100*(rs_w/rs_b-1)))
# (d) native (pre-sat) hue purity
rs_w0=(C(win0)[rim]/(L(win0)[rim]+1e-9)).mean(); rs_b0=(C(base0)[rim]/(L(base0)[rim]+1e-9)).mean()
print("rim chroma/lum PRE-sat      winner=%.4f base=%.4f  d=%+.1f%%"%(rs_w0,rs_b0,100*(rs_w0/rs_b0-1)))

# ---- HUE ANGLE: does the winner separate Ha-red from OIII-teal MORE, or just scale one hue? ----
def hue_frac(im, m):
    R,G,B=im[...,0][m],im[...,1][m],im[...,2][m]
    red=(R>B+0.01)&(R>G); teal=(B>R+0.01)|((G>R+0.01)&(B>=R));
    return float(red.mean()), float(teal.mean()), float(1-red.mean()-teal.mean())
wr,wt,wn=hue_frac(win,rim); br,bt,bn=hue_frac(base,rim)
print("\nrim hue fractions  winner: red=%.2f teal=%.2f neutral=%.2f"%(wr,wt,wn))
print("rim hue fractions  base  : red=%.2f teal=%.2f neutral=%.2f"%(br,bt,bn))
# bi-modality: a real 2-hue image has BOTH red and teal substantial; oversaturating one hue shifts the balance
print("  -> winner red+teal coverage=%.2f vs base=%.2f  (higher+balanced = more honest multi-hue)"%(wr+wt,br+bt))

# ---- 2. RIM BLOWN WHITE ----
print("\n=== Q2: rim blown white ===")
for nm,im in [("winner",win),("base",base)]:
    Li=L(im); white=(im.min(-1)>0.9)  # all channels high
    print("  %s rim: lum>=0.99 frac=%.4f  all-ch>0.9(white) frac=%.5f  max rim lum=%.3f"%(nm, (Li[rim]>=0.99).mean(), (white&rim).mean(), Li[rim].max()))

# ---- 3. DARK MOAT / BRIGHT HALO RING (radial median profile, fine bins across rim->halo->sky) ----
print("\n=== Q3: dark-moat / bright-halo ring (radial median lum) ===")
edges=list(range(0,520,20))
print("  r       win_medL   base_medL   (rim 40-170, halo 170-250, sky 320-500)")
prof_w=[]; prof_b=[]
for i in range(len(edges)-1):
    mm=(r>=edges[i])&(r<edges[i+1])
    if mm.sum()<50: continue
    a=float(np.median(wl[mm])); b=float(np.median(bl[mm])); prof_w.append((edges[i],a)); prof_b.append((edges[i],b))
    tag=""
    if edges[i]>=160 and edges[i]<260: tag="<-halo"
    print("  %3d-%3d  %.5f    %.5f %s"%(edges[i],edges[i+1],a,b,tag))
# A bright-halo ring = local MAX in halo zone above both rim-inner and sky; dark moat = local MIN below sky just outside rim
import numpy as np
pw=np.array([v for _,v in prof_w]);
print("  monotonic non-increasing winner profile?", bool(np.all(np.diff(pw)<=1e-4)), " (True = no bright-halo bump)")

# ---- 4. SKY CHROMA MOTTLE ----
print("\n=== Q4: sky chroma mottle (320-500) ===")
for nm,im in [("winner",win),("base",base)]:
    ch=C(im)[sky]
    print("  %s sky: chroma mean=%.4f std=%.4f  frac chroma>0.10=%.3f%%  frac>0.20=%.3f%%"%(
        nm, ch.mean(), ch.std(), 100*(ch>0.10).mean(), 100*(ch>0.20).mean()))

# ---- 5. WON ONLY BY DIMMING? compare what changed ----
print("\n=== Q5: dim-to-win check (background vs rim) ===")
print("  rim_lum   winner=%.4f base=%.4f  (%+.1f%%)"%(wl[rim].mean(),bl[rim].mean(),100*(wl[rim].mean()/bl[rim].mean()-1)))
print("  sky_lum   winner=%.4f base=%.4f  (%+.1f%%)"%(np.median(wl[sky]),np.median(bl[sky]),100*(np.median(wl[sky])/np.median(bl[sky])-1)))
print("  halo_lum  winner=%.4f base=%.4f  (%+.1f%%)"%(np.median(wl[halo]),np.median(bl[halo]),100*(np.median(wl[halo])/np.median(bl[halo])-1)))
print("  midtone   winner=%.4f base=%.4f  (%+.1f%%)"%(np.median(wl),np.median(bl),100*(np.median(wl)/np.median(bl)-1)))
# rim-over-sky CONTRAST (signal visibility) -- the honest 'is the ring more visible' metric
rc_w=wl[rim].mean()-np.median(wl[sky]); rc_b=bl[rim].mean()-np.median(bl[sky])
print("  rim-minus-sky lum CONTRAST winner=%.4f base=%.4f"%(rc_w,rc_b))

# ---- BONUS: how much of the rim annulus is actually faint sky vs real nebula? ----
# rim 40-170 is HUGE; most of it may be background between crescent arcs -> rim_chroma diluted/driven by bg
sky_med_w=np.median(wl[sky]); sky_sig_w=np.std(wl[sky])
neb_in_rim=(wl>sky_med_w+3*sky_sig_w)&rim
print("\nrim annulus composition: %.1f%% of rim px are >3sigma nebula (winner); rest is background-level"%(100*neb_in_rim.mean()/rim.mean() if rim.mean() else 0))
print("  rim_chroma on NEBULA-only px:  winner=%.4f base=%.4f"%(wc[neb_in_rim].mean() if neb_in_rim.sum() else 0, bc[neb_in_rim].mean() if neb_in_rim.sum() else 0))
neb_b=(bl>np.median(bl[sky])+3*np.std(bl[sky]))&rim
print("  nebula-px count winner=%d base=%d"%(neb_in_rim.sum(), neb_b.sum()))
