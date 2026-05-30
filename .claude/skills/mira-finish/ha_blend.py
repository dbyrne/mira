#!/usr/bin/env python
"""Hα-blend experiment for M51: boost the broadband base's red channel by the
HII (Hα) emission captured in the LP (dual-band) stack.

The Seestar LP filter is dual-band (Hα+OIII), so the LP stack's RED channel is
~continuum-suppressed Hα — i.e. the HII regions. We reproject that onto the
combined+PCC broadband base (C_cc, via the real plate solutions) and add a
weighted Hα excess to red, so M51's star-forming knots pop.

  python ha_blend.py [K=0.4]      # K = Hα boost strength
"""
import sys, warnings
warnings.filterwarnings("ignore")
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from reproject import reproject_interp

K = float(sys.argv[1]) if len(sys.argv) > 1 else 0.4


def load(path):
    h = fits.open(path)[0]
    d = np.asarray(h.data, dtype=np.float64)
    rgb = np.moveaxis(d, 0, -1) if d.shape[0] == 3 else d  # -> H,W,3
    return rgb, WCS(h.header, naxis=2), h.header


A, Awcs, _ = load("masters/A_bg_dn.fits")     # LP (Hα source)
C, Cwcs, Chdr = load("masters/C_cc.fit")        # combined + PCC broadband base
ny, nx = C.shape[:2]

Ha = A[..., 0]                                   # LP red ~ Ha (continuum-suppressed)
Ha_r, _ = reproject_interp((Ha, Awcs), Cwcs, shape_out=(ny, nx))
Ha_r = np.nan_to_num(Ha_r, nan=0.0)

# Isolate HII: threshold Ha a few sigma over its own sky + normalize to [0,1],
# so background noise is NOT boosted -- only real emission knots survive.
valid = Ha_r > 0
v = Ha_r[valid]
ha_med = np.median(v)
ha_sig = max(float(np.std(v[v < np.percentile(v, 90)])), 1e-9)   # robust noise
hii = np.clip(Ha_r - (ha_med + 3.0 * ha_sig), 0, None)
hi = np.percentile(hii[hii > 0], 99) if (hii > 0).any() else 1.0
hn = np.clip(hii / (hi + 1e-12), 0, 1)            # 0..1, HII only

cr = C[..., 0]
ref = float(np.percentile(cr, 80))                # mid-bright red reference
out = C.copy()
out[..., 0] = cr + K * ref * hn                   # add Ha only where HII is real
out = np.clip(out, 0, None)
fits.writeto("masters/C_cc_ha.fit",
             np.moveaxis(out, -1, 0).astype(np.float32), header=Chdr, overwrite=True)
print(f"WROTE masters/C_cc_ha.fit  K={K}  HII px(hn>0.05)={int((hn>0.05).sum())}  "
      f"coverage={100*valid.mean():.0f}%")
