#!/usr/bin/env python
"""Test-frame framing validator. Run on a SOLVED test frame to confirm the
S30's frame orientation + where the key feature lands before committing the
night to the pointing.

Usage:  python output/trips/catskills_jun20/check_orientation.py <solved_frame.fits> [ra dec [name]]
        (the frame must already carry WCS -> run `mira solve` on the dest dir first;
         default feature = NGC 6960 from the original Veil plan — pass the
         target explicitly, e.g. the Elephant Trunk:  ... 324.05 57.49 IC1396A)

Checks:
  1. Long-axis (N-S?) position angle  -- single-frame IC 1396 needs long ~N-S
     just like the old mosaic split did.
  2. Where the named feature lands -- framing.
  3. Pixel scale sanity (~3.66"/px).
"""
import sys, math
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

NGC6960 = (311.40, 30.72)   # Western Veil / 52 Cyg (legacy default)

def bearing(ra0, dec0, ra1, dec1):
    dra = (ra1 - ra0) * math.cos(math.radians((dec0 + dec1) / 2))
    return math.degrees(math.atan2(dra, dec1 - dec0)) % 360

def main(path, target=NGC6960, name="NGC 6960"):
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
    # framing: where does the feature land?
    px, py = w.all_world2pix(*target, 0)
    inframe = (0 <= px < nx) and (0 <= py < ny)
    print(f"{name} at px ({px:.0f},{py:.0f})  in-frame={inframe}  "
          f"(edge dist {min(px, nx-px, py, ny-py):.0f}px)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: check_orientation.py <solved_frame.fits> [ra dec [name]]"); sys.exit(1)
    tgt, nm = NGC6960, "NGC 6960"
    if len(sys.argv) >= 4:
        tgt = (float(sys.argv[2]), float(sys.argv[3]))
        nm = sys.argv[4] if len(sys.argv) > 4 else f"({tgt[0]:.2f},{tgt[1]:+.2f})"
    main(sys.argv[1], tgt, nm)
