# Agent workflows for Mira — proposal

How to apply the multi-agent **Workflow** primitive (deterministic orchestration
script that fans out subagents, with `pipeline()` / `parallel()` / structured
output / adversarial verify / judge-panel patterns) to Mira's five working
phases: configuration, nightly planning, capturing, troubleshooting, image
processing.

## The structural question first: separate, not one monolith

**Answer: a small *family* of single-phase workflows — not one big pipeline —
and only three of the five are really standalone workflows.** Reasons:

1. **Human gates + real-world time separate the phases.** You approve a plan,
   *then* hardware captures overnight, *then* you process the next morning. A
   monolith would either block for hours on those gates or — worse — automate
   straight through them next to a moving telescope. Mira's whole design is
   "candidate packet for human triage, not autonomous run"; orchestration
   should preserve those gates, not erase them.
2. **Different triggers.** Planning is nightly/scheduled. Troubleshooting is
   reactive (symptom-driven). Processing is post-capture. Config is occasional.
   One workflow can't have four trigger conditions.
3. **The fit is uneven.** Forcing one shape on all five over-engineers the
   serial ones (capture) and under-serves the judgment-heavy ones (processing).
4. **But they compose.** Shared structured-output schemas + artifact hand-off
   (plan → capture inputs → processing inputs) + I invoke them in sequence
   across a night. A family, each independently useful.

Think of it as Mira's existing philosophy — linear `mira` commands as the
deterministic workhorses, human triage between stages — lifted to
orchestration. **The workflow never re-implements a `mira` command; it *calls*
the command and adds the thing that's actually the bottleneck: judgment
(synthesis, scoring, adversarial verification).**

## Where workflows genuinely help — and where they don't

Two questions decide the fit: is the work **fan-out-able** (independent
sub-tasks), and is the bottleneck **judgment** (vs. deterministic compute or a
serial hardware resource)?

| Phase | Fan-out? | Bottleneck | Fit | Form |
|---|---|---|---|---|
| Image processing | Yes — recipe variants | Judgment (which looks best) | **Strongest** | `process-finish` workflow |
| Nightly planning | Yes — 4 target paths + conditions | Judgment (which target tonight) | **Strong** | `plan-tonight` workflow |
| Troubleshooting | Yes — competing hypotheses | Judgment (root cause) | **Strong** | `diagnose` workflow |
| Configuration | Some — parallel probes | Deterministic checks | **Light** | thin `preflight` (mostly `mira doctor`) |
| Capturing | **No** — one mount, serial, hours | Serial hardware | **Poor for the loop** | stays a plain `mira capture` |

So: **three core workflows + one light one + capture-as-a-plain-command.**
Not five, not one.

---

## A. `process-finish` — image processing (the strongest fit)

This is literally the "~15 experiments, judge by stats AND eye, pick the best"
loop I ran by hand on M51/M57. It's a textbook **variant tournament → judge
panel → adversarial verify**.

- **Input:** one stacked + GraXpert'd *linear* master (shared, read-only).
- **Phase 1 — variant fan-out (`pipeline`).** N agents, each applying a
  different recipe across the real levers: deconv-strength sweep
  (0.5/0.25/0.15 — the M57 ringing search), denoise on/off, the asinh
  `param`/black/white/sat grid, Hα-blend `K` values, LRGB-vs-natural. Each
  writes to its **own** `tmp/variants/v_<i>/` dir and returns its `stretch.py`
  stats line (bg noise, target SNR, faint-feature SNR, corner flatness) as
  structured output.
- **Phase 2 — judge panel.** Score every variant on **stats** (the numbers)
  *and* **eye** — a vision agent that actually `Read`s the PNG and flags
  walking-noise streaks, denoise plastic, deconv ringing, color cast, clipped
  core. Distinct lenses (sharpness / color fidelity / noise / artifacts) beat
  one redundant judge.
- **Phase 3 — adversarial verify on the winner.** An agent prompted to
  *refute*: "are those bright-rim features real stars or deconv ringing?"
  **This is exactly the check that would have caught my M57 mistake** — I first
  claimed "2 real stars," you pushed back, and they turned out to be ringing.
- **Output:** ranked variants + scores + the winning recipe + reasoning + the
  keeper image; keep 1–2 legitimate alternates (restrained-color, single-best-
  night — the skill already treats these as valid different "bests").
- **Optional loop-until-dry:** keep spawning variants around the current best
  until K rounds yield no stats/aesthetic gain.
- **Isolation note:** do **not** use `isolation: 'worktree'` here — the masters
  are gitignored, so a worktree wouldn't even contain the input. Use distinct
  per-variant output dirs instead (shared read-only master in, separate dir out
  → no clobber).
- **We can prototype this today** on the existing M51/M57 linear masters.

## B. `plan-tonight` — nightly planning (multi-modal sweep + synthesis)

Mira already has *four* independent target-finding paths I currently run
serially and reconcile by hand. That reconciliation is the judgment to lift.

- **Phase 1 — parallel barrier** (`parallel`, because synthesis needs all of
  them): one agent per path, each returning structured candidates
  (name, RA/Dec, score, observable window, why):
  - `mira tonight` → VSX variable-star queue
  - `mira galaxies plan` → bright galaxies (S30)
  - `mira dso plan` → narrowband DSO (only if the Esprit is on the pier)
  - `mira transients` → bright SNe/novae
  - a **conditions** agent: moon phase/illumination tonight, the
    `horizon_balcony_jc.yaml` profile (when does the target clear the house?),
    optional weather.
- **Phase 2 — synthesis judge.** One agent folds all candidates + tonight's
  conditions into a single *prescriptive* plan: "full moon → galaxies wash out,
  pick emission/transients; M27 clears the house at 23:15, M97 opener before
  that." This is the exact reasoning behind the recent M27/M97 night.
- **Output:** ranked, time-slotted plan → feeds capture inputs (RA/Dec,
  exposure, filter, dither).
- **Safe to fan out:** the four paths hit *different* external services
  (VizieR / IRSA / Rochester) and Mira caches — 4-wide is polite. (Contrast the
  guardrail below.)
- **Human gate:** I present the plan; you approve before anything slews.

## C. `diagnose` — troubleshooting (hypothesis fan-out + adversarial verify)

Diagnosis is where multi-agent earns its keep: the failure mode is *anchoring
on the first plausible theory*, and parallel + adversarial directly counters it.

- **Input:** a symptom ("NINA Center hangs at 300s", "telescope didn't park",
  "walking-noise streak", "PCC imprecise").
- **Phase 1 — parallel hypothesis investigators** (read-only, Explore-style;
  safe to fan wide): each pursues one theory and gathers evidence — read
  configs, grep logs, poll the NINA API state, read the relevant source, check
  versions. For the Center hang: (1) plate-solver config (ASTAP DB / radius /
  exposure), (2) plate-scale (FocalLength=NaN), (3) mount sync semantics
  (additive), (4) network/API timeout. Each returns evidence + a likelihood.
- **Phase 2 — synthesis:** rank causes by evidence.
- **Phase 3 — adversarial verify:** a skeptic tries to refute the top cause and
  names the single discriminating test. (My real wins — additive sync, the 2s
  plate-solve exposure starving stars under moon — came from exactly this
  multi-hypothesis reasoning.)
- **Output:** ranked causes + recommended fix + the one test that confirms it.
- Reads the codebase + memory + logs; mutates nothing → low-risk fan-out.

## D. `preflight` — configuration (light; mostly `mira doctor`)

`mira doctor` already does the serial checks. The workflow value is small and
specific: run the independent probes in parallel and **auto-escalate any FAIL
into `diagnose` (C)**.

- **Phase 1 — parallel probes:** ASCOM connectivity, disk free vs. session
  size, filter-wheel canonical names, plate-solver config, VSX/network reach,
  **flat freshness** (masters stale for tonight's gain/focus?), polar-align /
  focus readiness.
- **Phase 2 — conditional:** for each red probe, spawn a `diagnose` mini-run;
  all green → done.
- **Honest take:** if `mira doctor` is healthy this is overkill. Build it only
  as a thin front-end (`mira doctor` → conditional `diagnose`), not a
  reimplementation of the checks.

## E. Capturing — deliberately NOT a workflow

The capture loop is a single, sequential, hours-long **hardware** process
(`mira capture`). One mount, one camera — nothing to parallelize, and an agent
can't hold a 4-hour hardware session. Forcing it into a workflow is the wrong
tool. Its orchestration value lives in the bookends, which belong to other
workflows:

- **Before:** `preflight` (D) gates the session.
- **During:** lightweight anomaly watch (HFR drift, guide RMS, star-count drop
  = clouds) — but that's **monitoring-console / `ScheduleWakeup` polling**
  territory, not fan-out. Flag it as such; don't shoehorn it into Workflow.
- **After:** `process-finish` (B) triages the subs.

Capture stays a plain, human-gated `mira capture` call, bracketed by D and B.

---

## How the family composes across a night

1. `preflight` (D) → rig green?
2. `plan-tonight` (B) → you approve → capture inputs (target, RA/Dec, exposure,
   filter, dither).
3. `mira capture` (plain command, human-gated, hardware) → subs + sidecar.
   [+ optional monitoring-console watch]
4. next morning: `process-finish` (A) → keeper image.
5. anytime a symptom appears: `diagnose` (C), reactively.

Shared contracts: structured-output schemas for candidates / variants /
hypotheses; artifact hand-off via the existing `output/` + `mira_capture.json`
conventions. Each workflow is independently invokable and independently useful.

## Guardrails (Mira-specific)

- **Respect the external-service politeness Mira already encodes.** VSX/VizieR,
  IRSA/ZTF, AAVSO, Rochester are rate-limited; Mira deliberately serializes +
  caches + top-N's them. **Never fan out 16 agents at one service** — that's a
  ban risk. The planning sweep is safe only because it's 4 *different* services;
  a "fetch 50 targets' AAVSO in parallel" workflow is a footgun. Per-service
  concurrency 1, or lean on the cache.
- **Hardware is a singleton.** Never fan out anything that touches the
  mount/camera/filter wheel. One session, serial.
- **File-write isolation for parallel processing** via distinct per-variant
  output dirs — **not** `worktree` isolation (the masters are gitignored, so a
  worktree wouldn't contain them).
- **Human gates stay.** Workflows emit *proposals / triage* (a plan, ranked
  variants, ranked causes). The human approves before hardware moves or before
  a "keeper" is blessed.
- **Don't reimplement `mira`.** Agents call the deterministic commands and judge
  the outputs; the workflow adds synthesis + verification, nothing else.

## Status / recommended first build

Plan only — no workflow code yet. **Recommended first prototype:
`process-finish`** — strongest fit, we have M51/M57 linear masters to test on,
it's the loop I already do by hand, and it's low-risk (reads a shared master,
writes to scratch dirs, blesses nothing without you). `plan-tonight` is the
natural second (and tonight is a planning opportunity).
