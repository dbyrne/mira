#!/usr/bin/env python
"""Framing charts for the Catskills trip (v2 plan): DSS2 color via hips2fits,
with the rig FOV box + feature labels drawn on.

  1. ic1396_framing_dss.png — IC 1396 on the S30 Pro (2.196 deg E-W x 3.904 deg
     N-S, long axis ~N-S with the native ~4 deg tilt).
  2. iris_framing_dss.png — Iris + Ghost on the Esprit 80 ED / ASI2600MM
     (3.365 deg x 2.249 deg @ 1.94"/px), long axis rotated E-W.

Run:  python output/trips/catskills_jun20/make_framing.py   (needs internet)
"""
import math
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

HERE = Path(__file__).parent
HIPS = "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"

YEL = (255, 210, 0)
CYA = (0, 220, 255)
WHT = (255, 255, 255)


def font(sz, bold=True):
    try:
        return ImageFont.truetype(
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf", sz)
    except OSError:
        return ImageFont.load_default()


def fetch(ra, dec, fov_deg, px=1400):
    r = requests.get(HIPS, params={
        "hips": "CDS/P/DSS2/color", "width": px, "height": px,
        "fov": fov_deg, "projection": "TAN", "coordsys": "icrs",
        "ra": ra, "dec": dec, "format": "png",
    }, timeout=180)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


def projector(ra0, dec0, fov_deg, px):
    """world (ra, dec) -> chart pixel, gnomonic, north up / east LEFT."""
    scale = px / math.radians(fov_deg)  # px per radian on the tangent plane
    a0, d0 = math.radians(ra0), math.radians(dec0)

    def to_px(ra, dec):
        a, d = math.radians(ra), math.radians(dec)
        cosc = math.sin(d0) * math.sin(d) + math.cos(d0) * math.cos(d) * math.cos(a - a0)
        xi = math.cos(d) * math.sin(a - a0) / cosc            # east +
        eta = (math.cos(d0) * math.sin(d)
               - math.sin(d0) * math.cos(d) * math.cos(a - a0)) / cosc  # north +
        return px / 2 - xi * scale, px / 2 - eta * scale

    def offset_px(de_deg, dn_deg):
        """tangent-plane offset (deg E, deg N) from center -> pixel."""
        return (px / 2 - math.radians(de_deg) * scale,
                px / 2 - math.radians(dn_deg) * scale)

    return to_px, offset_px


def fov_box(d, offset_px, w_ew, h_ns, rot_deg, color, label):
    """Camera footprint centered on the chart center. w_ew/h_ns in deg;
    rot rotates the footprint on the sky (0 = sides along E-W / N-S)."""
    th = math.radians(rot_deg)
    pts = []
    for se, sn in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        e, n = se * w_ew / 2, sn * h_ns / 2
        er = e * math.cos(th) - n * math.sin(th)
        nr = e * math.sin(th) + n * math.cos(th)
        pts.append(offset_px(er, nr))
    d.polygon(pts, outline=color, width=5)
    d.text((min(p[0] for p in pts) + 10, min(p[1] for p in pts) + 8),
           label, fill=color, font=font(34))


def mark(d, to_px, ra, dec, name, color=YEL, dy=-46, r=14):
    x, y = to_px(ra, dec)
    d.ellipse([x - r, y - r, x + r, y + r], outline=color, width=4)
    d.text((x + r + 6, y + dy), name, fill=color, font=font(32))


def compass_scale(d, px, fov_deg):
    x0, y0 = px - 90, px - 110
    d.line([x0, y0, x0, y0 - 70], fill=WHT, width=4)
    d.text((x0 - 12, y0 - 110), "N", fill=WHT, font=font(30))
    d.line([x0, y0, x0 - 70, y0], fill=WHT, width=4)
    d.text((x0 - 105, y0 - 16), "E", fill=WHT, font=font(30))
    bar = px / fov_deg  # 1 deg
    d.line([40, px - 50, 40 + bar, px - 50], fill=WHT, width=5)
    d.text((40, px - 92), "1°", fill=WHT, font=font(30))


def chart(out, ra0, dec0, fov, title, boxes, marks):
    px = 1400
    im = fetch(ra0, dec0, fov, px)
    d = ImageDraw.Draw(im)
    to_px, offset_px = projector(ra0, dec0, fov, px)
    for w_ew, h_ns, rot, color, label in boxes:
        fov_box(d, offset_px, w_ew, h_ns, rot, color, label)
    for ra, dec, name, color in marks:
        mark(d, to_px, ra, dec, name, color)
    d.text((24, 18), title, fill=WHT, font=font(40))
    compass_scale(d, px, fov)
    im.save(HERE / out)
    print("wrote", HERE / out)


if __name__ == "__main__":
    # --- S30 Pro on IC 1396 (single frame; long axis N-S, native ~4 deg tilt)
    chart(
        "ic1396_framing_dss.png", 324.78, 57.5, 5.6,
        "IC 1396 — S30 Pro single frame  (center 324.78, +57.50)",
        boxes=[(2.196, 3.904, 4.0, YEL, "S30 2.20°×3.90° (~4° tilt)")],
        marks=[
            (324.05, 57.49, "IC 1396A Elephant Trunk", CYA),
            (325.877, 58.780, "μ Cep (Garnet Star)", CYA),
        ],
    )
    # --- Esprit 80 ED on Iris + Ghost (long axis rotated E-W)
    chart(
        "iris_framing_dss.png", 317.25, 68.20, 5.0,
        "NGC 7023 Iris + vdB 141 Ghost — Esprit 80 ED  (center 317.25, +68.20)",
        boxes=[(3.365, 2.249, 0.0, YEL, "Esprit 80 3.37°×2.25° (long axis E-W)")],
        marks=[
            (315.40, 68.163, "NGC 7023 Iris", CYA),
            (319.11, 68.265, "vdB 141 Ghost", CYA),
        ],
    )
