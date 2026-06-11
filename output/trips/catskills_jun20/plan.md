# Catskills dark-site trip — plan v3 (CONFIRMED: Sat June 20, 2026)

**v3 (2026-06-11): date confirmed as Saturday June 20** — a 42%-moon night
(sets 00:30), so the Esprit sequence flips to **narrowband first, broadband
after moonset** (Crescent HOO → Iris LRGB); the S30's LP plan doesn't care
about the moon and is unchanged. v2 history: the S30 switched from the Veil
2-panel to the **Elephant Trunk (IC 1396)** single frame and the **Esprit 80
ED joined the trip** (its first deployment). The Veil kit stays shelved in
the appendix.

**Site:** Catskills (~lat 42.1, lon −74.4). No southern-horizon dependency in
this plan — every primary sits dec +57 to +68 (N/NE, climbing) and M101 is high
NW. The v1 "confirm southern horizon" caveat only matters if you flex to M16/M17.

**Full candidate menu with framing charts + the JWST/Hubble showpieces:
[`trip_book/trip_book.md`](trip_book/trip_book.md)** — every chart carries both
rig footprints (cyan S30, green Esprit 80), June-20 altitude tracks, per-rig recs.

## Conditions — Sat Jun 20→21 (EDT)

- **Astro dark:** 22:55 → 03:05.
- **Moon: 42%, sets 00:30** → moonless dark = 00:30→03:05 (~2h35m). The moon
  taxes broadband for the first ~1.5h; LP/narrowband shrug it off — the whole
  sequence below is built around that split.
- Altitudes by hour:

| Target | 22:00 | 23:00 | 00:00 | 01:00 | 02:00 | 03:00 | 04:00 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IC 1396 (S30, all night) | 30° | 37° | 45° | 53° | 61° | 68° | 73° |
| Iris NGC 7023 (Esprit, post-moonset) | 38° | 44° | 49° | 55° | 59° | 63° | 64° |
| NGC 7000 (alternate) | 28° | 37° | 47° | 58° | 68° | 79° | 87° |
| M16+M17 (south window, post-moonset) | 18° | 25° | 31° | 34° | 33° | 30° | 23° |

Both primaries **climb all night** — no setting deadline, no meridian flip.
NGC 6888 (the Esprit's moon-block target) rides high in Cygnus throughout.
(The forecast that confirmed the date: Sat night mostly clear, 57°F, calm,
bracketed by thunderstorms Fri + Sun nights. Re-check before driving.)

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
#   python output/trips/catskills_jun20/check_orientation.py <solved.fits> 324.05 57.49 IC1396A
# Dark site: try --exposure 120 on the test frame (check star roundness);
# 60s is the safe default. LP doesn't care that the moon is up until 00:30.

# Single run, all night; last run on this rig -> park-at-end safes it at dawn
mira capture --ra 324.78 --dec 57.5 --exposure 60 --gain 80 --filter LP `
  --dest captures/ic1396_20260620 --platesolve-center --park-at-end
```

Budget: 22:55→03:05 ≈ ~3h30m integration after dither/re-center overhead
(~200 × 60s, or ~105 × 120s). LP_g80 master flat exists → `--auto-flats`
resolves it at stack time (sealed system — no on-site flats needed).
**Pre-trip must-do:** the capture chain's last two real runs produced 0 frames
(Jun 5 filter-confirm abort, Jun 8 empty husk) — run the indoor dry-run
(filter confirms, frames copy, sidecar written) before packing.

## Rig 2 — Esprit 80 ED + ASI2600MM + AM7: two blocks around moonset

The 42% moon until 00:30 splits the Esprit's night cleanly:

### Block 1 — moon up (22:55→00:30): NGC 6888 Crescent, HOO (narrowband)

3nm Ha/OIII punch through moonlight. Center **RA 303.0, Dec +38.35**, PA ~060;
~45 min **Ha** + ~45 min **OIII** (120s subs). The goal is the faint **OIII
envelope** around the crescent — the dark-site prize the JC data lacks; this
stacks with the existing JC LP sessions at processing time. High in Cygnus the
whole block; also doubles as the 80's guided-imaging shakedown before the
broadband main event.

### Block 2 — moonless (00:30→03:05): Iris + Ghost, LRGB (the main event)

**Target: NGC 7023 (Iris) + vdB 141 (Ghost Nebula) in one frame.**
Center **RA 317.25, Dec +68.20**, camera long axis **E–W** — the 3.37°×2.25°
field catches the Iris, the Ghost 1.4° to its east, and the LDN 1170-complex
dust between them. **Framing chart: `iris_framing_dss.png`.**

Why this is still the main event: dark-site leverage is **broadband** —
reflection nebulae + brown LDN dust are invisible from Bortle-9 and ruined by
moonlight, which is exactly why it waits for moonset. Compressed but real:
**RGB ~15 min each (00:30→01:20), then L 01:20→03:05 (~50 × 120s ≈ 1h40m).**
A second visit on a moonless night can deepen it later; tonight establishes
the field.

**Capture (NINA Target Scheduler on the MeLE — the Esprit's normal
non-photometry path; TS dithers through PHD2 correctly):**

- Gain 100 / offset 50, **120s subs**, dither every 3, AF on filter change +
  temp drift. Two TS targets: Crescent (Ha, OIII) with an end-by ~00:30, then
  Iris (R, G, B, L).

**Flats — do not skip, do not refocus first:** the Wanderer 190mm panel stays
home (it can't clamp the 80's dew shield). At dawn, **before touching focus or
rotation**, tape paper over the aperture and run (note Ha + OIII now too):

```powershell
mira flats --filters L,R,G,B,Ha,OIII --gain 100
```

Per-filter dest dirs (`captures/iris_L` …) mean each dir's sidecar keys
`--auto-flats` to the right `<filter>_g100` master at stack time.

Dew: straps on the Esprit OTA + guide scope (the S30 handles its own).

### Alternates (decide on-site)
- **NGC 7000 Cygnus Wall, HOO** — swap for the Crescent in Block 1 if you'd
  rather a fresh target than deepening the JC Crescent data.
- **M16+M17 on the S30?** No — IC 1396 owns the S30 all night. But if the
  southern horizon is clean, the pair peaks ~34° right as the moon sets
  (00:30–02:00); stealing 1h from IC 1396 for the one-frame pair (trip book
  headliner row) is a defensible audible.
- **M101 LRGB** is OFF this date: it sinks while the moon is still up —
  moonlit broadband on a low-SB face-on is a write-off. Next trip.

## After the trip

`reduce_trip.ps1` runs the reductions: S30 IC 1396 solve→cull→stack→PCC→
`mira finish --preset emission`; Esprit Iris per-filter stacks →
`combine_lrgb.py` (WCS-registers R/G/B onto the L grid) → PCC → contact sheet
→ preset pick → manual L-blend per the M51 all-lum recipe; Crescent Ha/OIII
stacks are produced per-filter for the combine-with-JC-data processing
session (the OIII-envelope project). The LRGB combine is a first for this
kit — budget an evening. Then: regenerate `mira inventory`, and the
PixInsight 45-day trial window opens with this data as the A/B set
(`plans/pixinsight_evaluation.md`).

## Field network (no site WiFi)

The MeLE↔laptop link needs a LAN, not the internet — bring the LAN:

- **Plan A — travel router** (USB-powered, no internet behind it): laptop +
  MeLE + **Seestar** all join one field SSID → RDP, NINA API `:1888`,
  Syncthing live-stack mirror, and the S30 connection all work exactly as at
  home. Reserve the MeLE's IP so RDP / `--nina-url` never drift.
- **Plan B — zero hardware**: Ethernet cable laptop↔MeLE (static IPs
  192.168.50.1/.2), laptop WiFi joins the Seestar's own AP for the S30.
- **The trap:** Windows marks unknown networks **Public** → firewall silently
  kills RDP/Syncthing/NINA API. Set the field network to *Private* on both
  machines. **Build + test the exact field network at home before leaving.**
- No internet costs nothing critical: ASTAP solves offline (local indexes),
  Syncthing uses local discovery, PCC is already deferred to home in
  `reduce_trip.ps1`. Sync both clocks before departure.

## Packing deltas vs a JC night

- Esprit 80 OTA + ASI2600MM + wheel + AM7 + MeLE + PHD2 guide kit + dew straps.
- Paper/tape for Esprit flats (no panel).
- **Travel router (+ USB power lead) or Ethernet cable + laptop dongle** — see
  Field network above. Pre-tested at home.
- Both laptops or just homebase + MeLE (Syncthing share works over the field
  LAN; or sneakernet the captures after).

## Appendix — shelved v1: Veil 2-panel mosaic (S30)

Kit stays runnable if revived: `veil_framing_dss.png`, `mosaic_veil.py`,
`reduce_veil.ps1`, panels W (311.78, +31.0) / E (313.78, +31.0), ~22% overlap,
do West first. `check_orientation.py` now takes the feature to check as args
(defaults to NGC 6960 for this plan).
