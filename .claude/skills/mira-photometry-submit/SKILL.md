---
name: mira-photometry-submit
description: Run differential photometry on captured FITS and produce an AAVSO Extended File via `mira submit`. Use after a capture session to reduce light curves. Read the honest AAVSO-submittability caveat first.
when_to_use: run photometry, submit to AAVSO, reduce the light curve, after capturing a variable-star target
allowed-tools: [Bash, Read]
shell: powershell
---

# Mira photometry / submit

```
mira submit --captures "captures/<TARGET>/" --target "<NAME>" \
  --comp-stars docs/comp_stars/<t>.json --observer-code ABC \
  --chart-id X12345AAB
```
Reads each FITS, runs circular-aperture differential photometry vs the
comp stars, writes `aavso_<TARGET>.txt` (AAVSO Extended Format) for
manual upload at https://www.aavso.org/webobs/file.

## Honest caveat — read before "submitting"
This pipeline does **not** apply color-term / transformation
corrections. The differential light curves are real and useful for
*your own* analysis and trend-watching, but the output is **not
publication-grade AAVSO-submittable** without the transformation work,
which is not built. Do not present `aavso_<TARGET>.txt` as
submission-ready. State this plainly to the user.

## WCS prerequisite (the NINA-capture trap)
NINA API/snapshot captures save FITS with **no WCS**. Photometry needs
a celestial WCS. Recipe (offline, per frame, ~0.2 s):
```
& "C:\Program Files\astap\astap_cli.exe" -f <file> -ra <RA_hours> \
  -spd <Dec+90> -fov 0 -r 20 -z 2 -update
```
`-fov 0` (auto) is essential — a wrong fixed `-fov` fails "No solution".
`mira doctor` checks ASTAP + star DB are present. `mira submit
--siril-calibrate` is the opt-in calibrate pre-step (WCS safety gate
aborts if Siril flips the image — verify recovered mags before trusting).

## Comp stars
Pass `--comp-stars <json>` or let it auto-fetch from AAVSO VSP. Format:
`[{"label","ra_deg","dec_deg","catalog_mag","catalog_band"}, ...]`.
Sanity-check recovered magnitudes against the chart before believing the
curve.
