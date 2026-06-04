#!/usr/bin/env python
"""Generate the v8 accessory-topology diagram for astrophotography_rig_plan_v8.md.

Two panels: a side elevation and a top (plan) view of the 355mm D-plate.
Run: python docs/diagrams/rig_v8_layout.py  -> docs/astrophotography_rig_v8_layout.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrow

# palette
C_OTA = "#3b4252"      # tube
C_RAIL = "#2e7d32"     # D-plate (green, matches FOV overlay)
C_BOTTOM = "#5d4037"   # stock losmandy bar
C_GUIDE = "#1565c0"    # guide scope
C_MELE = "#6a1b9a"     # mini PC
C_PBOX = "#ef6c00"     # powerbox
C_COVER = "#b71c1c"    # wandercover
C_TXT = "#1a1a1a"


def rrect(ax, x, y, w, h, color, label=None, tcolor="white", fs=11, lw=0):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                       linewidth=lw, edgecolor="black", facecolor=color, zorder=3)
    ax.add_patch(p)
    if label:
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                color=tcolor, fontsize=fs, fontweight="bold", zorder=6)
    return p


fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9.5),
                               gridspec_kw={"height_ratios": [1.45, 1]})
fig.suptitle("Esprit 120EDX — v8 Accessory Topology  (355 mm Universal D-Plate)",
             fontsize=16, fontweight="bold", y=0.985)

# ============================ SIDE VIEW ============================
ax1.set_title("Side elevation  (objective ◄ left,  camera ► right)",
              fontsize=12, loc="left", pad=8)
ax1.set_xlim(0, 14)
ax1.set_ylim(0, 6.2)
ax1.axis("off")

# OTA tube
rrect(ax1, 2.3, 1.7, 8.4, 1.2, C_OTA, "Sky-Watcher Esprit 120EDX OTA", fs=12)
# dew shield + WandererCover (front, left)
rrect(ax1, 1.55, 1.62, 0.75, 1.36, "#4a5568")  # dew shield
rrect(ax1, 1.15, 1.55, 0.5, 1.5, C_COVER)
ax1.annotate("WandererCover\n(front dew shield — OFF rail)", xy=(1.4, 1.5),
             xytext=(0.6, 0.45), fontsize=9.5, color=C_COVER, fontweight="bold",
             ha="center", arrowprops=dict(arrowstyle="->", color=C_COVER, lw=1.5))
# imaging train (focuser+EFW+camera) at right
rrect(ax1, 10.7, 1.85, 1.9, 0.9, "#263238", "focuser·EFW·2600", fs=9)

# tube rings
for rx in (4.7, 8.3):
    ax1.add_patch(Rectangle((rx, 1.55), 0.34, 1.5, facecolor="#9e9e9e",
                            edgecolor="black", zorder=4))

# stock Losmandy bar (bottom) -> saddle
rrect(ax1, 3.8, 1.0, 5.4, 0.42, C_BOTTOM, "stock Losmandy bar", fs=9.5)
ax1.add_patch(FancyArrow(6.5, 1.0, 0, -0.55, width=0.04, head_width=0.22,
                         head_length=0.18, color="black", length_includes_head=True))
ax1.text(6.5, 0.18, "into AM7 saddle", ha="center", fontsize=9.5, fontweight="bold")

# 355mm D-plate (top rail) — overhangs rings fore & aft
rrect(ax1, 3.2, 3.25, 7.7, 0.4, C_RAIL, "355 mm Universal D-Plate  (top accessory rail)",
      fs=10.5)

# components on the rail
rrect(ax1, 3.35, 3.7, 1.5, 0.7, C_GUIDE, "guide\nscope", fs=9.5)
rrect(ax1, 4.85, 3.95, 0.32, 0.4, "#0d47a1")  # guide cam on tail
ax1.text(5.0, 4.55, "+cam", ha="center", fontsize=8, color=C_GUIDE, fontweight="bold")
rrect(ax1, 5.8, 3.7, 1.7, 0.9, C_MELE, "MeLE\nmini PC", fs=10)
rrect(ax1, 8.6, 3.7, 1.9, 0.8, C_PBOX, "Pegasus\nPowerbox", fs=9.5)

# fore/aft labels
ax1.text(4.1, 5.35, "FORWARD", ha="center", fontsize=9, color="#555")
ax1.text(9.55, 5.35, "AFT", ha="center", fontsize=9, color="#555")
for x0, x1, y in [(3.35, 4.85, 5.15)]:
    pass

# ============================ TOP (PLAN) VIEW ============================
ax2.set_title("Top (plan) view of the 355 mm D-Plate  —  fore → aft",
              fontsize=12, loc="left", pad=8)
ax2.set_xlim(0, 14)
ax2.set_ylim(0, 4)
ax2.axis("off")

# the rail
rrect(ax2, 1.0, 1.2, 12.0, 1.4, C_RAIL, lw=1)
# components
rrect(ax2, 1.4, 1.45, 2.6, 0.9, C_GUIDE, "guide scope  (+cam)", fs=10.5)
rrect(ax2, 5.4, 1.4, 2.7, 1.0, C_MELE, "MeLE mini PC", fs=11)
rrect(ax2, 9.6, 1.45, 3.0, 0.9, C_PBOX, "Pegasus Powerbox", fs=10.5)

# dimension line
ax2.annotate("", xy=(1.0, 3.05), xytext=(13.0, 3.05),
             arrowprops=dict(arrowstyle="<->", color="black", lw=1.4))
ax2.text(7.0, 3.2, "355 mm  (~14 in)", ha="center", fontsize=11, fontweight="bold")
ax2.text(0.6, 0.55, "FRONT (objective)", ha="left", fontsize=10, color="#333", fontweight="bold")
ax2.text(13.4, 0.55, "REAR (camera)", ha="right", fontsize=10, color="#333", fontweight="bold")
ax2.text(7.0, 0.55, "◄ slide any item to trim balance / clear the flip ►",
         ha="center", fontsize=9.5, color="#777", style="italic")

# off-rail note
fig.text(0.5, 0.012,
         "Off the rail:  WandererCover → front dew shield   ·   guide camera → tail of guide scope",
         ha="center", fontsize=10, color="#444", style="italic")

plt.tight_layout(rect=[0, 0.03, 1, 0.96])
out = "docs/astrophotography_rig_v8_layout.png"
plt.savefig(out, dpi=130, facecolor="white")
print("wrote", out)
