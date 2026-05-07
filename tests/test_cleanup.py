"""Tests for the cleanup CLI: dry-run vs apply, age cutoff, submitted-protection."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.cli import cleanup


def _set_old(path: Path, age_days: float) -> None:
    """Set a file's mtime to N days in the past."""
    seconds = age_days * 86400
    new_time = time.time() - seconds
    os.utime(path, (new_time, new_time))


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "state_dir": "",
        "cache_dir": "",
        "older_than": 90,
        "runs": False,
        "cache": False,
        "apply": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class CleanupTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.state_dir = Path(self.tmp.name) / "runs"
        self.cache_dir = Path(self.tmp.name) / "cache"
        self.state_dir.mkdir()
        self.cache_dir.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _drop_run(self, run_id: str, age_days: float, submitted: bool = False) -> Path:
        path = self.state_dir / f"{run_id}.json"
        record = {
            "run_id": run_id,
            "kind": "submit:RR_LYR",
            "status": "done",
            "result": {"submitted_at": "2026-04-01T00:00:00+00:00"} if submitted else {},
        }
        path.write_text(json.dumps(record), encoding="utf-8")
        if age_days > 0:
            _set_old(path, age_days)
        return path

    def test_dry_run_does_not_delete(self) -> None:
        path = self._drop_run("old1", age_days=120)
        cleanup(_args(state_dir=str(self.state_dir), older_than=90, runs=True))
        self.assertTrue(path.exists())

    def test_apply_removes_old_unprotected(self) -> None:
        old = self._drop_run("old1", age_days=120)
        recent = self._drop_run("recent1", age_days=10)
        cleanup(_args(state_dir=str(self.state_dir), older_than=90, runs=True, apply=True))
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_submitted_runs_are_protected(self) -> None:
        submitted = self._drop_run("submitted1", age_days=180, submitted=True)
        unsubmitted = self._drop_run("draft1", age_days=180, submitted=False)
        cleanup(_args(state_dir=str(self.state_dir), older_than=90, runs=True, apply=True))
        self.assertTrue(submitted.exists())
        self.assertFalse(unsubmitted.exists())

    def test_settings_json_is_skipped(self) -> None:
        settings = self.state_dir / "settings.json"
        settings.write_text("{}", encoding="utf-8")
        _set_old(settings, 365)
        cleanup(_args(state_dir=str(self.state_dir), older_than=90, runs=True, apply=True))
        self.assertTrue(settings.exists())

    def test_cache_cleanup(self) -> None:
        old_cache = self.cache_dir / "vsx" / "abc.json"
        old_cache.parent.mkdir()
        old_cache.write_text("{}", encoding="utf-8")
        _set_old(old_cache, 120)

        recent_cache = self.cache_dir / "vsx" / "def.json"
        recent_cache.write_text("{}", encoding="utf-8")

        cleanup(_args(cache_dir=str(self.cache_dir), older_than=90, cache=True, apply=True))
        self.assertFalse(old_cache.exists())
        self.assertTrue(recent_cache.exists())

    def test_no_flag_no_op(self) -> None:
        # If neither --runs nor --cache, command exits early without touching anything
        old = self._drop_run("old1", age_days=120)
        cleanup(_args(state_dir=str(self.state_dir), older_than=90, apply=True))
        self.assertTrue(old.exists())
