---
name: mira-deep-capture
description: Run a dithered, filter-confirmed deep-capture loop on one target via `mira capture`. User-invoked only — it slews the mount and captures for hours. Use for deep single-target imaging beyond the nightly queue.
when_to_use: deep capture, image a target for hours, dithered capture loop, a single-target deep run
disable-model-invocation: true
user-invocable: true
allowed-tools: [Bash, Read]
shell: powershell
---

# Mira deep-capture (slews + captures for hours — user-invoked only)

```
mira capture --ra <J2000_deg> --dec <J2000_deg> --exposure 45 --gain 120 \
  --filter LP --dest captures/<target>_<date> \
  --dither-arcsec 30 --dither-every 1 --alt-floor 30 --sun-max -15
```

## Non-negotiables (each is a hard-won bug)
- **RA/Dec are J2000 DEGREES.** NINA mount/info reports RA in *hours* —
  that asymmetry is the classic trap. Convert hours->deg (x15) before
  passing `--ra`.
- **`--filter` selects AND confirms the wheel before any slew/capture.**
  If it can't confirm, the run aborts before shooting — it will never
  burn a multi-hour stack through the wrong/no filter. Match the filter
  to your flats.
- **Dithering is the point.** Un-dithered + multi-hour drift produced an
  unrecoverable walking-noise streak on M94 (six post-fixes all failed).
  The loop dithers relative to FIXED nominal coords (breaks walking
  noise AND re-centers; drift can't accumulate). Keep dithering on.
- **Blind slews + app-align for now (`--no-platesolve-center`).** NINA's
  iterative Center has been hanging on this mount (300s timeouts), so the
  current workaround is: reposition in the Seestar app, then capture one
  frame and ASTAP-solve it to confirm pointing. BUT this is very likely a
  NINA plate-solve *config* issue, not the mount (Seestar reports
  FocalLength=NaN → NINA can't compute plate scale; also confirm ASTAP is
  selected as NINA's plate solver with a star DB). If Center is fixed it's
  preferable to the manual dance — treat `--no-platesolve-center` as a
  workaround, not a law.
- **`--park-at-end` (default on) safes the rig at dawn:** parks the mount
  (stops tracking) + rotates the wheel to the opaque 'Dark' position to
  shield the sensor — fires on normal stop AND crash/Ctrl-C.
  `--no-park-at-end` leaves it tracking (e.g. to hand off to another target).
- It stops itself at `--alt-floor` altitude or `--sun-max` twilight.

## Site reality — the horizon profile exists; compute it, don't hedge
- **`config/horizon_balcony_jc.yaml`** is a real az/alt silhouette of the JC
  balcony (house, trees, rail), captured from Stellarium AR. Load it with
  `mira.horizon.load_horizon_profile` → `min_altitude_at(az)`, compute the
  target's (az, alt) track over the night, and you get DETERMINISTICALLY when
  it clears the obstruction. Don't say "if the house blocks it" — work it out.
  (Worked example: M27 rises through the clean **E** window and clears at alt
  ~24° / 23:15; the blocked zone is the **NE**, az 30-60° at +40-45°, which it
  never crosses.) The old "just eyeball the sky line" advice is superseded.
- Capture drive: a deep run is ~19 GB. `mira doctor` checks free space.

## Closes the calibration loop
`--filter X` writes a `mira_capture.json` sidecar next to the subs
(NINA's FITS carry no FILTER keyword — verified). Then:
```
mira stack --lights captures/<dir> --out output/<t>.tif --auto-flats
```
resolves the matching `data/flats/X_g<gain>_*` master and applies it via
Siril `calibrate -flat=` — or HARD-ABORTS if none matches (it won't
silently stack uncalibrated). `--flats <dir>` overrides manually.

## Exposure length + dither cadence — set them INDEPENDENTLY
- **Sub length: be sky-limited, then stop.** A sub only needs to be long
  enough that sky shot-noise swamps read noise; past that, longer subs add
  ZERO SNR/hour — depth is set by TOTAL integration, not sub length. Longer
  only adds downside: clipped highlights, fewer frames to reject the moon
  gradient + satellites, more trailing per frame.
- **Bright moon → sky-limited in seconds → SHORT subs (~15-20s at f/5).**
  Long subs (60s+) only pay off under genuinely dark skies (read-noise-limited).
- **Dither overhead is a CADENCE problem, not an exposure one.** Do NOT
  lengthen subs to amortize the dither slew — that's backwards. Keep subs
  short and use `--dither-every 2` (or 3): cuts slew/settle overhead ~½-⅔
  while still killing walking noise (the M94 disaster was ZERO dither, not
  "every-3"; hundreds of subs at many offsets decorrelate fine). The only
  *fixed* per-frame cost (readout + save, a few sec) is what argues against
  absurdly short subs — not the dither.
- Sanity-check the first sub's histogram: sky background < ~⅓ full scale,
  bright target not clipping. Drop the sub length if it runs hot.

## Target choice under a bright moon
Broadband, low-surface-brightness targets (galaxies, reflection nebulae)
drown: a full moon is ≈ 6-10× brighter sky ≈ 2.5-3× worse per-sub SNR on
faint structure, so moony integration is largely wasted on them — and it gets
down-weighted in the stack anyway. Pick EMISSION targets: planetaries
(M27/M57/M97) and Hα/OIII nebulae punch through with the LP filter; globular
clusters (M13/M92) are essentially moon-immune (resolved point sources, like
transients). Save galaxies for a dark night — that's when extra integration
actually deepens them.
