"""Read-only monitoring console for the Esprit DSO/narrowband rig.

Aggregates live state from NINA's Advanced API plus the DSO ledger and
catalog into a single ``MonitorSnapshot`` the webapp renders at
``/monitor``. Pure functions throughout (build_snapshot, detect_anomalies);
no I/O state of its own.

The design rule that anchors every module here: this is read-only by
design — nothing in this package issues any command to the rig. Same
risk-surface reasoning as the Hermes deployment question; an
LLM-driven console that could mis-issue mount commands is a category
of bug we explicitly designed out. If you ever want control, it lives
behind a confirmation gate elsewhere, not here.

See ``plans/monitoring_console.md`` for the full design doc.
"""
