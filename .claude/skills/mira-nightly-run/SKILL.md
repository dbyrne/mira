---
name: mira-nightly-run
description: Plan tonight's observing session — run `mira tonight`, read the session schedule, and adjust window/site. Use at the start of an observing night to get the prescriptive phone-readable plan.
when_to_use: what should I image tonight, plan the session, run tonight, start of an observing night
allowed-tools: [Bash, Read]
shell: powershell
---

# Mira nightly run

```
mira tonight --config config/s30_pro_jc.yaml --hours 4
```
Writes to `output/s30_pro_jc/tonight/`. The **primary phone doc** is
`session_schedule.md` (chronological, prescriptive: time-slot table then
per-target detail). `session_plan.md` is the full menu if you want to
override the auto-pick. `nina_targets.csv` is the NINA Target Scheduler
import (scheduled subset, execution order).

## Flow
1. Run `mira-preflight` first. Don't plan a night the doctor says is
   un-dark or rig-broken.
2. Run the command. Pick `--hours` to match how long you'll actually be
   out. `--config` selects the site profile.
3. Read `session_schedule.md`. Import `nina_targets.csv` into NINA's
   Target Scheduler (project "Mira", the OSC exposure template).
4. Run the NINA sequence. For deep single-target work instead of the
   queue, use the `mira-deep-capture` skill.

## Failure modes (hardened, fail loud)
- **"VSX/VizieR unreachable ... No schedule produced"** -> total network
  outage. VSX is required to build a queue. Restore internet/tether and
  re-run. (Previous outputs in the dir were already cleared; this is
  expected — nothing else to do but reconnect and re-run.)
- **"Nothing in the next window"** -> legit empty window. Increase
  `--hours`, run later when targets rise, or `mira run` for the
  multi-night queue.

## Notes
- Re-running the same night reuses the HTTP cache (incidental
  resilience; there is no true offline mode — a no-signal site = no
  queue that night; tether/Starlink is the dependency).
- Site config tunes mag/amplitude/altitude floors. `config/s30_pro_jc`
  is the gear-tuned urban profile (prefer_max_mag 12, ZTF off).
