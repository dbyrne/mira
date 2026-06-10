#!/usr/bin/env python
"""Veil panel-1 test-run validator. Run on a SOLVED test frame to confirm the
S30's frame orientation + framing before trusting the 2-panel mosaic plan.

Usage:  python output/catskills_jun18/check_orientation.py <solved_frame.fits>
        (the frame must already carry WCS -> run `mira solve` on the dest dir first)

Checks:
  1. Long-axis (N-S?) position angle  -- the mosaic split assumes long ~N-S.
  2. Where NGC 6960 (Witch's Broom) lands -- framing.
  3. Pixel scale sanity (~3.66"/px).
"""
import sys, math
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

NGC6960 = (311.40, 30.72)   # Western Veil / 52 Cyg

def bearing(ra0, dec0, ra1, dec1):
    dra = (ra1 - ra0) * math.cos(math.radians((dec0 + dec1) / 2))
    return math.degrees(math.atan2(dra, dec1 - dec0)) % 360

def main(path):
    h = fits.getheader(path)
    if "CRVAL1" not in h:
        print("NO WCS -- run `mira solve --lights <dir>` first."); return
    w = WCS(h, naxis=2); nx, ny = h["NAXIS1"], h["NAXIS2"]
    # long axis = the larger of NAXIS1/NAXIS2 (S30: NAXIS2=3840 is long)
    long_is_y = ny >= nx
    cx, cy = nx / 2, ny / 2
    r0, d0 = w.all_pix2world(cx, cy, 0)
    # step 100px along the LONG axis
    if long_is_y: r1, d1 = w.all_pix2world(cx, cy + 100, 0)
    else:         r1, d1 = w.all_pix2world(cx + 100, cy, 0)
    pa = bearing(float(r0), float(d0), float(r1), float(d1))
    # fold to nearest N-S (0/180) vs E-W (90/270)
    off_ns = min(abs(pa - 0), abs(pa - 180), abs(pa - 360))
    verdict = "N-S (GOOD - mosaic split valid)" if off_ns < 20 else "NOT N-S (rotated! flip the split)"
    print(f"field center: RA {float(r0):.3f}  Dec {float(d0):+.3f}")
    print(f"long-axis bearing on sky: {pa:.0f} deg  ->  {verdict}  (off-N-S by {off_ns:.0f} deg)")
    print(f"pixel scale: {abs(h.get('CD1_1', h.get('CDELT1', 0)))*3600:.2f} arcsec/px (expect ~3.66)")
    # framing: where does NGC6960 land?
    px, py = w.all_world2pix(*NGC6960, 0)
    inframe = (0 <= px < nx) and (0 <= py < ny)
    print(f"NGC 6960 at px ({px:.0f},{py:.0f})  in-frame={inframe}  "
          f"(edge dist {min(px, nx-px, py, ny-py):.0f}px)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: check_orientation.py <solved_frame.fits>"); sys.exit(1)
    main(sys.argv[1])
