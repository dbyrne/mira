"""Compare on a FIXED structural crescent mask derived from LINEAR data (curve-invariant),
so winner & baseline are judged on IDENTICAL nebula pixels. Also render crops for the eye."""
import os, numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
from PIL import Image
HERE=r"C:/mira/output/NGC6888_curveshootout"
RA,DEC=303.0,38.35; RIM=(40,170); SKY=(320,500); SAT=1.9; WHITE_PCT=99.99

hd=fits.open(r"C:/mira/output/ngc6888/ngc6888_cc.fit")[0]; d=np.asarray(hd.data,dtype=np.float64)
rgb=np.moveaxis(d,0,-1); hdr=hd.header
H,W,_=rgb.shape
w=WCS(hdr,naxis=2); cx,cy=w.world_to_pixel_values(RA,DEC); cx,cy=int(round(float(cx))),int(round(float(cy)))
yy,xx=np.mgrid[0:H,0:W]; r=np.hypot(xx-cx,yy-cy)
rim=(r>=RIM[0])&(r<RIM[1]); sky=(r>=SKY[0])&(r<SKY[1])

# linear luminance, curve-invariant
lin=rgb.mean(-1)
_,smed,ssig=sigma_clipped_stats(lin[sky])
# structural crescent = linear signal well above sky, within the rim annulus
arc = rim & (lin > smed + 5*ssig)
print("linear sky med=%.5g sig=%.5g  arc(>5sig in rim) px=%d (%.1f%% of rim)"%(smed,ssig,arc.sum(),100*arc.sum()/rim.sum()))

win=np.load(HERE+"/_win.npy"); base=np.load(HERE+"/_base.npy")
def L(im):return im.mean(-1)
def C(im):return im.max(-1)-im.min(-1)
wl,bl=L(win),L(base); wc,bc=C(win),C(base)

print("\n=== ON IDENTICAL STRUCTURAL ARC PIXELS (curve-invariant mask, n=%d) ==="%arc.sum())
print("  display lum     winner=%.4f base=%.4f  (%+.1f%%)"%(wl[arc].mean(),bl[arc].mean(),100*(wl[arc].mean()/bl[arc].mean()-1)))
print("  chroma(max-min) winner=%.4f base=%.4f  (%+.1f%%)"%(wc[arc].mean(),bc[arc].mean(),100*(wc[arc].mean()/bc[arc].mean()-1)))
sw=(wc[arc]/(wl[arc]+1e-9)).mean(); sb=(bc[arc]/(bl[arc]+1e-9)).mean()
print("  chroma/lum(hue purity) winner=%.4f base=%.4f  (%+.1f%%)"%(sw,sb,100*(sw/sb-1)))
# arc-over-sky contrast
print("  arc lum - sky lum  winner=%.4f base=%.4f"%(wl[arc].mean()-np.median(wl[sky]), bl[arc].mean()-np.median(bl[sky])))
# hue balance on arc
def hue(im,m):
    R,G,B=im[...,0][m],im[...,1][m],im[...,2][m]
    return float(((R>B+0.01)&(R>G)).mean()), float(((B>R+0.01)).mean())
print("  arc hue  winner red=%.2f teal=%.2f | base red=%.2f teal=%.2f"%(*hue(win,arc),*hue(base,arc)))

# brightest-knot test (single hottest patch, definitely real nebula)
bx,by=np.unravel_index(np.argmax(np.where(rim,lin,-1)),lin.shape)
print("\n  brightest rim knot at (%d,%d) lin=%.4g"%(by,bx,lin[bx,by]))
for nm,im in [("winner",win),("base",base)]:
    patch=im[max(0,bx-6):bx+6,max(0,by-6):by+6]
    print("    %s patch meanL=%.3f meanC=%.3f maxL=%.3f RGB=%.3f/%.3f/%.3f"%(nm,L(patch).mean(),C(patch).mean(),L(patch).max(),patch[...,0].mean(),patch[...,1].mean(),patch[...,2].mean()))

# ---- render center crops (760x760, same as PNGs) AND a tight arc crop, side by side, AMPLIFIED for eyeballing
ch=380
def crop(im):
    return im[max(0,cy-ch):cy+ch, max(0,cx-ch):cx+ch]
cw,cb=crop(win),crop(base)
# side-by-side full crop
sbs=np.concatenate([cw, np.ones((cw.shape[0],8,3)), cb],axis=1)
Image.fromarray((np.clip(sbs,0,1)*255+0.5).astype(np.uint8),"RGB").save(HERE+"/_sbs_win_base.png")
# a 3x luminance-amplified version to expose dark-moat/halo and mottle the eye misses at these low values
def amp(im,k=3.0):
    lum=im.mean(-1,keepdims=True);
    return np.clip(im*k,0,1)
sbs_amp=np.concatenate([amp(cw),np.ones((cw.shape[0],8,3)),amp(cb)],axis=1)
Image.fromarray((sbs_amp*255+0.5).astype(np.uint8),"RGB").save(HERE+"/_sbs_amp3x.png")
print("\nwrote _sbs_win_base.png (winner|baseline crop) and _sbs_amp3x.png (3x amplified)")
print("crop center in crop-coords:", ch, ch)
