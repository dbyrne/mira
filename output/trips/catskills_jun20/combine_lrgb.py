#!/usr/bin/env python
"""Register the four Esprit 80 mono filter masters onto a common grid and
build the RGB cube for color calibration.

Each per-filter stack (from `mira stack` on plate-solved subs) carries its own
WCS. L is the deepest -> it defines the target grid (no interpolation on L);
R/G/B are reprojected onto it and stacked into a (3,ny,nx) cube with L's WCS,
ready for Siril PCC + `mira finish`. The L master is used as-is for the
luminance blend later (see the M51 all-lum recipe:
output/processed/m51/refinish_m51.py).

Run:  python output/trips/catskills_jun20/combine_lrgb.py
Deps: reproject, astropy (already installed).
"""
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from reproject import reproject_interp

WORK = "output/trips/catskills_jun20"
L = f"{WORK}/iris_L_stack.fit"
RGB = {c: f"{WORK}/iris_{c}_stack.fit" for c in "RGB"}
OUT = f"{WORK}/iris_RGB.fit"


def load(path):
    h = fits.open(path)[0]
    d = np.asarray(h.data, dtype=np.float32)
    if d.ndim == 3:
        d = d[0]                                 # mono stored as (1,ny,nx)
    return d, WCS(h.header, naxis=2), h.header


def main():
    dl, wl, hl = load(L)
    print(f"L grid: {dl.shape[1]}x{dl.shape[0]} px (reference)")
    chans = []
    for c in "RGB":
        d, w, _ = load(RGB[c])
        arr, fp = reproject_interp((d, w), wl, shape_out=dl.shape)
        cov = float(np.nanmean(fp)) * 100
        print(f"  {c}: reprojected, {cov:.0f}% of L grid covered")
        chans.append(np.nan_to_num(arr).astype(np.float32))
    cube = np.stack(chans, 0)
    hdr = wl.to_header()
    fits.writeto(OUT, cube, hdr, overwrite=True)
    print("wrote", OUT, cube.shape, "— PCC this, then blend", L, "as luminance")


if __name__ == "__main__":
    main()
