"""Resolver tests for `mira capture` config: CLI > session profile > builtin
default. Required-field validation. Hyphen/underscore key normalization."""
from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.cli import (
    CAPTURE_BUILTIN_DEFAULTS,
    CAPTURE_REQUIRED,
    _load_session_profile,
    _load_site_capture_defaults,
    resolve_capture_config,
)


def _ns(**kw):
    """argparse-style Namespace where missing attrs read as None (matching how
    the real argparse args look with default=None on every flag)."""
    return argparse.Namespace(**{**{
        "ra": None, "dec": None, "exposure": None, "dest": None,
        "gain": None, "dither_arcsec": None, "dither_every": None,
        "recenter_every": None, "n_max": None, "alt_floor": None,
        "sun_max": None, "lat": None, "lon": None, "settle": None,
        "nina_url": None, "nina_root": None, "target_name": None,
        "filter": None, "platesolve_center": None,
        "autofocus_every_min": None, "autofocus_timeout_s": None,
    }, **kw})


class TestResolveCaptureConfig(TestCase):
    def test_cli_wins_over_session_wins_over_builtin(self) -> None:
        args = _ns(dither_arcsec=99.0)                       # CLI
        session = {"dither_arcsec": 50.0, "dither_every": 4} # session profile
        cfg = resolve_capture_config(args, session=session)
        self.assertEqual(cfg["dither_arcsec"], 99.0)         # CLI wins
        self.assertEqual(cfg["dither_every"], 4)             # session wins (no CLI)
        self.assertEqual(cfg["recenter_every"],               # builtin (neither set)
                          CAPTURE_BUILTIN_DEFAULTS["recenter_every"])

    def test_full_precedence_cli_session_site_builtin(self) -> None:
        args = _ns(lat=10.0)                                  # CLI
        session = {"lat": 20.0, "lon": 30.0}                  # session
        site = {"lat": 40.0, "lon": 50.0, "nina_root": "/N"}  # site config
        cfg = resolve_capture_config(args, session=session, site=site)
        self.assertEqual(cfg["lat"], 10.0)                    # CLI wins
        self.assertEqual(cfg["lon"], 30.0)                    # session beats site
        self.assertEqual(cfg["nina_root"], "/N")              # site beats builtin
        # builtin path: setting that none of CLI/session/site touched
        self.assertEqual(cfg["dither_arcsec"],
                          CAPTURE_BUILTIN_DEFAULTS["dither_arcsec"])

    def test_site_only_satisfies_no_required_field(self) -> None:
        # capture_defaults is for site/rig constants, NOT target identity.
        # ra/dec/exposure/dest must still come from session or CLI.
        site = {"lat": 40.0, "lon": -74.0, "nina_root": "/N"}
        cfg = resolve_capture_config(_ns(), session={}, site=site)
        missing = [k for k in CAPTURE_REQUIRED if cfg.get(k) is None]
        self.assertEqual(set(missing), set(CAPTURE_REQUIRED))

    def test_session_fills_required_fields(self) -> None:
        args = _ns()
        session = {"ra": 202.47, "dec": 47.20, "exposure": 30, "dest": "/x"}
        cfg = resolve_capture_config(args, session=session)
        for k in CAPTURE_REQUIRED:
            self.assertIsNotNone(cfg[k], f"{k} should be resolved from session")

    def test_required_missing_when_neither_cli_nor_session(self) -> None:
        cfg = resolve_capture_config(_ns(), session={})
        missing = [k for k in CAPTURE_REQUIRED if cfg.get(k) is None]
        self.assertEqual(set(missing), set(CAPTURE_REQUIRED))

    def test_false_cli_does_not_get_overridden_by_truthy_session(self) -> None:
        # --no-platesolve-center on the CLI (False) must beat session True.
        args = _ns(platesolve_center=False)
        cfg = resolve_capture_config(
            args, session={"platesolve_center": True})
        self.assertFalse(cfg["platesolve_center"])

    def test_zero_cli_value_does_not_get_overridden(self) -> None:
        # `--autofocus-every-min 0` is meaningful (= disable) and must
        # beat a session profile that sets a nonzero value.
        args = _ns(autofocus_every_min=0)
        cfg = resolve_capture_config(
            args, session={"autofocus_every_min": 45})
        self.assertEqual(cfg["autofocus_every_min"], 0)


class TestLoadSessionProfile(TestCase):
    def test_returns_empty_when_path_is_none(self) -> None:
        self.assertEqual(_load_session_profile(None), {})

    def test_normalizes_hyphenated_keys_to_underscores(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "x.yaml"
            p.write_text(
                "dither-arcsec: 20\nautofocus-every-min: 30\nra: 10.0\n",
                encoding="utf-8",
            )
            session = _load_session_profile(str(p))
            self.assertEqual(session["dither_arcsec"], 20)    # hyphen -> underscore
            self.assertEqual(session["autofocus_every_min"], 30)
            self.assertEqual(session["ra"], 10.0)

    def test_rejects_non_mapping_yaml(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "list.yaml"
            p.write_text("- 1\n- 2\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                _load_session_profile(str(p))
            self.assertIn("mapping", str(cm.exception))

    def test_empty_yaml_returns_empty_dict(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "empty.yaml"
            p.write_text("# only comments\n", encoding="utf-8")
            self.assertEqual(_load_session_profile(str(p)), {})


class TestLoadSiteCaptureDefaults(TestCase):
    def test_returns_empty_when_path_is_none(self) -> None:
        self.assertEqual(_load_site_capture_defaults(None), {})

    def test_reads_capture_defaults_section_only(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "site.yaml"
            p.write_text(
                "sites:\n  - name: anywhere\n"
                "capture_defaults:\n  lat: 40.7178\n  nina_root: /tmp/N\n",
                encoding="utf-8",
            )
            site = _load_site_capture_defaults(str(p))
            self.assertEqual(site, {"lat": 40.7178, "nina_root": "/tmp/N"})

    def test_missing_section_returns_empty(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "site.yaml"
            p.write_text("sites:\n  - name: anywhere\n", encoding="utf-8")
            self.assertEqual(_load_site_capture_defaults(str(p)), {})

    def test_non_mapping_section_is_a_clear_error(self) -> None:
        with TemporaryDirectory() as d:
            p = Path(d) / "site.yaml"
            p.write_text("capture_defaults:\n  - 1\n  - 2\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                _load_site_capture_defaults(str(p))
            self.assertIn("capture_defaults", str(cm.exception))


class TestShippedSiteConfig(TestCase):
    """Smoke test config/s30_pro_jc.yaml carries the right capture_defaults
    so a `mira capture --config config/s30_pro_jc.yaml --session
    targets/m51.yaml --dest …` invocation needs no other flags."""

    def test_s30_pro_jc_capture_defaults_complete(self) -> None:
        path = Path(__file__).parent.parent / "config" / "s30_pro_jc.yaml"
        site = _load_site_capture_defaults(str(path))
        for k in ("lat", "lon", "nina_url", "nina_root",
                  "alt_floor", "sun_max", "settle"):
            self.assertIn(k, site, f"capture_defaults missing {k}")
        # The on-this-laptop nina_root must NOT be the OneDrive default.
        self.assertNotIn("OneDrive", site["nina_root"])


class TestShippedM51Profile(TestCase):
    """Smoke test that targets/m51.yaml is a valid session profile that
    satisfies the required-field gate when paired with a --dest CLI flag."""

    def test_m51_profile_loads_and_provides_required_minus_dest(self) -> None:
        path = Path(__file__).parent.parent / "targets" / "m51.yaml"
        self.assertTrue(path.exists(), "targets/m51.yaml missing")
        session = _load_session_profile(str(path))
        cfg = resolve_capture_config(_ns(dest="data/captures/m51_test"),
                                     session=session)
        for k in CAPTURE_REQUIRED:
            self.assertIsNotNone(cfg[k], f"{k} should be set")
        self.assertEqual(cfg["filter"], "LP")
        self.assertTrue(cfg["platesolve_center"])
        self.assertEqual(cfg["autofocus_every_min"], 45)
