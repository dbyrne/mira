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
- Blind slews only (`center=False`): NINA's iterative Center loop runs
  forever on this mount. The loop already does this; don't add Center.
- It stops itself at `--alt-floor` altitude or `--sun-max` twilight.

## Site reality
- **Check the actual sky line, not just computed altitude.** At the JC
  yard the house blocked a target that had a "good" computed altitude
  (NGC7000 was behind the house). Eyeball where the scope is pointing
  before committing hours. A horizon profile in the site config is the
  durable fix.
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
