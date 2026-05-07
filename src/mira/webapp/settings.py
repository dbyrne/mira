"""Persistent app-level settings (single-user, file-backed JSON).

Stores the small set of user preferences that don't belong on a
per-run record — currently just the AAVSO observer code so the
photometry form remembers it across sessions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SETTINGS_FILENAME = "settings.json"


def load_settings(state_dir: Path | None) -> dict[str, Any]:
    if state_dir is None:
        return {}
    path = state_dir / SETTINGS_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(state_dir: Path | None, settings: dict[str, Any]) -> None:
    if state_dir is None:
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / SETTINGS_FILENAME
    try:
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass


def update_setting(state_dir: Path | None, key: str, value: Any) -> None:
    """Convenience: load, set one key, save."""
    settings = load_settings(state_dir)
    settings[key] = value
    save_settings(state_dir, settings)
