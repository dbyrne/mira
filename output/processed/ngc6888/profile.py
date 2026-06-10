import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

f = "C:/mira/output/ngc6888/ngc6888_cc.fit"
hdul = fits.open(f)
data = hdul[0].data.astype(np.float32)
hdr = hdul[0].header
# Siril 3-layer FITS -> (3,H,W); normalize layout to (H,W,3)
if data.ndim == 3 and data.shape[0] == 3:
    img = np.moveaxis(data, 0, -1)
else:
    img = data
H, W = img.shape[:2]
lum = img.mean(axis=2)
chroma = img.max(axis=2) - img.min(axis=2)

w = WCS(hdr, naxis=2)
cx, cy = w.world_to_pixel_values(303.0, 38.35)
cx, cy = float(cx), float(cy)
print(f"image HxW = {H}x{W}; nebula center px = ({cx:.0f},{cy:.0f})")

yy, xx = np.mgrid[0:H, 0:W]
r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

# robust black/scale for readable lum: subtract corner-sky median
sky_patch = lum[int(H*0.04):int(H*0.14), int(W*0.04):int(W*0.14)]
sky_med = np.median(sky_patch)
sky_std = np.std(sky_patch)
print(f"corner sky: med={sky_med:.5f} std={sky_std:.5f}")
lum_sub = lum - sky_med

print(f"{'r0':>5}{'r1':>5}{'med_lum-sky':>14}{'snr':>8}{'med_chroma':>12}")
for r0 in range(0, 520, 20):
    r1 = r0 + 20
    m = (r >= r0) & (r < r1)
    if m.sum() < 10:
        continue
    ml = float(np.median(lum_sub[m]))
    mc = float(np.median(chroma[m]))
    snr = ml / (sky_std + 1e-9)
    print(f"{r0:5d}{r1:5d}{ml:14.6f}{snr:8.1f}{mc:12.6f}")
hdul.close()
