"""DSO / narrowband planner. Parallel to the VSX side of Mira but with
different inputs (curated YAML, not a remote catalog) and different scoring
(per-filter integration budgets + FOV fit, not photometric novelty).

The package is split into:

- ``catalog`` — YAML schema + loader for the curated DSO target list.
- ``planner`` — observability-aware ranking. Reuses the VSX observability
  machinery via ``evaluate_observability_at_coords`` so the altitude /
  horizon / sun / moon logic stays in one place.
- ``report`` — Markdown + CSV plan output, NINA Target Scheduler-compatible
  rows.

Phase 1 (this version) covers catalog + planner + plan output. Phase 2 will
add an integration ledger (aggregating ``mira_capture.json`` sidecars into
per-target/per-filter totals so the planner can rank by remaining-budget).
Phase 3 adds a per-night scheduler with filter rotation. Phase 4 is the
Aladin Lite viewer in the webapp.
"""
