#!/usr/bin/env python
"""Schematic of the proposed rooftop-pier nook: plan view (footprint + closet
door clearance + ladder landing) and section (ceiling slope + mount height +
maintenance ladder reach). Roughly to scale from the measured nook
4ft3in x 3ft5in. Units = inches.
"""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, Arc, FancyArrow, Polygon

W, D = 51, 41          # nook width x depth (in)
CEIL = 96              # flat ceiling height (8 ft)
PIER_X, PIER_Y = 18, 20.5
PIER_R = 8             # 16in baseplate
MOUNT_Z = 84           # mount head ~7 ft

fig, (axp, axs) = plt.subplots(1, 2, figsize=(15, 7.2))

# ---------------------------------------------------------------- PLAN VIEW
ax = axp
ax.add_patch(Rectangle((0, 0), W, D, fill=False, lw=2))
ax.set_title("PLAN VIEW (looking down)", fontsize=12, weight="bold")

# left wall = dormer/window wall, roof slopes up above it
ax.add_patch(Rectangle((0, 0), 8, D, color="0.85"))
ax.text(4, D/2, "dormer /\nwindow wall\n(roof slope\nabove)", rotation=90,
        ha="center", va="center", fontsize=8, color="0.3")

# right wall = closet w/ double doors + swing arcs (KEEP CLEAR)
cl_lo, cl_hi = 4, 36                     # closet opening span in y
ax.plot([W, W], [cl_lo, cl_hi], color="saddlebrown", lw=5, solid_capstyle="butt")
for hy in (cl_lo, cl_hi):
    sgn = 1 if hy == cl_lo else -1
    ax.add_patch(Arc((W, hy), 32, 32, angle=0,
                     theta1=(90 if sgn > 0 else 180),
                     theta2=(180 if sgn > 0 else 270),
                     color="saddlebrown", ls="--", lw=1.2))
ax.add_patch(Rectangle((W-16, cl_lo), 16, cl_hi-cl_lo, color="saddlebrown", alpha=0.10))
ax.text(W-8, D-3.5, "closet door swing\n(cannot block)", ha="center", va="top",
        fontsize=8, color="saddlebrown")

# pier baseplate + mount
ax.add_patch(Circle((PIER_X, PIER_Y), PIER_R, color="0.4"))
ax.add_patch(Rectangle((PIER_X-5, PIER_Y-5), 10, 10, color="navy"))
ax.text(PIER_X, PIER_Y-PIER_R-2, "fixed steel pier\n(~16in baseplate)",
        ha="center", va="top", fontsize=8, color="navy")

# roof hatch above (dashed)
ax.add_patch(Rectangle((PIER_X-11, PIER_Y-11), 22, 22, fill=False, ls=":",
                       ec="seagreen", lw=1.6))
ax.text(PIER_X, PIER_Y+12.5, "roof hatch above", ha="center", fontsize=8,
        color="seagreen")

# ladder deployed footprint
ax.add_patch(Rectangle((26, 12), 12, 16, fill=False, ls="--", ec="darkorange", lw=1.6))
ax.text(32, 30, "ladder deployed\nfor maintenance\n(stows in closet)",
        ha="center", va="bottom", fontsize=8, color="darkorange")

# clearance callout pier->door
ax.annotate("", xy=(W-16, 20.5), xytext=(PIER_X+PIER_R, 20.5),
            arrowprops=dict(arrowstyle="<->", color="red"))
ax.text((PIER_X+PIER_R+W-16)/2, 18.5, "~9in", ha="center", color="red", fontsize=8)

# dimensions
ax.annotate("", xy=(0, -4), xytext=(W, -4), arrowprops=dict(arrowstyle="<->"))
ax.text(W/2, -7, '4 ft 3 in (51")', ha="center", fontsize=9)
ax.annotate("", xy=(-4, 0), xytext=(-4, D), arrowprops=dict(arrowstyle="<->"))
ax.text(-7, D/2, '3 ft 5 in (41")', va="center", rotation=90, fontsize=9)
ax.text(W/2, D+2, "bed / entry side", ha="center", fontsize=8, color="0.5")

ax.set_xlim(-12, W+4); ax.set_ylim(-10, D+5)
ax.set_aspect("equal"); ax.axis("off")

# ---------------------------------------------------------------- SECTION
ax = axs
ax.set_title("SECTION (maintenance reach)", fontsize=12, weight="bold")
# floor + walls
ax.plot([0, W], [0, 0], color="0.2", lw=2)
ax.plot([W, W], [0, CEIL], color="0.2", lw=2)
# ceiling: flat from right down to x=14, then slope to window knee at left
ax.plot([W, 14], [CEIL, CEIL], color="0.2", lw=2)
ax.plot([14, 0], [CEIL, 50], color="0.2", lw=2)          # interior slope
ax.plot([0, 0], [0, 50], color="0.2", lw=2)
# window in the slope wall
ax.add_patch(Rectangle((0.5, 18), 3, 26, fill=False, ec="0.4"))
ax.text(6, 32, "window", fontsize=8, color="0.4")
# roof exterior (above ceiling) + hatch
ax.plot([W, 14], [CEIL+12, CEIL+12], color="0.5", lw=1.5)
ax.plot([14, 0], [CEIL+12, 62], color="0.5", lw=1.5)
ax.text(W-2, CEIL+14, "roof exterior", ha="right", fontsize=8, color="0.5")
# hatch opening over pier
ax.add_patch(Rectangle((PIER_X-12, CEIL), 24, 12, color="skyblue", alpha=0.5))
ax.plot([PIER_X-12, PIER_X-12], [CEIL, CEIL+12], color="seagreen", lw=1.5)
ax.plot([PIER_X+12, PIER_X+12], [CEIL, CEIL+12], color="seagreen", lw=1.5)
ax.text(PIER_X, CEIL+16, "hatch OPEN (sky)", ha="center", fontsize=8, color="seagreen")
ax.plot([PIER_X-12, PIER_X+12], [CEIL+12, CEIL+12], color="seagreen", ls="--", lw=2)
ax.text(PIER_X+13, CEIL+9, "lid closed\n+ sealed when idle", fontsize=7, color="seagreen", va="center")

# pier + mount + OTA poking through hatch
ax.add_patch(Rectangle((PIER_X-3, 0), 6, MOUNT_Z, color="0.4"))      # column
ax.add_patch(Rectangle((PIER_X-6, MOUNT_Z), 12, 8, color="navy"))    # mount head
ax.add_patch(Rectangle((PIER_X-3, MOUNT_Z+8), 6, 22, color="dimgray"))  # OTA up thru hatch
ax.text(PIER_X-8, MOUNT_Z+4, "mount\nhead", ha="right", fontsize=8, color="navy")

# mount-head height callout
ax.annotate("", xy=(43, 0), xytext=(43, MOUNT_Z), arrowprops=dict(arrowstyle="<->", color="navy"))
ax.text(44.5, MOUNT_Z/2, "~7 ft\nmount head", color="navy", fontsize=8, va="center")
ax.annotate("", xy=(48, 0), xytext=(48, CEIL), arrowprops=dict(arrowstyle="<->", color="0.4"))
ax.text(49.2, CEIL/2, "8 ft\nceiling", color="0.4", fontsize=8, va="center")

# ladder + person reaching
lx = 30
for i, z in enumerate([0, 12, 24]):                  # 3 steps
    ax.plot([lx, lx+9], [z, z], color="darkorange", lw=2)
ax.plot([lx, lx], [0, 30], color="darkorange", lw=2)
ax.plot([lx+9, lx+9], [0, 30], color="darkorange", lw=2)
ax.text(lx+4.5, -5, "3-step ladder", ha="center", color="darkorange", fontsize=8)
# stick person on top step reaching toward mount
px, pz = lx+3, 24
ax.add_patch(Circle((px, pz+30), 3, color="black"))           # head
ax.plot([px, px], [pz, pz+27], color="black", lw=2)           # torso
ax.plot([px, PIER_X+4], [pz+24, MOUNT_Z], color="black", lw=2)  # arm to mount
ax.plot([px, px-6], [pz+18, pz+10], color="black", lw=2)      # other arm
ax.plot([px, px-3], [pz, pz-8], color="black", lw=2)          # legs (on step)
ax.plot([px, px+3], [pz, pz-8], color="black", lw=2)
ax.annotate("reach mount flat-footed\nfrom the top step", xy=(PIER_X+4, MOUNT_Z),
            xytext=(lx+12, MOUNT_Z+6), fontsize=8,
            arrowprops=dict(arrowstyle="->"))

ax.set_xlim(-4, W+10); ax.set_ylim(-10, CEIL+26)
ax.set_aspect("equal"); ax.axis("off")

fig.suptitle("Rooftop pier nook — layout & maintenance access (rough scale; slim fixed pier, not the tripod)",
             fontsize=13, weight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.96])
out = Path("output/rooftop_eval/room_layout.png")
fig.savefig(out, dpi=130, bbox_inches="tight")
print("wrote", out)
