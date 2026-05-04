# AAVSO Anomaly Scout

AAVSO Anomaly Scout finds variable-star follow-up candidates that are practical
to observe from Jersey City, NJ. The first version focuses on known VSX objects:
bright, observable, uncrowded enough for urban photometry, and plausibly worth
human review because their catalog metadata suggests uncertainty, stale periods,
or good amateur follow-up value.

The project intentionally produces a short observing queue rather than a giant
catalog. The useful artifact is a candidate packet that another observer can
inspect, challenge, or follow up.

For a clean continuation in a fresh thread or on another computer, start with
[`HANDOFF.md`](HANDOFF.md).

## What It Does

- Queries the public AAVSO VSX catalog via VizieR (`B/vsx/vsx`).
- Samples VSX in RA bins so the first-pass queue is not biased to RA 0.
- Filters targets for Jersey City observability.
- Avoids low-altitude and crowded Galactic-plane fields.
- Checks recent AAVSO coverage for top candidates.
- Adds SIMBAD context and cross-identifiers for candidate review.
- Caches successful archive/API calls in `data/cache/` for repeatable runs.
- Scores targets for amateur follow-up value.
- Optionally fetches ZTF light curves for top-ranked candidates.
- Writes CSV and Markdown candidate packets.

## Quick Start

```powershell
python -m pip install -e .
anomaly-scout run --config config/jersey_city.yaml
```

For a small smoke-test run:

```powershell
python -m pip install -e .
anomaly-scout run --config config/jersey_city.yaml --limit 50 --top 10 --aavso-top 5 --simbad-top 5 --ztf-top 0
```

Outputs are written to `output/` by default:

- `candidate_queue.csv`: ranked observing queue.
- `research_notes.md`: short triage notes for the highest-ranked candidates.
- `candidate_packets/*.md`: one review packet per top candidate.
- `candidate_packets/*.png`: light-curve plots when ZTF enrichment succeeds.

## Recommended First Use

Start without ZTF enrichment, review the queue, then enrich a few candidates:

```powershell
anomaly-scout run --config config/jersey_city.yaml --limit 500 --top 25 --aavso-top 25 --simbad-top 25 --ztf-top 0
anomaly-scout run --config config/jersey_city.yaml --limit 500 --top 10 --aavso-top 10 --simbad-top 10 --ztf-top 5
```

ZTF calls can be slow or occasionally time out. That is expected; the Scout will
keep going and mark the ZTF status in the candidate packet.

Successful network calls are cached under `data/cache/`. Delete that directory
when you want to force fresh archive queries.

To evaluate a specific observing season:

```powershell
anomaly-scout run --config config/jersey_city.yaml --start-date 2026-05-04
```

## Jersey City Assumptions

The default config assumes:

- Location: Jersey City, NJ (`40.7178`, `-74.0431`)
- Practical observing window: 8 PM to 1 AM local time
- Target altitude floor: `45 deg`
- First-pass target brightness: brighter than magnitude `15`
- Declination lower bound: `-10 deg`
- Galactic latitude floor: `|b| >= 12 deg`

These are deliberately conservative for urban differential photometry.

## Data Sources

- VSX through VizieR: `B/vsx/vsx`
- AAVSO recent coverage through the VSX object API
- SIMBAD context through the CDS SIMBAD TAP service
- ZTF light curves through IRSA: `https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves`

Use the generated packets as starting points, not as discovery claims. Before
submitting anything to VSX or AAVSO, manually check VSX, SIMBAD, recent
literature, field crowding, and your own calibrated photometry.
