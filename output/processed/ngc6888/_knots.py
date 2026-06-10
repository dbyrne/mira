import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
HERE=r"C:/mira/output/NGC6888_curveshootout"
RA,DEC=303.0,38.35; RIM=(40,170); SKY=(320,500)
hd=fits.open(r"C:/mira/output/ngc6888/ngc6888_cc.fit")[0]; d=np.asarray(hd.data,dtype=np.float64)
rgb=np.moveaxis(d,0,-1); hdr=hd.header; H,W,_=rgb.shape
w=WCS(hdr,naxis=2); cx,cy=w.world_to_pixel_values(RA,DEC); cx,cy=int(round(float(cx))),int(round(float(cy)))
yy,xx=np.mgrid[0:H,0:W]; r=np.hypot(xx-cx,yy-cy); rim=(r>=RIM[0])&(r<RIM[1]); sky=(r>=SKY[0])&(r<SKY[1])
lin=rgb.mean(-1)
win=np.load(HERE+"/_win.npy"); base=np.load(HERE+"/_base.npy")
def L(im):return im.mean(-1)
def C(im):return im.max(-1)-im.min(-1)

# top 8 brightest non-overlapping nebula knots by linear lum within rim
linr=np.where(rim,lin,-1).copy()
pts=[]
for _ in range(8):
    bx,by=np.unravel_index(np.argmax(linr),linr.shape)
    pts.append((bx,by)); linr[max(0,bx-15):bx+15,max(0,by-15):by+15]=-1
print("top rim knots: winner vs baseline (6px patch)")
print("  idx  lin     win_L  base_L   win_C  base_C   chroma winner/base")
wC=[];bC=[]
for i,(bx,by) in enumerate(pts):
    pw=win[bx-6:bx+6,by-6:by+6]; pb=base[bx-6:bx+6,by-6:by+6]
    wc=C(pw).mean(); bc=C(pb).mean(); wC.append(wc); bC.append(bc)
    print("  %2d  %.4f  %.3f  %.3f    %.3f  %.3f    %.2f"%(i,lin[bx,by],L(pw).mean(),L(pb).mean(),wc,bc, wc/(bc+1e-9)))
print("\nMEAN over 8 brightest real knots:  winner chroma=%.4f  baseline chroma=%.4f  (winner is %+.1f%%)"%(
    np.mean(wC),np.mean(bC),100*(np.mean(wC)/np.mean(bC)-1)))

# Decompose the metric win: how much of rim_chroma mean comes from bg vs arc
_,smed,ssig=sigma_clipped_stats(lin[sky])
arc=rim&(lin>smed+5*ssig); bg=rim&~arc
wc_all,bc_all=C(win),C(base)
print("\n=== rim_chroma metric decomposition (rim mean = arc-frac*arc + bg-frac*bg) ===")
print("  rim px=%d  arc px=%d (%.1f%%)  bg px=%d (%.1f%%)"%(rim.sum(),arc.sum(),100*arc.sum()/rim.sum(),bg.sum(),100*bg.sum()/rim.sum()))
print("  winner:  whole-rim C=%.4f | arc C=%.4f  bg C=%.4f"%(wc_all[rim].mean(),wc_all[arc].mean(),wc_all[bg].mean()))
print("  base  :  whole-rim C=%.4f | arc C=%.4f  bg C=%.4f"%(bc_all[rim].mean(),bc_all[arc].mean(),bc_all[bg].mean()))
print("  -> winner beats on rim mean (%.4f>%.4f) but LOSES on the actual arc (%.4f<%.4f). The metric win is carried by the %0.0f%% BACKGROUND."%(
    wc_all[rim].mean(),bc_all[rim].mean(),wc_all[arc].mean(),bc_all[arc].mean(),100*bg.sum()/rim.sum()))

# background luminance crush summary
print("\n=== background crush (the lever that games BOTH chroma-annulus and sky-noise) ===")
for nm,im in [("winner",win),("base",base)]:
    print("  %s: median display lum  rim-bg=%.5f  sky=%.5f"%(nm, L(im)[bg].mean(), np.median(L(im)[sky])))
