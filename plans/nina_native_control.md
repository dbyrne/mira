# NINA-native rig control for Mira (drive focus + center from Mira)

**Status:** plan / design. Created 2026-05-30 (S30 Pro, Jersey City balcony).

**Goal:** drive the full capture chain — **focus → center → dithered capture →
park** — from `mira capture`, with NINA as the equipment layer and **zero
dependence on the Seestar app**. The app is the root of our recurring friction:
opening it to align or focus **grabs the mount and drops NINA's connection**,
which we then have to recover.

## Why this matters
The 2026-05-29/30 M57 prep exposed the pattern: we lean on the Seestar app to
fix pointing (because NINA's "Center" hung), but the app then drops NINA's
mount link. Eliminating the app means Mira (via NINA) owns the whole session,
unattended, start to dawn.

We already have, in `mira capture`: blind slew, filter select+confirm, anchored
dither, alt/sun guards, and `--park-at-end` (parks + shields the sensor at
dawn). **The two gaps are CENTER and FOCUS** — and they're exactly the two
things we're testing tonight.

## Diagnosis (2026-05-29/30)
- **Center hang ≈ NINA plate-solve starvation.** NINA's Center uses a **2s**
  plate-solve exposure. On the 30 mm aperture, under a full moon, through LP, a
  2 s frame holds too few stars for ASTAP → every Center iteration fails to
  solve → loops to a 300 s timeout. Our own solves use the full 30 s subs
  (~800 stars) and succeed in ~1 s. Star detectability ~ √(exposure), so 2 s ≈
  ¼ the per-star SNR of a 30 s sub. **Candidate fix: NINA plate-solve exposure
  → ~10 s.** Search radius (30°) and focal length (150) are already correct.
- **Additive-sync wildcard.** This mount's sync is additive (sync to truth,
  then a slew lands the same error the other way — proven 2026-05-30). NINA's
  Center does solve → **sync** → correct, so even with solving fixed, the
  *sync* step may oscillate. The Seestar **app's** align works because it's the
  mount's native routine.
- **Focus IS NINA-drivable.** The Seestar exposes "**Seestar S30 Pro Telephoto
  Focuser**" — connected, reports absolute position + temperature (24.4 °C).
  Move tested under NINA: 1290 → 1390 (1.6 s) → 1290 (2.1 s). It does **not**
  report MaxStep/StepSize (None/NaN), and `IsMoving` is laggy. So in-NINA
  autofocus is viable; the "S30 has no motorized focuser" note (target yamls +
  CLAUDE.md) is **wrong** and gets corrected once a clean AF curve is confirmed.

## Tonight's tests (the experiments that decide the build)
**Preflight (dusk):** NINA plate-solve exposure → 10 s, solver ASTAP; Hocus
Focus AF set (exp ~5–8 s LP, step ~30, 7–9 pts, settle ~2–3 s); `mira doctor`
RIG READY; **Seestar app closed.**

1. **Autofocus** — Hocus Focus on a star-rich field. Pass = clean V-curve +
   sharp return. Validates Phase 2 (`run_autofocus`).
2. **Center** — (a) single plate-solve at 10 s: does it solve? (b) slew-with-
   Center to M97: does it converge, or oscillate on the sync?
   - **Converges →** NINA Center is usable; Phase 1 becomes "use it + guard the
     plate-solve config."
   - **Oscillates →** it's the additive sync; Phase 1 must be the Mira-native
     offset-slew loop (below).

## Enhancements (phased)

### Phase 1 — Mira-native plate-solve centering ★ (high value)
Stop depending on NINA's internal Center. Mira runs its own loop:
`blind slew → capture frame → solve with our offline ASTAP → offset-slew the
correction → repeat to tolerance.`
- Uses our **proven offline ASTAP** (not NINA's flaky internal solve).
- **Offset slews, never sync** → sidesteps the additive-sync problem entirely.
- Natural extension of `_verify_pointing` in `capture.py` (already captures +
  solves + computes the offset; add correct-and-iterate + a cap + fail-soft to
  blind slew).
- Robust regardless of tonight's Center outcome — this is the proper "drive
  from Mira" path. Expose via `--center`, or make `--platesolve-center` use
  this Mira-native path instead of NINA's Center.
- Tolerance can be generous (a few arcmin) given the wide S30 field.

### Phase 2 — Mira-driven autofocus (mostly already wired)
- `--autofocus-every-min` already calls `run_autofocus` → NINA AF. Now that the
  focuser's drivable, validate it works with Hocus Focus (tonight).
- Add `--autofocus-at-start` (focus once — it holds; matches "control, not
  frequency").
- Enable in the S30 target yamls; drop the "no motorized focuser" assumption;
  correct CLAUDE.md.
- Config gotchas: manual step size (driver gives NaN StepSize), generous settle
  (laggy `IsMoving`), bound the sweep (MaxStep unknown — probe travel once).

### Phase 3 — polish
- `mira doctor`: focuser check (connected + a tiny test-move, like the
  1290↔1390 probe).
- Optional **temp-compensated refocus** using the focuser's temp sensor.
- Maybe a standalone `mira focus` to trigger AF on demand.

## Decisions / out of scope
- **NINA Filter Offset Calculator — NOT for the S30.** Filter offsets dial in
  the per-filter focus *delta* so you can switch filters mid-session without a
  full AF. The S30 images **single-filter (LP) all session** — no switching, so
  there's no offset to apply (offset relative to what?). We autofocus *through*
  LP and use that focus directly; LP is its own reference. **This plugin IS
  valuable on the Esprit** (LRGB-V + SHO, non-parfocal, switched within a
  session) — revisit when the Esprit comes online. (If we ever run an LP+IR
  session on the S30, revisit then.)

## Open questions
- Does NINA Center survive the 10 s exposure fix, or does the additive sync
  force the Mira-native loop? (Tonight's Test 2.)
- Does Hocus Focus produce a clean V-curve despite the NaN StepSize / laggy
  `IsMoving`? (Tonight's Test 1.)
- Focuser travel range (MaxStep unknown) — probe once to bound AF sweeps.

## Results log
_(fold in tonight's test outcomes here)_
- 2026-05-30: plan created; focuser drivability + plate-solve-exposure theory
  confirmed pre-night. Center + AF on-sky tests pending.
