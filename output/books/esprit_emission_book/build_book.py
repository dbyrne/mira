#!/usr/bin/env python
"""Esprit 120 emission-nebula 'image book' — single-frame framing previews.

For each curated emission target (HII / PN / SNR / WR bubble) that (a) is
emission-line and NB-suitable, (b) fits a single Esprit 120 frame
(1.60°×1.07° @ 840mm, APS-C), and (c) is observable from Jersey City this
summer/fall, this:
  - resolves exact J2000 coords via SIMBAD (fallback to curated coords),
  - computes max altitude from JC + approximate peak month,
  - fetches a DSS2 color image (fixed 2.0° field for comparability),
  - overlays the Esprit FOV box rotated to the suggested PA,
  - writes a framing PNG.
Then writes emission_book.md (the book) + emission_book.csv (index).

Run:  python output/books/esprit_emission_book/build_book.py
"""
import io, math, csv, traceback
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFont

OUT = Path("output/books/esprit_emission_book"); OUT.mkdir(parents=True, exist_ok=True)

# Ambiguous SIMBAD names: plain "Abell 21" resolves to the GALAXY CLUSTER
# (RA 0h20m, +28.7°), not the Medusa planetary — query the PN id instead.
SIMBAD_QUERY = {"Abell 21": "PN A66 21"}
LAT = 40.7178
FOV = 2.0; PX = 1000; PPD = PX / FOV
ESP_L = math.degrees(2*math.atan(23.5/2/840))   # 1.60° sensor long axis
ESP_S = math.degrees(2*math.atan(15.7/2/840))   # 1.07° sensor short axis

# Curated targets: id (SIMBAD query), common, const, type, maj', min', PA(maj-axis deg),
# palette, fallback RA/Dec (deg), note. PA = position angle of object major axis (N->E).
T = [
 ("NGC 6888","Crescent","Cyg","WR bubble",18,12,60,"SHO / HOO",303.00,38.35,"OIII shell + Ha; classic"),
 ("Sh2-101","Tulip","Cyg","HII",16,9,135,"SHO",301.57,35.27,"near Cyg X-1"),
 ("NGC 6960","Western Veil","Cyg","SNR",70,8,10,"HOO",311.40,30.72,"Witch's Broom / 52 Cyg; long thin"),
 ("NGC 6992","Eastern Veil","Cyg","SNR",60,8,200,"HOO",313.10,31.72,"Network; OIII-rich filament"),
 ("IC 5146","Cocoon","Cyg","HII+refl",12,12,0,"Ha / HOO",328.38,47.27,"small; emission core + dust"),
 ("IC 5070","Pelican","Cyg","HII",60,50,0,"SHO",313.40,44.37,"fits tight; pairs w/ NGC7000"),
 ("IC 1396A","Elephant's Trunk","Cep","HII",20,10,120,"SHO",324.74,57.50,"trunk only (full IC1396 too big)"),
 ("NGC 7380","Wizard","Cep","HII",25,20,0,"SHO",341.00,58.12,"open cluster + neb"),
 ("Sh2-155","Cave","Cep","HII",50,30,90,"SHO",343.49,62.62,"dark cave rim"),
 ("NGC 281","Pacman","Cas","HII",35,30,0,"SHO",13.20,56.62,"round; Bok globules"),
 ("NGC 7635","Bubble","Cas","HII",22,15,0,"SHO",350.20,61.20,"bubble + M52 nearby"),
 ("Sh2-157","Lobster Claw","Cas","HII",60,30,40,"SHO",345.40,61.50,"60' fits long axis"),
 ("NGC 6820","Sh2-86","Vul","HII",40,30,0,"SHO",295.80,23.10,"pillar + NGC6823 cluster"),
 ("M27","Dumbbell","Vul","PN",8,6,30,"HOO / SHO",299.90,22.72,"bright PN; OIII strong"),
 ("M57","Ring","Lyr","PN",1.4,1.0,0,"HOO",283.40,33.03,"tiny — better long-FL/cropped"),
 ("Sh2-132","Lion","Cep","HII",40,30,30,"SHO",335.00,56.10,"faint; SHO rewards it"),
 ("NGC 7822","Sh2-171","Cep","HII",60,60,0,"SHO",2.00,68.00,"fills frame; pillars"),
 ("IC 405","Flaming Star","Aur","HII+refl",37,19,30,"Ha / HOO",78.00,34.30,"late-fall rising; AE Aur"),
 ("IC 410","Tadpoles","Aur","HII",40,30,0,"SHO",80.20,33.40,"late-fall; tadpole globs"),
 ("NGC 2237","Rosette","Mon","HII",80,70,0,"SHO",97.95,4.95,"tight/slight overflow; late fall"),
 ("NGC 2264","Christmas Tree / Cone","Mon","HII",40,20,0,"SHO",100.25,9.90,"cluster + Cone; late fall"),
 ("IC 443","Jellyfish","Gem","SNR",50,40,140,"HOO",94.20,22.50,"SNR; fall/winter"),
 ("NGC 2174","Monkey Head","Ori","HII",40,30,0,"SHO",91.00,20.30,"fall/winter rising"),
 # --- WINTER (RA 05h-07h): Orion / Taurus / CMa / Gemini ---
 ("M42","Orion Nebula","Ori","HII",85,60,0,"HOO / SHO",83.82,-5.39,"very bright; tight in frame; +M43/Running Man"),
 ("NGC 2024","Flame","Ori","HII",30,30,0,"SHO",85.43,-1.91,"Alnitak glare; Horsehead in adjacent frame"),
 ("IC 434","Horsehead","Ori","HII",60,10,0,"Ha / SHO",85.24,-2.46,"B33 dark horse on the IC434 Ha strip"),
 ("M1","Crab","Tau","SNR",6,4,0,"HOO",83.63,22.01,"small bright SNR; filaments"),
 ("NGC 2359","Thor's Helmet","CMa","WR bubble",10,8,0,"HOO",109.42,-13.20,"low from JC; OIII bubble"),
 ("Abell 21","Medusa","Gem","PN",10,10,0,"HOO",112.30,13.25,"large faint PN; OIII-rich"),
]

def simbad_coord(qid, fb_ra, fb_dec):
    try:
        from astroquery.simbad import Simbad
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        r = Simbad.query_object(SIMBAD_QUERY.get(qid, qid))
        if r is None: return fb_ra, fb_dec, "fallback"
        row = r[0]
        racol = "ra" if "ra" in r.colnames else "RA"
        deccol = "dec" if "dec" in r.colnames else "DEC"
        val_ra, val_dec = row[racol], row[deccol]
        try:  # deg already?
            c = SkyCoord(float(val_ra)*u.deg, float(val_dec)*u.deg)
        except Exception:
            c = SkyCoord(str(val_ra), str(val_dec), unit=(u.hourangle, u.deg))
        return float(c.ra.deg), float(c.dec.deg), "SIMBAD"
    except Exception:
        return fb_ra, fb_dec, "fallback"

def peak_month(ra_deg):
    ra_h = ra_deg/15.0
    sun_ra = (ra_h - 12) % 24                 # sun RA when target transits midnight
    doy = (80 + sun_ra/24*365) % 365          # ~Mar21 = doy80 = sun RA 0h
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    return months[min(11, int(doy//30.4))]

def hms(ra_deg):
    h=ra_deg/15; m=(h-int(h))*60; s=(m-int(m))*60
    return f"{int(h):02d}h{int(m):02d}m{int(s):02d}s"
def dms(dec):
    sg="+" if dec>=0 else "-"; a=abs(dec); d=int(a); m=(a-d)*60
    return f"{sg}{d:02d}°{int(m):02d}'"

def fetch(ra, dec):
    url=("https://alasky.u-strasbg.fr/hips-image-services/hips2fits"
         f"?hips=CDS/P/DSS2/color&ra={ra}&dec={dec}&fov={FOV}&width={PX}&height={PX}"
         "&projection=TAN&format=jpg")
    return Image.open(io.BytesIO(requests.get(url,timeout=60).content)).convert("RGB")

def draw_box(img, pa, label, sub):
    d=ImageDraw.Draw(img); cx=cy=PX/2
    try: f=ImageFont.truetype("arial.ttf",22); fs=ImageFont.truetype("arial.ttf",17)
    except: f=fs=ImageFont.load_default()
    hl=ESP_L/2*PPD; hs=ESP_S/2*PPD; th=math.radians(pa)
    lu=(-math.sin(th),-math.cos(th)); su=(-math.cos(th),math.sin(th))
    corners=[]
    for a in (+hl,-hl):
        for b in ((+hs,-hs) if a>0 else (-hs,+hs)):
            corners.append((cx+a*lu[0]+b*su[0], cy+a*lu[1]+b*su[1]))
    for i in range(4):
        d.line([corners[i],corners[(i+1)%4]],fill=(255,230,0),width=3)
    d.text((10,8),label,fill=(255,255,255),font=f)
    d.text((10,32),sub,fill=(255,225,120),font=fs)
    # compass + scale
    d.line([PX-50,70,PX-50,35],fill=(255,255,255),width=2); d.text((PX-58,14),"N",fill=(255,255,255),font=fs)
    d.line([PX-50,70,PX-85,70],fill=(255,255,255),width=2); d.text((PX-104,60),"E",fill=(255,255,255),font=fs)
    d.line([20,PX-22,20+PPD*0.5,PX-22],fill=(255,255,255),width=3); d.text((20,PX-46),"30'",fill=(255,255,255),font=fs)
    return img

rows=[]
for qid,common,const,typ,maj,mn,pa,pal,fra,fdec,note in T:
    try:
        ra,dec,src=simbad_coord(qid,fra,fdec)
        maxalt=90-abs(LAT-dec)
        pk=peak_month(ra)
        fits_long = maj <= ESP_L*60*0.95
        fit = "fits" if (maj<=ESP_L*60*0.92 and mn<=ESP_S*60*0.92) else ("tight" if maj<=ESP_L*60 else "overflow")
        rot = f"PA {pa:03d}° (long axis)" if maj/max(mn,1) > 1.25 else "any (round)"
        slug=qid.replace(" ","_")
        img=fetch(ra,dec)
        sub=f"{typ} | {maj}'×{mn}' | {pal} | maxAlt {maxalt:.0f}° | peak {pk} | {fit}"
        draw_box(img, pa if "PA" in rot else 0, f"{qid}  ({common})  — {const}", sub)
        png=OUT/f"{slug}.png"; img.save(png)
        rows.append(dict(qid=qid,common=common,const=const,typ=typ,ra=ra,dec=dec,
            radm=hms(ra),decdm=dms(dec),maj=maj,min=mn,pa=pa,rot=rot,pal=pal,
            maxalt=round(maxalt),peak=pk,fit=fit,src=src,note=note,png=png.name))
        print(f"OK  {qid:<10} {common:<18} {src:<8} alt{maxalt:4.0f} {fit:<8} {pk}")
    except Exception as e:
        print(f"ERR {qid}: {e}"); traceback.print_exc()

# CSV
with open(OUT/"emission_book.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

# Markdown book
season_order={"Jun":0,"Jul":1,"Aug":2,"Sep":3,"Oct":4,"Nov":5,"Dec":6,"Jan":7,"Feb":8,
              "Mar":9,"Apr":10,"May":11}
rows.sort(key=lambda r:(season_order.get(r["peak"],99), -r["maxalt"]))
md=["# Esprit 120 — Emission Nebula Image Book (single-frame)",
 "",
 "Single-frame framing previews for **emission nebulae** (HII / planetary / SNR / WR) that fit one "
 f"Esprit 120 frame (**{ESP_L:.2f}°×{ESP_S:.2f}°**, 96'×64' @ 840mm, ASI2600MM) and are observable from "
 "Jersey City this **summer/fall**. Mosaics excluded by design — these are the objects that work as a "
 "single shot. Coordinates resolved via SIMBAD; yellow box = Esprit FOV at the suggested rotation; "
 "DSS2 color (Ha reads brown here — through your 3nm filters it's vivid red/SHO). Sorted by peak month.",
 "",
 "**Excluded as too low from JC (<35° / deep southern Milky Way):** Lagoon M8, Trifid M20, Eagle M16, "
 "Swan M17. **Excluded as too big for one frame (mosaic/wide-field):** North America NGC7000, "
 "Heart & Soul IC1805/1848, California NGC1499, full IC1396, Sh2-119 Clamshell.",
 "",
 "| Target | Common | Type | Size | Fit | Rotation | Palette | maxAlt(JC) | Peak |",
 "|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    md.append(f"| {r['qid']} | {r['common']} | {r['typ']} | {r['maj']}'×{r['min']}' | {r['fit']} | "
              f"{r['rot']} | {r['pal']} | {r['maxalt']}° | {r['peak']} |")
md.append("")
for r in rows:
    md += [f"## {r['qid']} — {r['common']}  ({r['const']})",
     "",
     f"![{r['qid']}]({r['png']})",
     "",
     f"- **Coords (J2000):** {r['radm']} {r['decdm']}  ({r['ra']:.3f}°, {r['dec']:.3f}°) — *{r['src']}*",
     f"- **Type / size:** {r['typ']}, {r['maj']}'×{r['min']}'  → **{r['fit']}** in the Esprit frame",
     f"- **Rotation:** {r['rot']}",
     f"- **Palette:** {r['pal']}",
     f"- **JC observability:** max altitude {r['maxalt']}°, peaks ~{r['peak']}",
     f"- **Note:** {r['note']}",
     ""]
(OUT/"emission_book.md").write_text("\n".join(md),encoding="utf-8")
print(f"\nWrote {len(rows)} targets -> {OUT}/emission_book.md + .csv + PNGs")
