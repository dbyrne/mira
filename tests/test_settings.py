from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.webapp.settings import (
    load_settings,
    save_settings,
    update_setting,
)


class SettingsTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_load_returns_empty_dict_when_missing(self) -> None:
        self.assertEqual(load_settings(self.state_dir), {})

    def test_save_and_load_roundtrip(self) -> None:
        save_settings(self.state_dir, {"observer_code": "ABC", "favorite_filter": "V"})
        loaded = load_settings(self.state_dir)
        self.assertEqual(loaded["observer_code"], "ABC")
        self.assertEqual(loaded["favorite_filter"], "V")

    def test_update_setting_preserves_other_keys(self) -> None:
        save_settings(self.state_dir, {"observer_code": "ABC", "other": "thing"})
        update_setting(self.state_dir, "observer_code", "XYZ")
        loaded = load_settings(self.state_dir)
        self.assertEqual(loaded["observer_code"], "XYZ")
        self.assertEqual(loaded["other"], "thing")

    def test_load_returns_empty_on_corrupt_json(self) -> None:
        (self.state_dir / "settings.json").write_text("{not valid json", encoding="utf-8")
        self.assertEqual(load_settings(self.state_dir), {})

    def test_none_state_dir_no_op(self) -> None:
        self.assertEqual(load_settings(None), {})
        save_settings(None, {"observer_code": "ABC"})  # should not raise
        update_setting(None, "observer_code", "ABC")  # should not raise
