"""Tests for the bright-transient path (`mira transients`).

Covers the scrape parser (against a fixture of real Rochester rows — the
coordinate-units conversion is pinned here because it was a real bug) and
the observability/reach planner.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest import TestCase

from mira.config import (
    AavsoConfig, FilterConfig, GaiaConfig, ObserverConfig, OutputConfig,
    ScoringConfig, ScoutConfig, SimbadConfig, SiteConfig, VsxQueryConfig,
    WindowConfig, ZtfConfig,
)
from mira.transients.catalog import Transient, parse_active_supernovae
from mira.transients.planner import build_transient_candidates


# Verbatim rows from rochesterastronomy.org (trimmed to a representative
# set): a normal high-dec row, a stale (*) row whose name links out to
# novae.html, a hostless ("none") row that still carries coordinates, a row
# with a non-link host cell (no coords → must be skipped), and a row with a
# non-numeric magnitude (→ skipped).
FIXTURE = """
<b>All active supernova over mag 17.0</b>
<table>
<tr><th>Name</th><th>Mag</th><th>Type</th><th>Host</th></tr>
<tr><td><a href="#2026fov" target="_self">2026fov</a></td><td>14.0</td><td>II</td><td><a href="http://www.wikisky.org/?ra=22.474234&de=30.298462&zoom=10&show_box=1&box_width=50">NGC 7292</a></td></tr>
<tr><td><a href="#2026fvx" target="_self">2026fvx</a></td><td>15.1</td><td>Ia</td><td><a href="http://www.wikisky.org/?ra=12.249481&de=63.787891&zoom=10&show_box=1&box_width=50">NGC 4205</a></td></tr>
<tr><td><a href="novae.html#2026jnl" target="_self">AT2026jnl</a></td><td>15.4*</td><td>unk</td><td><a href="http://www.wikisky.org/?ra=0.727367&de=41.270416&zoom=10&show_box=1&box_width=50">M31</a></td></tr>
<tr><td><a href="#2026nma" target="_self">AT2026nma</a></td><td>15.3</td><td>unk</td><td><a href="http://www.wikisky.org/?ra=11.415004&de=47.950371&zoom=10&show_box=1&box_width=50">none</a></td></tr>
<tr><td><a href="#nocoord" target="_self">2026zzz</a></td><td>16.0</td><td>Ia</td><td>UGC 9999</td></tr>
<tr><td><a href="#badmag" target="_self">2026qqq</a></td><td>?</td><td>Ia</td><td><a href="http://www.wikisky.org/?ra=10.0&de=10.0&zoom=10">NGC 1</a></td></tr>
</table>
"""


class ParseTests(TestCase):
    def setUp(self) -> None:
        self.ts = parse_active_supernovae(FIXTURE)
        self.by_name = {t.name: t for t in self.ts}

    def test_parses_only_valid_rows(self) -> None:
        # 4 valid; the no-coord and bad-mag rows are skipped.
        self.assertEqual(len(self.ts), 4)
        self.assertNotIn("2026zzz", self.by_name)  # no coords
        self.assertNotIn("2026qqq", self.by_name)  # non-numeric mag

    def test_ra_converted_from_hours_to_degrees(self) -> None:
        # THE regression guard: wikisky ?ra= is decimal HOURS, not degrees.
        # NGC 7292: ra=22.474234h → 337.11°, dec stays 30.30°.
        t = self.by_name["2026fov"]
        self.assertAlmostEqual(t.ra_deg, 22.474234 * 15.0, places=4)
        self.assertAlmostEqual(t.ra_deg, 337.1135, places=3)
        self.assertAlmostEqual(t.dec_deg, 30.2985, places=3)

    def test_magnitude_and_type_and_host(self) -> None:
        t = self.by_name["2026fvx"]
        self.assertEqual(t.magnitude, 15.1)
        self.assertEqual(t.sn_type, "Ia")
        self.assertEqual(t.host, "NGC 4205")
        self.assertFalse(t.mag_stale)

    def test_stale_flag(self) -> None:
        t = self.by_name["AT2026jnl"]
        self.assertTrue(t.mag_stale)
        self.assertEqual(t.magnitude, 15.4)  # the '*' is stripped from the value

    def test_hostless_row_still_has_coords(self) -> None:
        t = self.by_name["AT2026nma"]
        self.assertEqual(t.host, "none")
        self.assertAlmostEqual(t.ra_deg, 11.415004 * 15.0, places=3)

    def test_missing_marker_returns_empty(self) -> None:
        self.assertEqual(parse_active_supernovae("<html>no table here</html>"), [])


def _site(name: str = "JC") -> SiteConfig:
    return SiteConfig(
        name=name,
        observer=ObserverConfig(40.7178, -74.0431, "America/New_York"),
        observing_window=WindowConfig(
            start_hour_local=20, end_hour_local=2, nights=1, sample_minutes=30,
            min_altitude_deg=25, max_sun_altitude_deg=-12.0,
            max_moon_altitude_deg=30.0, max_moon_illumination=0.7,
            min_moon_separation_deg=30.0,
        ),
        filters=FilterConfig(0, 0, 0, 20, 0),
    )


def _config(*sites: SiteConfig) -> ScoutConfig:
    return ScoutConfig(
        sites=tuple(sites) or (_site(),),
        vsx_query=VsxQueryConfig(100, 30, 3, -10, 17, False, ()),
        scoring=ScoringConfig(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        aavso=AavsoConfig(False, 0, 0, 0, 0, (), 0),
        simbad=SimbadConfig(False, 0, 0, 0),
        gaia=GaiaConfig(False, 0, 0, 0),
        ztf=ZtfConfig(False, 0, 0, 0, (), 0),
        output=OutputConfig(directory=Path("/tmp"), top_packets=10),
    )


def _t(name, mag, ra, dec, *, stale=False, typ="Ia", host="NGC x") -> Transient:
    return Transient(name=name, magnitude=mag, mag_stale=stale,
                     sn_type=typ, host=host, ra_deg=ra, dec_deg=dec)


class PlannerTests(TestCase):
    DATE = date(2026, 8, 15)
    UP = (303.025, 45.0)     # high transit from JC in mid-August
    DOWN = (303.025, -80.0)  # never clears the horizon from JC

    def test_unobservable_dropped(self) -> None:
        cands = build_transient_candidates(
            [_t("up", 13.0, *self.UP), _t("down", 13.0, *self.DOWN)],
            _config(), start_date=self.DATE, max_mag=16.0,
        )
        names = [c.transient.name for c in cands]
        self.assertIn("up", names)
        self.assertNotIn("down", names)

    def test_within_reach_flag(self) -> None:
        cands = build_transient_candidates(
            [_t("bright", 13.0, *self.UP), _t("faint", 17.0, *self.UP)],
            _config(), start_date=self.DATE, max_mag=15.0,
        )
        by = {c.transient.name: c for c in cands}
        self.assertTrue(by["bright"].within_reach)
        self.assertFalse(by["faint"].within_reach)

    def test_sort_reachable_first_then_brightest(self) -> None:
        cands = build_transient_candidates(
            [_t("faint_reach", 14.0, *self.UP),
             _t("bright_reach", 12.0, *self.UP),
             _t("beyond", 17.0, *self.UP)],
            _config(), start_date=self.DATE, max_mag=15.0,
        )
        self.assertEqual(
            [c.transient.name for c in cands],
            ["bright_reach", "faint_reach", "beyond"],
        )
