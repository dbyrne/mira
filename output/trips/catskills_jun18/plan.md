# Catskills dark-site trip — plan v2 (target night: Sat June 13, 2026)

**v2 supersedes the Jun 18 Veil-mosaic plan**: trip likely moves to **Saturday
night**, the S30 switches to the **Elephant Trunk (IC 1396)** single frame, and
the **Esprit 80 ED comes along** with a target of its own. The Veil 2-panel kit
is shelved, not deleted — see the appendix. (Folder keeps the `catskills_jun18`
name until the date is confirmed; `git mv` it then.)

**Site:** Catskills (~lat 42.1, lon −74.4). No southern-horizon dependency in
this plan — every primary sits dec +57 to +68 (N/NE, climbing) and M101 is high
NW. The v1 "confirm southern horizon" caveat only matters if you flex to M16/M17.

## Pick the night

| Night | Moon | Moon during astro dark (≈22:50→03:05) |
| --- | --- | --- |
| **Sat Jun 13→14** | **2%** | **none — sets 19:25, rises 04:25. Entire window moonless.** |
| Thu Jun 18→19 (v1 date) | 21% | thin in the W until ~23:50 |
| Sat Jun 20→21 | 42% | up until 00:30 — first ~1.5h compromised for broadband |

Jun 13 is the best dark window of the month and the whole plan below assumes
it. If the trip slips to Jun 20, the target picks still work (sky shifts only
~30 min earlier) but **start the Esprit on RGB after moonset (00:30)** and give
the moony first hours to L… or better, to nothing — set up, focus, and run the
S30's LP capture, which tolerates the moon.

## Conditions — Sat Jun 13→14 (EDT)

- **Astro dark:** 22:50 → 03:05 (~4h15m usable).
- **Moon:** 2% — below the horizon the entire window.
- Altitudes by hour:

| Target | 22:00 | 23:00 | 00:00 | 01:00 | 02:00 | 03:00 | 04:00 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IC 1396 (S30) | 27° | 34° | 41° | 49° | 57° | 65° | 71° |
| Iris NGC 7023 (Esprit 80) | 36° | 41° | 47° | 52° | 57° | 61° | 64° |
| M101 (alternate) | 77° | 71° | 63° | 54° | 45° | 37° | 29° |
| NGC 7000 (alternate) | 24° | 33° | 43° | 53° | 63° | 74° | 85° |

Both primaries **climb all night** — no setting deadline, no meridian flip
(Iris transits ~04:50, after dark ends; IC 1396 even later).

## Rig 1 — S30 Pro: IC 1396 / Elephant Trunk, single frame (LP)

The full IC 1396 shell is ~170′×140′ (2.8°×2.3°). The S30's frame is 2.196°
(E–W, short) × 3.904° (N–S, long), long axis native ≈ N–S (~4° tilt). N–S is
generous — μ Cep (the Garnet Star) on the north rim lands in-frame; E–W the
shell rim kisses both edges (2.33° vs 2.20° — the ~4′ clipped per side is
diffuse rim, fine). **Framing chart: `ic1396_framing_dss.png`.**

- **Center: RA 324.78, Dec +57.50** (shell center; Trunk sits 0.78° W of
  center, safely inside).
- μ Cep doubles as a color sanity-check after PCC — it should be strikingly red.

```powershell
# Test frame FIRST: one sub, mira solve the dir, then confirm orientation +
# that the Trunk is in-frame:
#   python output/trips/catskills_jun18/check_orientation.py <solved.fits> 324.05 57.49 IC1396A
# Dark site: try --exposure 120 on the test frame (check star roundness);
# 60s is the safe default.

# Single run, all night; last run on this rig -> park-at-end safes it at dawn
mira capture --ra 324.78 --dec 57.5 --exposure 60 --gain 80 --filter LP `
  --dest captures/ic1396_20260613 --platesolve-center --park-at-end
```

Budget: 22:50→03:05 ≈ ~3h30m–4h integration after dither/re-center overhead
(~200+ × 60s, or ~110 × 120s). LP_g80 master flat exists → `--auto-flats`
resolves it at stack time (sealed system — no on-site flats needed).

## Rig 2 — Esprit 80 ED + ASI2600MM + AM7: Iris + Ghost, LRGB

**Target: NGC 7023 (Iris) + vdB 141 (Ghost Nebula) in one frame.**
Center **RA 317.25, Dec +68.20**, camera long axis **E–W** — the 3.37°×2.25°
field catches the Iris, the Ghost 1.4° to its east, and the LDN 1170-complex
dust between them. **Framing chart: `iris_framing_dss.png`.**

Why this over another nebula: a 2%-moon dark site is the one thing JC can never
give you, and its leverage is **broadband** — reflection nebulae + brown LDN
dust are invisible from Bortle-9. Narrowband (NGC 7000 etc.) works fine from
the backyard; spending the trip on it wastes the sky. This is also the kind of
field the galaxy/emission planners never surface — it's a dust target.

**Capture (NINA Target Scheduler on the MeLE — the Esprit's normal
non-photometry path; TS dithers through PHD2 correctly):**

- Gain 100 / offset 50, **120s subs**, dither every 3, AF on filter change +
  temp drift.
- **RGB while lower, L at peak altitude:** R→G→B ~40 min each 22:50→00:50,
  then **L 00:50→03:05** (~65 × 120s ≈ 2h10m).
- Yields L ≈ 2h + 40m/channel RGB ≈ 4h total — a real single-night LRGB set at
  f/5.

**Flats — do not skip, do not refocus first:** the Wanderer 190mm panel stays
home (it can't clamp the 80's dew shield). At dawn, **before touching focus or
rotation**, tape paper over the aperture and run:

```powershell
mira flats --filters L,R,G,B --gain 100
```

Per-filter dest dirs (`captures/iris_L` …) mean each dir's sidecar keys
`--auto-flats` to the right `<filter>_g100` master at stack time.

Dew: straps on the Esprit OTA + guide scope (the S30 handles its own).

### Alternates (decide on-site)
- **M101, LRGB, early block** — 77° at dusk but sinking; if you want two
  trophies, run M101 22:50→00:30 and hand the Esprit to Iris after. Costs
  depth on both; default is all-night Iris.
- **NGC 7000 Cygnus Wall, HOO** — if broadband conditions disappoint (haze
  kills dust contrast first). Honest note: weakest use of the dark site.

## After the trip

`reduce_trip.ps1` runs both reductions: S30 solve→cull→stack→PCC→
`mira finish --preset emission`; Esprit per-filter stacks → `combine_lrgb.py`
(WCS-registers R/G/B onto the L grid) → PCC → contact sheet → preset pick →
manual L-blend per the M51 all-lum recipe. The LRGB combine is a first for
this kit — budget an evening.

## Packing deltas vs a JC night

- Esprit 80 OTA + ASI2600MM + wheel + AM7 + MeLE + PHD2 guide kit + dew straps.
- Paper/tape for Esprit flats (no panel).
- Both laptops or just homebase + MeLE (Syncthing share works over the field
  router; or sneakernet the captures after).

## Appendix — shelved v1: Veil 2-panel mosaic (S30)

Kit stays runnable if revived: `veil_framing_dss.png`, `mosaic_veil.py`,
`reduce_veil.ps1`, panels W (311.78, +31.0) / E (313.78, +31.0), ~22% overlap,
do West first. `check_orientation.py` now takes the feature to check as args
(defaults to NGC 6960 for this plan).
