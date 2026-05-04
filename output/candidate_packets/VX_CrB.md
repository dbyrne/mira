# VX CrB

Score: **79.0**

## Catalog

- VSX type: `RRAB`
- Coordinates: RA `240.01442`, Dec `34.97246`
- Catalog photometry: bright `14.120` CV; amplitude `1.090` mag CV
- Catalog amplitude: `1.090` mag
- Period: `0.51908280` days
- Spectral type: `blank`
- VSX: https://www.aavso.org/vsx/index.php?view=detail.top&oid=10641
- AAVSO finder chart: https://apps.aavso.org/vsp/photometry/?star=VX+CrB&type=chart&fov=900&maglimit=15&resolution=150&north=up&east=left

## Jersey City Observability

- Max altitude in configured window: `83.7 deg`
- Best single-night time above altitude floor: `240 min`
- Best window date: `2026-05-17`
- Best sampled local time: `2026-05-18T01:00:00-04:00`
- Galactic latitude: `49.2 deg`

## Observing Strategy

- Time-series follow-up: run continuously for 2-4 hours when the target is high, then compare the folded light curve against the VSX period.

## Why It Was Flagged

- max altitude 83.7 deg
- long nightly window
- catalog amplitude about 1.09 mag
- time-series candidate (0.5191 d)
- well away from Galactic plane (b=49.2 deg)
- sparse AAVSO coverage (0 recent observations)

## AAVSO Recent Coverage

- Status: `ok-cached`
- Recent observations: `0`
- JD range: `2460434.50-2461164.50`
- Note: used cached AAVSO response after live request failed: 405 Client Error: Not Allowed for url: https://vsx.aavso.org/index.php?view=api.object&ident=VX+CrB&data=50000&fromjd=2460434.50000&tojd=2461164.50000&csv=&band=V%2CVis.%2CCV%2CTG%2CB%2CR%2CI&mtype=std

## SIMBAD Context

- Status: `ok`
- Main ID: `V* VX CrB`
- Object type: `RR*`
- Match separation: `0.010` arcsec
- Search: https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=240.014420+34.972460&Radius=5.0&Radius.unit=arcsec
- Other IDs: `TIC 458490426`, `ATO J240.0143+34.9724`, `ZTF J160003.44+345820.9`, `Gaia DR3 1372000918724474240`, `NSVS   7847696`, `Antipin V22`, `GSC 02576-00466`, `V* VX CrB`

## Gaia DR3 Context

- Status: `ok`
- Source ID: `1372000918724474240`
- G mag: `14.066`
- BP-RP: `0.628`
- Parallax: `0.200` mas
- Parallax error: `0.018` mas
- RUWE: `1.410`
- Absolute G estimate: `0.566`
- Match separation: `0.143` arcsec
- VizieR query: https://vizier.cds.unistra.fr/viz-bin/asu-tsv?-source=I%2F355%2Fgaiadr3&-out=Source%2CRA_ICRS%2CDE_ICRS%2CGmag%2CBP-RP%2CPlx%2Ce_Plx%2CRUWE&-c=240.014420+34.972460&-c.rs=5.0

## ZTF Enrichment

- Not requested for this run.

## Human Review Checklist

- Check VSX and SIMBAD for newer notes or duplicate names.
- Inspect DSS/Pan-STARRS imagery for crowding and bright nearby stars.
- Verify AAVSO comparison stars are available in the field.
- Decide cadence: single nightly point, weekly monitoring, or continuous time-series.
- Treat this as a follow-up candidate, not a discovery claim.
