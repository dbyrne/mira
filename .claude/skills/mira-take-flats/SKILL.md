---
name: mira-take-flats
description: Capture per-filter master flats with the S30 Pro filter wheel via `mira flats`. User-invoked only — it drives the wheel and camera. Use when you want flat calibration frames for a filter/gain.
when_to_use: take flats, flat calibration, build a master flat, before or after a deep imaging run you want calibrated
disable-model-invocation: true
user-invocable: true
allowed-tools: [Bash, Read]
shell: powershell
---

# Mira take-flats (drives the wheel + camera — user-invoked only)

```
mira flats --gain 120 --target-adu 30000 --frames 25
mira flats --filters LP,IR --gain 120        # explicit subset
```
Tape paper over the aperture ONCE; it cycles every wheel position,
auto-brackets exposure (wide -> fine to ~target ADU), captures a
validated series per filter, builds a Siril master into
`data/flats/<filter>_g<gain>_<date>/` (gitignored). Opaque positions
(`Dark`) are auto-detected and skipped.

## Flat source — this is the failure mode that wasted a session
- A **hand-held tablet screen is NOT a valid flat source.** Proven
  2026-05-19: it works *only* if held perfectly flush and steady; you
  cannot hold it for a 25-frame series, and screen PWM/auto-brightness
  fluctuates. Non-monotonic / non-repeatable ADU = bad flat.
- Use a **hands-free, even, steady** source: paper taped flush over the
  aperture lit by an even wall / a dim screen at distance / twilight
  sky. The tool's two-shot repeatability gate will abort an unstable
  source rather than bank bad flats — trust it.
- Built-in guards (do not disable): frame freshness (the `NoState`
  stale-frame trap returned byte-identical "captures"), 0-stars (a
  frame with stars is sky, not a flat), opaque auto-skip.

## Match gain to your lights
Flats are only valid at the SAME gain as the lights. `--gain 120`
matches a gain-120 deep run. The S30 Pro is a sealed optical system, so
a master is reusable session-to-session for that filter/gain UNTIL
focus/optics change.

## Honest limits
Flats fix vignette/dust — NOT an urban light-pollution sky gradient
(that's additive sky; measured ~+28% gradient when a 4%-deep flat fought
M51's LP). Don't expect flats to rescue an LP-limited target.

After capture, `mira-deep-capture` lights shot with `--filter X` get a
`mira_capture.json` sidecar so `mira stack --auto-flats` finds the
matching master automatically.
