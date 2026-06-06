#!/usr/bin/env python
"""Attach a crop-adjusted WCS to a stretched wide-field TIFF -> sky-positioned 16-bit FITS.

The TIFF holds the final stretched+cropped display pixels; the *linear* master FITS holds
the plate solution. We shift CRPIX by the crop offset (pixels trimmed off the top/left,
derived from the crop fractions x the master's real dimensions) and write a (3,H,W) uint16
FITS the viewer app can load directly for sky placement -- atomic pixels+astrometry, no
sidecar to drift. Validates by round-tripping a known object coordinate through both WCSs.

  python tiff_to_skyfits.py --tiff X.tiff --master m.fit --out X.fit \
      --object M51 --top-frac 0.02 --left-frac 0.02 --ra 202.4696 --dec 47.1952
"""
import argparse, warnings
warnings.filterwarnings("ignore")
import numpy as np, tifffile
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales


def main(a):
    img = tifffile.imread(a.tiff)                      # (H,W,3) uint16
    H, W = img.shape[:2]
    mh = fits.open(a.master)[0]
    oH, oW = mh.data.shape[-2], mh.data.shape[-1]      # master NAXIS2, NAXIS1
    top, left = int(oH * a.top_frac), int(oW * a.left_frac)

    ow = WCS(mh.header, naxis=2)                        # original solution (naxis=2: RGB cube + SIP)
    nw = ow.deepcopy()
    nw.wcs.crpix[0] -= left                            # CRPIX1 (x) <- removed cols on the left
    nw.wcs.crpix[1] -= top                             # CRPIX2 (y) <- removed rows on top

    cube = np.moveaxis(img, -1, 0).astype(np.uint16)   # (3,H,W): R,G,B planes
    hdr = nw.to_header(relax=True)                      # relax=True keeps SIP distortion terms
    hdr["OBJECT"] = a.object
    hdr.add_history(f"stretched+cropped sky master; crop top={top}px left={left}px of {oW}x{oH}")
    fits.PrimaryHDU(cube, hdr).writeto(a.out, overwrite=True)

    # --- validate: object pixel must shift by exactly (left, top) and stay in-frame ---
    vw = WCS(fits.open(a.out)[0].header, naxis=2)
    sx, sy = (proj_plane_pixel_scales(vw) * 3600.0)    # arcsec/px
    if a.ra is not None:
        ox, oy = (float(v) for v in ow.world_to_pixel_values(a.ra, a.dec))
        nx, ny = (float(v) for v in vw.world_to_pixel_values(a.ra, a.dec))
        ok = abs(nx - (ox - left)) < 0.5 and abs(ny - (oy - top)) < 0.5 and 0 <= nx < W and 0 <= ny < H
        print(f"  VALIDATE {a.object}: orig_px=({ox:.1f},{oy:.1f}) new_px=({nx:.1f},{ny:.1f}) "
              f"expect=({ox-left:.1f},{oy-top:.1f}) in_frame={0<=nx<W and 0<=ny<H} -> {'OK' if ok else 'FAIL'}")
    cra, cdec = (float(v) for v in vw.pixel_to_world_values(W / 2.0, H / 2.0))
    cr = vw.pixel_to_world_values([0, W - 1, W - 1, 0], [0, 0, H - 1, H - 1])
    print(f"WROTE {a.out}  {W}x{H}  scale=({sx:.3f},{sy:.3f}) arcsec/px  center=({cra:.4f},{cdec:.4f})")
    names = ["TL", "TR", "BR", "BL"]
    for n, ra, dec in zip(names, np.atleast_1d(cr[0]), np.atleast_1d(cr[1])):
        print(f"  corner {n}: ra={float(ra):.4f}  dec={float(dec):.4f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tiff", required=True)
    p.add_argument("--master", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--object", default="")
    p.add_argument("--top-frac", dest="top_frac", type=float, default=0.0)
    p.add_argument("--left-frac", dest="left_frac", type=float, default=0.0)
    p.add_argument("--ra", type=float, default=None)
    p.add_argument("--dec", type=float, default=None)
    main(p.parse_args())
