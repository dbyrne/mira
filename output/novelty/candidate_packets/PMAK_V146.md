# PMAK V146

Score: **85.0**  
Observable from: **Fairbanks + Jersey City**

## Catalog

- VSX type: `EA`
- Coordinates: RA `302.69226`, Dec `56.17889`
- Catalog photometry: bright `10.660` V; amplitude `0.440` mag TESS
- Catalog amplitude: `0.440` mag
- Period: `56.35490000` days
- Spectral type: `K7.5Ve`
- Galactic latitude: `12.2 deg`
- VSX: https://www.aavso.org/vsx/index.php?view=detail.top&oid=10867917
- AAVSO finder chart: https://apps.aavso.org/vsp/photometry/?star=PMAK+V146&type=chart&fov=900&maglimit=15&resolution=150&north=up&east=left

## Observability from Fairbanks (best)

- Max altitude in dark window: `81.3 deg`
- Best single-night dark time above altitude floor: `420 min`
- Best window date: `2026-09-20`
- Best sampled local time: `2026-09-20T22:00:00-08:00`

## Observability from Jersey City

- Max altitude in dark window: `74.5 deg`
- Best single-night dark time above altitude floor: `300 min`
- Best window date: `2026-09-21`
- Best sampled local time: `2026-09-21T21:00:00-04:00`

## Observing Strategy

- Time-series follow-up: run continuously for 2-4 hours when the target is high, then compare the folded light curve against the VSX period.

## Why It Was Flagged

- max altitude 81.3 deg from Fairbanks
- long nightly window from Fairbanks
- catalog amplitude about 0.44 mag
- bright enough for Fairbanks (10.66)
- long-period cadence friendly (56.35 d)
- well away from Galactic plane (b=12.2 deg)
- also observable from Jersey City
- AAVSO recent-coverage check unavailable
- Gaia color anomaly: VSX type EA (short-period) but Gaia BP-RP=1.85 (expected <1.8)

## AAVSO Recent Coverage

- Status: `unavailable`
- Recent observations: not available (status above).
- Note: 405 Client Error: Not Allowed for url: https://vsx.aavso.org/index.php?view=api.object&ident=PMAK+V146&data=50000&fromjd=2460435.08679&tojd=2461165.08679&csv=&band=V%2CVis.%2CCV%2CTG%2CB%2CR%2CI&mtype=std

## SIMBAD Context

- Status: `ok`
- Main ID: `LSPM J2010+5610`
- Object type: `SB*`
- Match separation: `0.026` arcsec
- Search: https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=302.692260+56.178890&Radius=5.0&Radius.unit=arcsec
- Other IDs: `TIC 233751709`, `AP J20104613+5610440`, `Gaia DR3 2186285245845919360`, `TYC 3940-923-1`, `ASCC  207516`, `2MASS J20104613+5610440`, `USNO-B1.0 1461-00328922`, `LSPM J2010+5610`

## Gaia DR3 Context

- Status: `ok`
- Source ID: `2186285245845919360`
- G magnitude: `10.015`
- BP-RP color: `1.846`
- Parallax: `29.328` +/- `0.012` mas
- RUWE: `1.219`
- Gaia photometric variability flag: `not flagged`
- Match separation: `2.891` arcsec
- IPD multi-peak fraction: `0.000`
- **Color anomaly**: VSX type EA (short-period) but Gaia BP-RP=1.85 (expected <1.8)

## ZTF Enrichment

- Not requested for this run.

## Human Review Checklist

- Check VSX and SIMBAD for newer notes or duplicate names.
- Inspect DSS/Pan-STARRS imagery for crowding and bright nearby stars.
- Verify AAVSO comparison stars are available in the field.
- Decide cadence: single nightly point, weekly monitoring, or continuous time-series.
- Treat this as a follow-up candidate, not a discovery claim.
