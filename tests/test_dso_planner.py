"""Tests for the DSO planner — observability + FOV-fit + moon-relax ranking."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest import TestCase

from mira.config import (
    AavsoConfig, DsoConfig, FilterConfig, GaiaConfig, ObserverConfig,
    OutputConfig, ScoringConfig, ScoutConfig, SimbadConfig, SiteConfig,
    VsxQueryConfig, WindowConfig, ZtfConfig,
)
from mira.dso.catalog import DsoCatalog, DsoTarget
from mira.dso.planner import build_dso_candidates


def _make_site(name: str = "Test JC", **overrides) -> SiteConfig:
    window = WindowConfig(
        start_hour_local=overrides.get("start_hour_local", 20),
        end_hour_local=overrides.get("end_hour_local", 2),
        nights=overrides.get("nights", 1),
        sample_minutes=overrides.get("sample_minutes", 30),
        min_altitude_deg=overrides.get("min_altitude_deg", 25),
        max_sun_altitude_deg=-12.0,
        max_moon_altitude_deg=overrides.get("max_moon_altitude_deg", 30.0),
        max_moon_illumination=overrides.get("max_moon_illumination", 0.7),
        min_moon_separation_deg=overrides.get("min_moon_separation_deg", 30.0),
    )
    return SiteConfig(
        name=name,
        observer=ObserverConfig(
            latitude_deg=40.7178,
            longitude_deg=-74.0431,
            timezone="America/New_York",
        ),
        observing_window=window,
        filters=FilterConfig(
            min_galactic_latitude_abs_deg=0,
            min_catalog_amplitude_mag=0,
            prefer_amplitude_mag=0,
            prefer_max_mag=20,
            reject_saturated_brighter_than_mag=0,
        ),
    )


def _make_config(*sites: SiteConfig) -> ScoutConfig:
    return ScoutConfig(
        sites=tuple(sites),
        vsx_query=VsxQueryConfig(100, 30, 3, -10, 17, False, ()),
        scoring=ScoringConfig(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        aavso=AavsoConfig(False, 0, 0, 0, 0, (), 0),
        simbad=SimbadConfig(False, 0, 0, 0),
        gaia=GaiaConfig(False, 0, 0, 0),
        ztf=ZtfConfig(False, 0, 0, 0, (), 0),
        output=OutputConfig(directory=Path("/tmp"), top_packets=10),
    )


def _make_target(
    name: str = "T1",
    ra_deg: float = 303.025,    # NGC 6888 — high transit from JC
    dec_deg: float = 38.35,
    size_arcmin=(18.0, 13.0),
    object_type: str = "WR",
    budget=None,
) -> DsoTarget:
    return DsoTarget(
        name=name,
        common_name=name,
        object_type=object_type,
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        size_arcmin=size_arcmin,
        constellation="Cyg",
        budget_minutes=budget or {"Ha": 600, "OIII": 600, "SII": 480},
    )


class BuildDsoCandidatesTests(TestCase):
    def test_culminating_target_is_viable(self) -> None:
        # NGC 6888 in mid-August from JC transits very high.
        config = _make_config(_make_site())
        catalog = DsoCatalog(
            version="t", defaults={}, targets=(_make_target(),),
        )
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
        )
        self.assertEqual(len(cands), 1)
        cand = cands[0]
        self.assertGreater(cand.best_observability.minutes_above_minimum, 0)
        self.assertGreater(cand.best_observability.max_altitude_deg, 60)
        self.assertTrue(cand.fits_fov)

    def test_too_southern_target_drops_out(self) -> None:
        # Dec -60 from JC (lat +40.7) never rises above 25° floor.
        config = _make_config(_make_site())
        catalog = DsoCatalog(version="t", defaults={}, targets=(
            _make_target(dec_deg=-60.0),
        ))
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
        )
        self.assertEqual(cands, [])

    def test_mosaic_flagged_and_demoted(self) -> None:
        config = _make_config(_make_site())
        # Same RA/Dec, one fits FOV, one doesn't (oversized + mosaic flag).
        small = _make_target(name="Small", size_arcmin=(20.0, 15.0))
        big = DsoTarget(
            name="Big", common_name="Big", object_type="HII",
            ra_deg=303.025, dec_deg=38.35,
            size_arcmin=(240.0, 180.0),
            constellation="Cyg", budget_minutes={"Ha": 600},
            mosaic=True,
        )
        catalog = DsoCatalog(version="t", defaults={}, targets=(big, small))
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            fov_deg=(1.6, 1.07),
        )
        # Both viable, but the FOV-fitting one ranks first (mosaic demoted).
        names = [c.target.name for c in cands]
        self.assertEqual(names[0], "Small")
        self.assertEqual(names[1], "Big")
        big_cand = next(c for c in cands if c.target.name == "Big")
        small_cand = next(c for c in cands if c.target.name == "Small")
        self.assertFalse(big_cand.fits_fov)
        self.assertTrue(small_cand.fits_fov)
        self.assertLess(big_cand.score, small_cand.score)

    def test_moon_relax_only_applies_to_narrowband(self) -> None:
        # Pin: a broadband-only DSO target (REF/galaxy with L+RGB) gets the
        # VSX-style moon gate; a narrowband target ignores moon entirely.
        # The way to surface this without faking a moon-up date is to set
        # max_moon_altitude_deg=-90 (always treated as "moon below limit",
        # so the moon-separation gate never activates) — which is the
        # default site config; we instead lock max_moon_altitude_deg to a
        # value low enough that the moon will sometimes trip it.
        site = _make_site(
            min_moon_separation_deg=180.0,    # any sky → blocked when moon-up
            max_moon_altitude_deg=0.0,
            max_moon_illumination=0.0,        # any phase counts as bright
        )
        config = _make_config(site)
        narrowband = _make_target(name="NB", budget={"Ha": 600})
        broadband = _make_target(
            name="BB", budget={"L": 240, "R": 180, "G": 180, "B": 180},
        )
        catalog = DsoCatalog(
            version="t", defaults={}, targets=(narrowband, broadband),
        )
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            relax_moon=True,
        )
        # Narrowband still observable (moon ignored). Broadband may be
        # observable or not depending on the moon that night — but
        # importantly, when relax_moon=False, *neither* should get a free
        # pass.
        names_relaxed = {c.target.name for c in cands}
        self.assertIn("NB", names_relaxed)
        cands_strict = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            relax_moon=False,
        )
        names_strict = {c.target.name for c in cands_strict}
        # In strict mode, NB no longer gets the moon-relax — its viability
        # equals the broadband one. The point of this test: relax_moon=True
        # must produce ≥ candidates than relax_moon=False (narrowband can
        # only gain viability, never lose it).
        self.assertGreaterEqual(len(names_relaxed), len(names_strict))

    def test_ranking_score_orders_results(self) -> None:
        # Two narrowband targets in Cygnus; the higher-transit one should
        # outrank the lower-transit one.
        config = _make_config(_make_site())
        high = _make_target(name="High", dec_deg=40.0)
        low = _make_target(name="Low", dec_deg=10.0)
        catalog = DsoCatalog(version="t", defaults={}, targets=(low, high))
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
        )
        self.assertEqual([c.target.name for c in cands], ["High", "Low"])

    def test_multi_site_picks_best(self) -> None:
        # JC vs a phantom Fairbanks. NGC 6888 (dec +38) transits higher at
        # JC than at Fairbanks (lat +64.8); test that best_observability
        # is the site with the most dark-minutes above floor.
        jc = _make_site(name="JC")
        fbx = _make_site(
            name="Fairbanks",
            min_altitude_deg=25,
            max_sun_altitude_deg=-12.0,
        )
        # Hack: replace Fairbanks lat/lon by re-building the observer block
        fbx = replace(
            fbx,
            observer=ObserverConfig(
                latitude_deg=64.8378,
                longitude_deg=-147.7164,
                timezone="America/Anchorage",
            ),
        )
        config = _make_config(jc, fbx)
        catalog = DsoCatalog(
            version="t", defaults={}, targets=(_make_target(),),
        )
        # Late November — Fairbanks has long nights, JC has limited but the
        # target rises higher at JC. Either could win; what we're testing
        # is just that best_observability points at one of them, not None.
        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 11, 1),
        )
        self.assertEqual(len(cands), 1)
        self.assertIn(cands[0].best_site_name, {"JC", "Fairbanks"})
        self.assertEqual(len(cands[0].observabilities), 2)


class RelaxMoonAllTests(TestCase):
    """relax_moon_all — the engine half of `mira galaxies plan --relax-moon`.

    The narrowband-only relax above is pinned and stays the default; but
    every shipped galaxy is broadband, so without an explicit force the
    --relax-moon flag was a silent no-op on the galaxy path. These tests
    are deterministic regardless of where the moon happens to be: forcing
    the relax on a fully-moon-blocked site must reproduce a moon-free
    site's result exactly (``_maybe_relax_moon`` replaces the moon gates
    with exactly the moon-free values)."""

    DATE = date(2026, 8, 15)

    def _strict_moon_site(self) -> SiteConfig:
        # Any sky is blocked whenever the moon is above the horizon.
        return _make_site(
            min_moon_separation_deg=180.0,
            max_moon_altitude_deg=0.0,
            max_moon_illumination=0.0,
        )

    def _moon_free_site(self) -> SiteConfig:
        # The exact permissive values _maybe_relax_moon installs.
        return _make_site(
            min_moon_separation_deg=0.0,
            max_moon_altitude_deg=90.0,
            max_moon_illumination=1.01,
        )

    def test_relax_moon_all_relaxes_broadband(self) -> None:
        broadband = _make_target(name="BB", budget={"IR": 240})
        catalog = DsoCatalog(version="t", defaults={}, targets=(broadband,))
        forced = build_dso_candidates(
            catalog, _make_config(self._strict_moon_site()),
            start_date=self.DATE, relax_moon_all=True,
        )
        free = build_dso_candidates(
            catalog, _make_config(self._moon_free_site()),
            start_date=self.DATE,
        )
        self.assertEqual(len(forced), 1)
        self.assertEqual(len(free), 1)
        self.assertEqual(forced[0].score, free[0].score)
        self.assertEqual(
            forced[0].best_observability.minutes_above_minimum,
            free[0].best_observability.minutes_above_minimum,
        )
        # The reason must not claim the galaxy is narrowband.
        self.assertIn("moon-relaxed (forced)", forced[0].reasons)
        self.assertNotIn("moon-relaxed (narrowband)", forced[0].reasons)

    def test_relax_moon_all_covers_narrowband_even_with_relax_moon_off(self) -> None:
        nb = _make_target(name="NB", budget={"Ha": 600})
        catalog = DsoCatalog(version="t", defaults={}, targets=(nb,))
        forced = build_dso_candidates(
            catalog, _make_config(self._strict_moon_site()),
            start_date=self.DATE, relax_moon=False, relax_moon_all=True,
        )
        free = build_dso_candidates(
            catalog, _make_config(self._moon_free_site()),
            start_date=self.DATE, relax_moon=False,
        )
        self.assertEqual(len(forced), 1)
        self.assertEqual(forced[0].score, free[0].score)
        # Narrowband keeps its honest label even when force-relaxed.
        self.assertIn("moon-relaxed (narrowband)", forced[0].reasons)

    def test_default_false_keeps_broadband_strict(self) -> None:
        # The documented no-op the kwarg exists to fix: with relax_moon_all
        # left at its default, a broadband target on a moon-strict site is
        # bit-for-bit identical whether relax_moon is True or False.
        broadband = _make_target(name="BB", budget={"IR": 240})
        catalog = DsoCatalog(version="t", defaults={}, targets=(broadband,))
        config = _make_config(self._strict_moon_site())
        with_relax = build_dso_candidates(
            catalog, config, start_date=self.DATE, relax_moon=True,
        )
        without = build_dso_candidates(
            catalog, config, start_date=self.DATE, relax_moon=False,
        )
        self.assertEqual(
            [(c.target.name, c.score, c.reasons) for c in with_relax],
            [(c.target.name, c.score, c.reasons) for c in without],
        )


class DsoConfigDefaultsTests(TestCase):
    def test_default_dsoconfig_present_on_scoutconfig(self) -> None:
        # ScoutConfig.dso must always have a value — even on configs that
        # don't declare a `dso:` YAML section, the field defaults to
        # DSO_DEFAULTS so `cfg.dso.catalog_path` is safe to read.
        from mira.config import DSO_DEFAULTS
        config = _make_config(_make_site())
        self.assertEqual(config.dso.enabled, DSO_DEFAULTS.enabled)
        self.assertEqual(config.dso.fov_deg, DSO_DEFAULTS.fov_deg)
        self.assertTrue(config.dso.relax_moon)
        # Phase 2 fields default sensibly too.
        self.assertEqual(config.dso.captures_root, DSO_DEFAULTS.captures_root)
        self.assertEqual(config.dso.deficit_weight, DSO_DEFAULTS.deficit_weight)


class LedgerAwareRankingTests(TestCase):
    """Phase 2 — when a ledger is provided, deficit weighting kicks in.
    These tests pin both directions: ledger=None must reproduce Phase 1
    ranking exactly, and ledger-aware must demote completed targets."""

    def _two_targets(self):
        # Two narrowband targets that both transit very high from JC in
        # August — without the ledger they score almost identically;
        # with the ledger and one of them "done," the order should flip.
        a = _make_target(name="A", dec_deg=38.0)
        b = _make_target(name="B", dec_deg=38.5)
        return a, b

    def test_ledger_none_matches_phase_1_exactly(self) -> None:
        """build_dso_candidates with ledger=None and deficit_weight at any
        value must produce identical results to the Phase-1 path. Pinned
        bit-for-bit on score and order."""
        config = _make_config(_make_site())
        a, b = self._two_targets()
        catalog = DsoCatalog(version="t", defaults={}, targets=(a, b))

        baseline = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
        )
        with_weight = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            ledger=None, deficit_weight=99.0,
        )
        self.assertEqual(
            [c.target.name for c in baseline],
            [c.target.name for c in with_weight],
        )
        for c1, c2 in zip(baseline, with_weight):
            self.assertEqual(c1.score, c2.score)
            # captured + completion_fraction are zero when ledger=None.
            # budget_minutes IS populated (it's a property of the target,
            # not the ledger) — that's intentional, so the display shows
            # the target's budget regardless of ledger state.
            self.assertEqual(c1.captured_minutes, 0.0)
            self.assertEqual(c1.completion_fraction, 0.0)

    def test_completed_target_demoted_but_kept(self) -> None:
        """Per user rule: completed targets STAY in the queue, just
        deprioritized. Build a ledger where A is fully imaged and B is
        untouched; B ranks ahead but A must still appear."""
        from mira.dso.ledger import SessionRecord, aggregate_ledger
        config = _make_config(_make_site())
        a, b = self._two_targets()
        catalog = DsoCatalog(version="t", defaults={}, targets=(a, b))

        sessions = [
            SessionRecord(
                sidecar_path=Path("synth"), target_name=a.name,
                filter_name=fname, gain=100, exposure_s=60.0,
                frames_copied=int(mins),
                started_utc=None, ended_utc=None, stopped_reason="",
                frame_count_source="result.copied",
            )
            for fname, mins in a.budget_minutes.items()
        ]
        ledger = aggregate_ledger(sessions, catalog=catalog)

        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            ledger=ledger, deficit_weight=1.0,
        )
        names = [c.target.name for c in cands]
        self.assertIn("A", names, "completed target must stay in queue")
        self.assertIn("B", names)
        self.assertEqual(names[0], "B")
        a_cand = next(c for c in cands if c.target.name == "A")
        b_cand = next(c for c in cands if c.target.name == "B")
        self.assertAlmostEqual(a_cand.completion_fraction, 1.0, places=4)
        self.assertEqual(b_cand.completion_fraction, 0.0)
        # B got 1.5x boost, A got 0.5x demote → ratio ~3x on near-twin observability.
        self.assertGreater(b_cand.score / a_cand.score, 2.5)

    def test_deficit_weight_zero_keeps_ledger_metadata_but_phase1_order(self) -> None:
        """deficit_weight=0 surfaces ledger metadata on candidates without
        affecting ranking — escape hatch for "show me the totals but don't
        re-rank."""
        from mira.dso.ledger import SessionRecord, aggregate_ledger
        config = _make_config(_make_site())
        a, b = self._two_targets()
        catalog = DsoCatalog(version="t", defaults={}, targets=(a, b))
        sessions = [SessionRecord(
            sidecar_path=Path("x"), target_name=a.name,
            filter_name="Ha", gain=100, exposure_s=60.0,
            frames_copied=int(a.budget_minutes["Ha"]),
            started_utc=None, ended_utc=None, stopped_reason="",
            frame_count_source="result.copied",
        )]
        ledger = aggregate_ledger(sessions, catalog=catalog)

        cands_off = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            ledger=ledger, deficit_weight=0.0,
        )
        cands_phase1 = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15), ledger=None,
        )
        self.assertEqual(
            [c.target.name for c in cands_off],
            [c.target.name for c in cands_phase1],
        )
        for c_off, c_phase1 in zip(cands_off, cands_phase1):
            self.assertEqual(c_off.score, c_phase1.score)
        # But ledger fields ARE populated on cands_off:
        a_off = next(c for c in cands_off if c.target.name == "A")
        self.assertGreater(a_off.captured_minutes, 0.0)

    def test_partial_completion_partial_demote(self) -> None:
        """Halfway-imaged target should rank between never-imaged and
        fully-imaged (linear in deficit_fraction)."""
        from mira.dso.ledger import SessionRecord, aggregate_ledger
        config = _make_config(_make_site())
        a, b = self._two_targets()
        c = _make_target(name="C", dec_deg=38.25)
        catalog = DsoCatalog(version="t", defaults={}, targets=(a, b, c))

        sessions = []
        for fname, mins in a.budget_minutes.items():
            sessions.append(SessionRecord(
                sidecar_path=Path("a"), target_name=a.name,
                filter_name=fname, gain=100, exposure_s=60.0,
                frames_copied=int(mins),
                started_utc=None, ended_utc=None, stopped_reason="",
                frame_count_source="result.copied",
            ))
        # C at exactly half each filter
        for fname, mins in c.budget_minutes.items():
            sessions.append(SessionRecord(
                sidecar_path=Path("c"), target_name=c.name,
                filter_name=fname, gain=100, exposure_s=60.0,
                frames_copied=int(mins // 2),
                started_utc=None, ended_utc=None, stopped_reason="",
                frame_count_source="result.copied",
            ))
        ledger = aggregate_ledger(sessions, catalog=catalog)

        cands = build_dso_candidates(
            catalog, config, start_date=date(2026, 8, 15),
            ledger=ledger, deficit_weight=1.0,
        )
        a_cand = next(c for c in cands if c.target.name == "A")
        c_cand = next(c for c in cands if c.target.name == "C")
        b_cand = next(c for c in cands if c.target.name == "B")
        self.assertAlmostEqual(c_cand.completion_fraction, 0.5, places=4)
        # Score multiplier order: B (1.5x) > C (1.0x) > A (0.5x).
        self.assertGreater(b_cand.score, c_cand.score)
        self.assertGreater(c_cand.score, a_cand.score)
        self.assertEqual([c.target.name for c in cands], ["B", "C", "A"])
