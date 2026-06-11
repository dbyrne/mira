#!/usr/bin/env python
"""Mosaic the two Veil panels into one WCS frame.

Each panel stack (from `mira stack`) is an RGB cube (3,ny,nx) with a WCS from
plate-solving. We reproject + coadd both onto a common optimal celestial WCS,
per channel, averaging in the ~22% overlap. Output is a linear RGB FITS ready
for GraXpert + PCC + stretch.

Run:  python output/trips/catskills_jun20/mosaic_veil.py
Deps: reproject, astropy (already installed).
"""
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from reproject import reproject_interp
from reproject.mosaicking import find_optimal_celestial_wcs, reproject_and_coadd

P1 = "output/trips/catskills_jun20/veil_p1_west_stack.fit"
P2 = "output/trips/catskills_jun20/veil_p2_east_stack.fit"
OUT = "output/trips/catskills_jun20/veil_mosaic.fit"


def load(path):
    h = fits.open(path)[0]
    d = np.asarray(h.data, dtype=np.float32)        # (3,ny,nx)
    if d.ndim == 2:
        d = d[None]                                  # treat mono as 1 channel
    w = WCS(h.header, naxis=2)
    return d, w


def main():
    d1, w1 = load(P1)
    d2, w2 = load(P2)
    nch = d1.shape[0]
    # common output WCS covering both panels (use channel 0 footprints)
    wcs_out, shape_out = find_optimal_celestial_wcs(
        [(d1[0], w1), (d2[0], w2)], auto_rotate=True)
    print(f"mosaic output: {shape_out[1]}x{shape_out[0]} px, "
          f"scale {abs(wcs_out.proj_plane_pixel_scales()[0].to('arcsec').value):.2f}\"/px")
    chans = []
    for c in range(nch):
        arr, _fp = reproject_and_coadd(
            [(d1[c], w1), (d2[c], w2)],
            wcs_out, shape_out=shape_out,
            reproject_function=reproject_interp,
            combine_function="mean")
        chans.append(arr.astype(np.float32))
        print(f"  channel {c} done")
    cube = np.stack(chans, 0)
    hdr = wcs_out.to_header()
    fits.writeto(OUT, cube, hdr, overwrite=True)
    print("wrote", OUT, cube.shape)


if __name__ == "__main__":
    main()
