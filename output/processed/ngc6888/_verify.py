import sys, os, json, importlib.util, warnings
warnings.filterwarnings("ignore")
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats

HERE = r"C:/mira/output/NGC6888_curveshootout"

def load_rgb(path):
    hd = fits.open(path)[0]
    d = np.asarray(hd.data, dtype=np.float64)
    if d.ndim == 2: rgb = np.stack([d]*3,-1)
    elif d.shape[0]==3: rgb = np.moveaxis(d,0,-1)
    elif d.shape[-1]==3: rgb = d
    else: rgb = np.stack([d.mean(0)]*3,-1)
    return rgb, hd.header

def load_curve(name):
    spec = importlib.util.spec_from_file_location("c_"+name, os.path.join(HERE,"curves",name+".py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def locate(header, shape, ra, dec):
    try:
        w = WCS(header, naxis=2)
        x,y = w.world_to_pixel_values(ra,dec)
        return int(round(float(x))), int(round(float(y)))
    except Exception:
        return shape[1]//2, shape[0]//2

def normalize(rgb, white_pct):
    x = rgb.astype(np.float64).copy()
    for c in range(3):
        _,med,_ = sigma_clipped_stats(rgb[...,c]); x[...,c] = rgb[...,c]-med
    white = float(np.percentile(x, white_pct))
    return np.clip(x/(white+1e-12),0,1), white

def saturate(rgb, sat):
    if sat==1.0: return rgb
    lum = rgb.mean(-1,keepdims=True)
    return np.clip(lum+(rgb-lum)*sat,0,1)

def render(x01, curve, params, sat):
    y = curve.apply(x01.copy(), **params)
    y = np.clip(np.nan_to_num(y,nan=0,posinf=1,neginf=0),0,1)
    return saturate(y,sat)

def stats_chroma(stretched, linear, hdr, ra, dec, rim, halo, sky):
    H,W,_ = stretched.shape
    lum = stretched.mean(-1)
    chroma = stretched.max(-1)-stretched.min(-1)
    llin = linear.mean(-1)
    cx,cy = locate(hdr, lum.shape, ra, dec)
    yy,xx = np.mgrid[0:H,0:W]
    r = np.hypot(xx-cx, yy-cy)
    rimm=(r>=rim[0])&(r<rim[1]); halom=(r>=halo[0])&(r<halo[1]); skym=(r>=sky[0])&(r<sky[1]); cen=r<rim[0]
    skp = stretched[skym]
    return dict(rim_chroma=round(float(chroma[rimm].mean()),4), rim_lum=round(float(lum[rimm].mean()),4),
        rim_clip=round(float((lum[rimm]>=0.99).mean()),4), center_chroma=round(float(chroma[cen].mean()),4),
        halo_lum=round(float(np.median(lum[halom])),4), sky_lum=round(float(np.median(lum[skym])),4),
        sky_noise_lum=round(float(np.std(lum[skym])),4),
        sky_noise_chroma=round(float((np.std(skp[:,0]-skp[:,1])+np.std(skp[:,2]-skp[:,1]))/2),4),
        midtone=round(float(np.median(lum)),4))

if __name__=="__main__":
    inp = os.path.join(HERE,"../ngc6888/ngc6888_bg_dn.fits")
    rgb,hdr = load_rgb(inp)
    x01,white = normalize(rgb, 99.99)
    print("white",white, "shape",rgb.shape)
    stat = load_curve("statistical"); asinh = load_curve("asinh")
    win = render(x01, stat, {"anchor":0.013,"target":0.14,"sh_knee":0.007,"sh_pow":3.0,"toe_knee":0.0008,"toe_pow":2.0}, 1.6)
    base = render(x01, asinh, {"a":0.012}, 1.6)
    # target manifest: win rim_chroma 0.0234 rim_lum 0.0213 center_chroma 0.0404 sky_noise_lum 0.0265
    # NGC6888 center approx
    for ra,dec in [(303.0,38.35),(303.05,38.355),(302.99,38.345)]:
        cx,cy = locate(hdr, rgb.shape[:2], ra, dec)
        print("center px for",ra,dec,"=",cx,cy)
    # grid search geometry against manifest
    targ_win = dict(rim_chroma=0.0234, rim_lum=0.0213, center_chroma=0.0404, sky_noise_lum=0.0265, sky_lum=0.0005, halo_lum=0.0012)
    best=None
    import itertools
    ras=[302.95,303.0,303.05,303.1]; decs=[38.3,38.35,38.4]
    rims=[(4,11),(20,60),(40,120),(60,200),(100,400),(150,600)]
    halos=[(12,20),(60,120),(120,300),(400,700)]
    skys=[(80,200),(200,500),(700,1000),(900,1200)]
    for ra in ras:
      for dec in decs:
        for rim in rims:
          for halo in halos:
            for sky in skys:
              try:
                s = stats_chroma(win, rgb, hdr, ra,dec,rim,halo,sky)
                err = abs(s['rim_chroma']-targ_win['rim_chroma'])+abs(s['rim_lum']-targ_win['rim_lum'])+abs(s['center_chroma']-targ_win['center_chroma'])+abs(s['sky_noise_lum']-targ_win['sky_noise_lum'])
                if best is None or err<best[0]:
                    best=(err,ra,dec,rim,halo,sky,s)
              except Exception as e:
                pass
    print("BEST GEOMETRY err=%.4f"%best[0], "ra",best[1],"dec",best[2],"rim",best[3],"halo",best[4],"sky",best[5])
    print("  reproduced stats:",best[6])
    print("  target          :",targ_win)
