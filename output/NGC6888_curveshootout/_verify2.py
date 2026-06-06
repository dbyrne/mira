import os, json, importlib.util, warnings
warnings.filterwarnings("ignore")
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats

HERE = r"C:/mira/output/NGC6888_curveshootout"
INP  = r"C:/mira/output/ngc6888/ngc6888_cc.fit"
RA, DEC = 303.0, 38.35
RIM=(40,170); HALO=(170,250); SKY=(320,500); SAT=1.9; WHITE_PCT=99.99

def load_rgb(path):
    hd = fits.open(path)[0]; d = np.asarray(hd.data, dtype=np.float64)
    if d.ndim==2: rgb=np.stack([d]*3,-1)
    elif d.shape[0]==3: rgb=np.moveaxis(d,0,-1)
    elif d.shape[-1]==3: rgb=d
    else: rgb=np.stack([d.mean(0)]*3,-1)
    return rgb, hd.header
def load_curve(name):
    spec=importlib.util.spec_from_file_location("c_"+name, os.path.join(HERE,"curves",name+".py"))
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
def locate(header, shape, ra, dec):
    try:
        w=WCS(header,naxis=2); x,y=w.world_to_pixel_values(ra,dec); return int(round(float(x))),int(round(float(y)))
    except Exception: return shape[1]//2, shape[0]//2
def normalize(rgb, white_pct):
    x=rgb.astype(np.float64).copy()
    for c in range(3):
        _,med,_=sigma_clipped_stats(rgb[...,c]); x[...,c]=rgb[...,c]-med
    white=float(np.percentile(x,white_pct)); return np.clip(x/(white+1e-12),0,1), white
def saturate(rgb, sat):
    if sat==1.0: return rgb
    lum=rgb.mean(-1,keepdims=True); return np.clip(lum+(rgb-lum)*sat,0,1)
def render(x01, curve, params, sat):
    y=curve.apply(x01.copy(), **params); y=np.clip(np.nan_to_num(y,nan=0,posinf=1,neginf=0),0,1); return saturate(y,sat)

def masks(hdr, shape):
    H,W=shape
    cx,cy=locate(hdr,(H,W),RA,DEC)
    yy,xx=np.mgrid[0:H,0:W]; r=np.hypot(xx-cx,yy-cy)
    return r, (r>=RIM[0])&(r<RIM[1]), (r>=HALO[0])&(r<HALO[1]), (r>=SKY[0])&(r<SKY[1]), r<RIM[0], (cx,cy)

def stats_chroma(stretched, linear, hdr):
    H,W,_=stretched.shape
    lum=stretched.mean(-1); chroma=stretched.max(-1)-stretched.min(-1); llin=linear.mean(-1)
    r,rim,halo,sky,cen,_=masks(hdr,(H,W))
    skp=stretched[sky]; s_sky=float(np.median(llin[sky])); s_sig=float(np.std(llin[sky]))+1e-12
    return dict(rim_chroma=round(float(chroma[rim].mean()),4), rim_lum=round(float(lum[rim].mean()),4),
        rim_clip=round(float((lum[rim]>=0.99).mean()),4), center_chroma=round(float(chroma[cen].mean()),4),
        halo_contrast=round(float(np.median(lum[halo])-np.median(lum[sky])),5),
        halo_lum=round(float(np.median(lum[halo])),4), sky_lum=round(float(np.median(lum[sky])),4),
        sky_noise_lum=round(float(np.std(lum[sky])),4),
        sky_noise_chroma=round(float((np.std(skp[:,0]-skp[:,1])+np.std(skp[:,2]-skp[:,1]))/2),4),
        midtone=round(float(np.median(lum)),4),
        lin_rim_snr=round((float(np.median(llin[rim]))-s_sky)/s_sig,1),
        lin_halo_snr=round((float(np.median(llin[halo]))-s_sky)/s_sig,2))

rgb,hdr=load_rgb(INP); x01,white=normalize(rgb,WHITE_PCT)
print("INPUT",INP,"shape",rgb.shape,"white",white)
stat=load_curve("statistical"); asinh=load_curve("asinh")
WP={"anchor":0.013,"target":0.14,"sh_knee":0.007,"sh_pow":3.0,"toe_knee":0.0008,"toe_pow":2.0}
win=render(x01,stat,WP,SAT); base=render(x01,asinh,{"a":0.012},SAT)
sw=stats_chroma(win,rgb,hdr); sb=stats_chroma(base,rgb,hdr)
print("\n=== REPRODUCED STATS (should match manifest) ===")
man_w=dict(rim_chroma=0.0234,rim_lum=0.0213,rim_clip=0.0003,center_chroma=0.0404,halo_contrast=0.00068,halo_lum=0.0012,sky_lum=0.0005,sky_noise_lum=0.0265,sky_noise_chroma=0.0144,midtone=0.0012)
man_b=dict(rim_chroma=0.0225,rim_lum=0.0197,rim_clip=0.0003,center_chroma=0.0362,halo_contrast=0.00096,halo_lum=0.0027,sky_lum=0.0017,sky_noise_lum=0.0378,sky_noise_chroma=0.0158,midtone=0.0027)
for k in man_w:
    print("  %-18s winner repro=%.4f man=%.4f %s | base repro=%.4f man=%.4f %s"%(
        k, sw[k], man_w[k], "OK" if abs(sw[k]-man_w[k])<0.0006 else "MISMATCH",
        sb[k], man_b[k], "OK" if abs(sb[k]-man_b[k])<0.0006 else "MISMATCH"))

# Save full-res renders for visual inspection (full frame + crop)
from PIL import Image
def save(arr, path):
    Image.fromarray((arr*255+0.5).astype(np.uint8),"RGB").save(path)
np.save(os.path.join(HERE,"_win.npy"), win)
np.save(os.path.join(HERE,"_base.npy"), base)
print("\nsaved _win.npy _base.npy for analysis")
