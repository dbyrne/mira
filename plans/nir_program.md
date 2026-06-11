# Near-infrared imaging program — decision record

*Written 2026-06-11. Status: **deferred — down-the-road consideration** (David).
Nothing purchased; nothing changes on the rigs until this reopens.*

## The decision (made now, executed later)

When the NIR program happens, it will be a **dedicated NIR instrument, not
guest filters in the shared EFW**. Swapping 36mm filters in and out of the
7-slot wheel means opening it, handling bare glass, and invalidating flats —
surgery on the most-calibrated assembly we own (flats discipline, parfocal
offsets, the 55.6mm shimmed back-focus). A self-contained NIR train never
touches it, and it extends the fleet's existing design language: move
pre-assembled trains (the 80⇄120 swap model), never filters. The NIR train
lives on whichever Esprit is benched; "NIR night" = the established 10-minute
tube swap.

**Front-runner hardware: QHY miniCAM8M** (~$636 body / ~$819 with LRGB+SHO
filter combo, 2026-06 prices) — cooled mono IMX585 with a **built-in
8-position wheel** = the dedicated-camera-plus-dedicated-wheel architecture in
one body, and the same camera Nico Carver's urban NIR work runs on.

- FOV on our glass: Esprit 80 → 1.6°×0.9° @ 1.5″/px (proper nebula field);
  Esprit 120 → 0.76°×0.43° @ 0.71″/px (feature scale).
- IMX585 is the NIR enabler: ~40% QE still on tap near 889nm; the 2600MM's
  IMX571 is adequate for Sloan i′ (~⅔ the haul) but collapses in z′.

## Why NIR nebula imaging works from Bortle 8–9 (the Carver result)

Scattered light falls as λ⁻⁴ → the urban/moonlit sky goes nearly black in
NIR while nebulae still emit: the crowded high-Paschen lines + Paschen
continuum jump near the 820nm series limit, [Ar III] 713.6, [O II] 732.0/733.0,
He I — plus dust penetration (embedded stars/YSOs) and steadier seeing.
Sloan i′ = 695–844nm; z′ = ~820–920nm (where the 585 earns its keep).
Bonus: NIR blocks are **moon-immune** — another bright-moon scheduling tool.

## Pre-purchase gates (in order)

1. **Not before the Catskills trip** (2026-06-20) — nothing touches the rigs.
2. **Filter-format check (the lock-in risk):** the miniCAM8's wheel takes
   proprietary **19×12mm rectangular** filters — standard 36mm/1.25" glass
   does not fit. Verify Sloan i′/z′ (or at minimum IR-pass + NIR line
   filters) exist in that format. Ecosystem is young but forming (an
   [Ar III] 713.6 filter for the miniCAM8 already exists). **If Sloan isn't
   available in-format, the AAVSO SI-band synergy dies** and the program is
   line/IR-pass imaging only — still valid, lesser.
3. Storage Phase 1 in service (another ~3–5 GB/night data source).

## The cheap fallback if appetite is unproven

One **36mm Baader SLOAN/SDSS i′ (~$150)** guest-slotted into the 2600's wheel
for a single urban emission-target test (IMX571 is fine for i′), accepting
one round of wheel surgery + re-flats + a stored per-filter focus offset.
Judged against the same target's Ha channel. This validates the appetite for
~$150; the miniCAM8M validates nothing but removes all friction.

## Adjacent decisions already made (don't relitigate)

- **L stays resident in the main wheel** — NIR doesn't replace luminance:
  emission targets use Ha as luminance, and L is the backbone of the
  broadband mission (Iris LRGB, galaxy work, all-lum blend recipes).
- Back-focus (+0.5mm filter shim) and 3nm bandpass-shift envelopes are
  recorded in `docs/rigs.md` — both Esprits are inside spec; NIR filters on
  the *main* train would re-raise the substrate-thickness question (Baader
  2mm vs Antlia 1.85mm), which is one more argument for the dedicated train.
- Refractor caveat: the Esprits are visible-corrected — expect a real focus
  offset and mildly softer NIR stars (autofocus handles; check corners).

## When this reopens

- Re-verify miniCAM8M price/format availability and whether a successor
  exists; re-check IMX585-mono alternatives (uncooled Player One-class +
  1.25" manual wheel ≈ cheaper but no set-point darks).
- `mira submit` band mapping needs a Sloan-i → **SI** AAVSO band entry if
  the photometric synergy materializes (small `photometry.py` touch).
- First-light experiment design: same target in i′ vs Ha from JC, judge by
  eye + the curve-shootout adversarial habit.
