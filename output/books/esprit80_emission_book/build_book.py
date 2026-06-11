#!/usr/bin/env python
"""Esprit 80 ED emission-nebula 'image book' — single-frame framing previews.

Esprit 80 ED: 400mm f/5 + ASI2600MM Pro (23.5×15.7mm) -> 3.37°×2.25°
@ 1.94"/px, Antlia 3nm SHO (same camera train as the Esprit 120, swapped OTA).
The in-between book: it owns the medium-large complexes the 120 mosaics
(North America alone, Heart, Soul, Sh2-129, full IC 1396 tight, Rosette with
room) at twice the S30's sampling and true 3-filter SHO instead of dual-band
— and, unlike the S30's fixed frame, the camera ROTATES (manual, at setup),
so E-W-elongated giants (California, the Auriga pair) lay along the long
axis. Small targets (<25') are flagged '840mm territory' -> Esprit 120 book.

Per-target PA = suggested camera rotation (object major axis, N->E). Set it
at setup and confirm with a plate solve.

Run:  python output/books/esprit80_emission_book/build_book.py
"""
import io, math, csv, traceback
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFont

OUT = Path("output/books/esprit80_emission_book"); OUT.mkdir(parents=True, exist_ok=True)
LAT = 40.7178
FOV = 4.5; PX = 1000; PPD = PX / FOV
E80_L = math.degrees(2*math.atan(23.5/2/400))   # 3.37° sensor long axis
E80_S = math.degrees(2*math.atan(15.7/2/400))   # 2.25° sensor short axis
LMAX = E80_L*60                                  # 202'
SMAX = E80_S*60                                  # 135'

# Ambiguous SIMBAD names: plain "Abell 21" resolves to the GALAXY CLUSTER
# (RA 0h20m, +28.7°), not the Medusa planetary — query the PN id instead.
SIMBAD_QUERY = {"Abell 21": "PN A66 21"}

# id (SIMBAD), common, const, type, maj', min', PA(maj-axis deg), palette,
# fallback RA/Dec (deg), note.
T = [
 # --- SUMMER (Cyg / Cep / Cas / Vul) ---
 ("NGC 7000","North America","Cyg","HII",120,100,0,"SHO",314.75,44.30,"NA alone fits with room (mosaic on the 120); +Pelican combo ~2.2°+ E-W = S30 or 2-panel"),
 ("IC 5070","Pelican","Cyg","HII",60,50,0,"SHO",313.40,44.37,"own frame with context (tight on the 120)"),
 ("NGC 6960","Western Veil","Cyg","SNR",70,8,10,"HOO",311.40,30.72,"Witch's Broom + Pickering's with room the 120 can't give; full loop = 2-panel on this rig"),
 ("NGC 6992","Eastern Veil","Cyg","SNR",60,8,200,"HOO",313.10,31.72,"Network + Bat in one frame"),
 ("Sh2-119","Clamshell","Cyg","HII",90,90,0,"Ha / HOO",319.62,43.93,"whole shell + 68 Cyg, with field"),
 ("Sh2-101","Tulip","Cyg","HII",16,9,135,"SHO",301.57,35.27,"840mm territory; ok as a Cyg X-1 wide-context frame"),
 ("NGC 6888","Crescent","Cyg","WR bubble",18,12,60,"SHO / HOO",303.00,38.35,"840mm territory (existing data is from the 120)"),
 ("IC 5146","Cocoon (+B168)","Cyg","HII+refl",12,12,105,"Ha / HOO",328.38,47.27,"nebula is small, but at PA~105 the B168 dark river (~1.5°) makes the frame"),
 ("IC 1396","Elephant's Trunk (full)","Cep","HII",170,140,0,"SHO",324.74,57.50,"tight: 140' across vs 135' short axis — rim kiss; mu Cep + trunk + full shell"),
 ("Sh2-129","Flying Bat (+OU4 Squid)","Cep","HII",150,120,0,"HOO",317.80,59.40,"Bat+Squid fit together; the OIII Squid is dark-site-deep"),
 ("NGC 7380","Wizard","Cep","HII",25,20,0,"SHO",341.00,58.12,"fits with generous field"),
 ("Sh2-155","Cave","Cep","HII",50,30,90,"SHO",343.49,62.62,"comfortable, dark rim + field"),
 ("Sh2-132","Lion","Cep","HII",40,30,30,"SHO",335.00,56.10,"faint; SHO rewards it"),
 ("NGC 7822","Ced 214 / Sh2-171","Cep","HII",90,60,90,"SHO",2.00,68.00,"whole complex + Berkeley 59; circumpolar"),
 ("NGC 281","Pacman","Cas","HII",35,30,0,"SHO",13.20,56.62,"round; Bok globules"),
 ("NGC 7635","Bubble (+M52)","Cas","HII",22,15,0,"SHO",350.20,61.20,"840mm feature; or shoot it inside the Sh2-157 combo below"),
 ("Sh2-157","Lobster Claw (+Bubble)","Cas","HII",90,60,40,"SHO",345.40,61.50,"claw fits easily; claw+Bubble combo is razor-tight at PA~90 — test frame; M52 won't make it"),
 ("NGC 6820","Sh2-86","Vul","HII",40,30,0,"SHO",295.80,23.10,"pillar + NGC6823 cluster"),
 ("M27","Dumbbell","Vul","PN",8,6,30,"HOO / SHO",299.90,22.72,"840mm/long-FL territory"),
 # --- FALL / WINTER (Cas / Per / Aur / Mon / Ori / Gem / Tau / CMa) ---
 ("IC 1805","Heart","Cas","HII",100,90,0,"SHO",38.20,61.50,"Heart alone with room (overflows the 120); Heart+Soul pair ~5° = 2-panel"),
 ("IC 1848","Soul","Cas","HII",60,40,90,"SHO",42.70,60.40,"fits; natural 2-panel partner with Heart"),
 ("NGC 1499","California","Per","HII",145,40,100,"Ha / SHO",60.00,36.40,"THE rotation win: PA~100 lays the 145' ribbon along the 3.37° axis — overflows the S30's fixed frame, mosaic on the 120"),
 ("IC 405","Flaming Star","Aur","HII+refl",37,19,30,"Ha / HOO",78.00,34.30,"or frame the IC405+IC410 pair: ~2.7° span at PA~115 fits this rig only"),
 ("IC 410","Tadpoles","Aur","HII",40,30,0,"SHO",80.20,33.40,"pairs with IC 405 in one frame at PA~115"),
 ("NGC 2237","Rosette","Mon","HII",80,70,0,"SHO",97.95,4.95,"fits with room (tight on the 120); low from JC"),
 ("NGC 2264","Christmas Tree / Cone","Mon","HII",40,20,0,"SHO",100.25,9.90,"Cone + Fox Fur + cluster"),
 ("IC 443","Jellyfish","Gem","SNR",50,40,140,"HOO",94.20,22.50,"+IC 444 context in frame"),
 ("NGC 2174","Monkey Head","Ori","HII",40,30,0,"SHO",91.00,20.30,"fall/winter"),
 ("M42","Orion Nebula (+Running Man)","Ori","HII",90,60,0,"HOO / SHO",83.82,-5.39,"whole sword fits; HDR the core"),
 ("IC 434","Belt: Flame+Horsehead","Ori","HII",90,60,0,"Ha / SHO",85.24,-2.46,"Alnitak + Flame + Horsehead strip in one"),
 ("IC 2177","Seagull","CMa","HII",150,50,0,"Ha / HOO",105.50,-10.70,"150' wingspan along the long axis; low from JC (~39°)"),
 ("M1","Crab","Tau","SNR",6,4,0,"HOO",83.63,22.01,"840mm/long-FL territory"),
 ("NGC 2359","Thor's Helmet","CMa","WR bubble",10,8,0,"HOO",109.42,-13.20,"840mm territory + low from JC"),
 ("Abell 21","Medusa","Gem","PN",10,10,0,"HOO",112.30,13.25,"840mm territory; large faint OIII PN"),
]

def simbad_coord(qid, fra, fdec):
    try:
        from astroquery.simbad import Simbad
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        r = Simbad.query_object(SIMBAD_QUERY.get(qid, qid))
        if r is None: return fra, fdec, "fallback"
        row = r[0]
        rc = "ra" if "ra" in r.colnames else "RA"
        dc = "dec" if "dec" in r.colnames else "DEC"
        try:
            c = SkyCoord(float(row[rc])*u.deg, float(row[dc])*u.deg)
        except Exception:
            c = SkyCoord(str(row[rc]), str(row[dc]), unit=(u.hourangle, u.deg))
        return float(c.ra.deg), float(c.dec.deg), "SIMBAD"
    except Exception:
        return fra, fdec, "fallback"

def peak_month(ra_deg):
    sun_ra=(ra_deg/15-12)%24; doy=(80+sun_ra/24*365)%365
    return ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][min(11,int(doy//30.4))]
def hms(r): h=r/15;m=(h%1)*60;s=(m%1)*60; return f"{int(h):02d}h{int(m):02d}m{int(s):02d}s"
def dms(d): sg="+" if d>=0 else "-";a=abs(d);return f"{sg}{int(a):02d}°{int((a%1)*60):02d}'"

def fetch(ra,dec):
    url=("https://alasky.u-strasbg.fr/hips-image-services/hips2fits"
         f"?hips=CDS/P/DSS2/color&ra={ra}&dec={dec}&fov={FOV}&width={PX}&height={PX}"
         "&projection=TAN&format=jpg")
    return Image.open(io.BytesIO(requests.get(url,timeout=60).content)).convert("RGB")

def draw_box(img, pa, label, sub):
    d=ImageDraw.Draw(img); cx=cy=PX/2
    try: f=ImageFont.truetype("arial.ttf",22); fs=ImageFont.truetype("arial.ttf",17)
    except: f=fs=ImageFont.load_default()
    hl=E80_L/2*PPD; hs=E80_S/2*PPD; th=math.radians(pa)
    lu=(-math.sin(th),-math.cos(th)); su=(-math.cos(th),math.sin(th))
    corners=[]
    for a in (+hl,-hl):
        for b in ((+hs,-hs) if a>0 else (-hs,+hs)):
            corners.append((cx+a*lu[0]+b*su[0], cy+a*lu[1]+b*su[1]))
    for i in range(4):
        d.line([corners[i],corners[(i+1)%4]],fill=(120,255,120),width=3)
    d.text((10,8),label,fill=(255,255,255),font=f)
    d.text((10,32),sub,fill=(180,255,180),font=fs)
    d.line([PX-50,70,PX-50,35],fill=(255,255,255),width=2); d.text((PX-58,14),"N",fill=(255,255,255),font=fs)
    d.line([PX-50,70,PX-85,70],fill=(255,255,255),width=2); d.text((PX-104,60),"E",fill=(255,255,255),font=fs)
    d.line([20,PX-22,20+PPD,PX-22],fill=(255,255,255),width=3); d.text((20,PX-46),"1°",fill=(255,255,255),font=fs)
    return img

def classify(maj,mn):
    if maj<25: return "small"
    if maj<=0.92*LMAX and mn<=0.92*SMAX: return "fits"
    if maj<=LMAX and mn<=SMAX*1.10: return "tight"   # rim kiss, planner-tolerance territory
    return "overflow"

rows=[]
for qid,common,const,typ,maj,mn,pa,pal,fra,fdec,note in T:
    try:
        ra,dec,src=simbad_coord(qid,fra,fdec)
        maxalt=90-abs(LAT-dec); pk=peak_month(ra); fit=classify(maj,mn)
        rot = f"PA {pa:03d}° (long axis)" if maj/max(mn,1) > 1.25 else "any (round)"
        img=fetch(ra,dec)
        sub=f"{typ} | {maj}'×{mn}' | {pal} | maxAlt {maxalt:.0f}° | peak {pk} | {fit}"
        draw_box(img, pa if "PA" in rot else 0, f"{qid}  ({common})  — {const}", sub)
        slug=qid.replace(" ","_"); png=OUT/f"{slug}.png"; img.save(png)
        rows.append(dict(qid=qid,common=common,const=const,typ=typ,ra=round(ra,3),dec=round(dec,3),
            radm=hms(ra),decdm=dms(dec),maj=maj,min=mn,pa=pa,rot=rot,pal=pal,
            maxalt=round(maxalt),peak=pk,fit=fit,src=src,note=note,png=png.name))
        print(f"OK  {qid:<10} {common:<26} {src:<8} alt{maxalt:4.0f} {fit:<9} {pk}")
    except Exception as e:
        print(f"ERR {qid}: {e}"); traceback.print_exc()

with open(OUT/"emission_book.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

season_order={"Jun":0,"Jul":1,"Aug":2,"Sep":3,"Oct":4,"Nov":5,"Dec":6,"Jan":7,"Feb":8,
              "Mar":9,"Apr":10,"May":11}
rows.sort(key=lambda r:(season_order.get(r["peak"],99), -r["maxalt"]))
md=["# Esprit 80 ED — Emission Nebula Image Book (single-frame)",
 "",
 f"Single-frame framing previews for **emission nebulae** that suit the Esprit 80 ED + ASI2600MM Pro "
 f"(**{E80_L:.2f}°×{E80_S:.2f}°** @ 1.94\"/px, 400mm f/5, **Antlia 3nm SHO** — the Esprit 120's camera "
 "train on the second OTA) from Jersey City. This is the **in-between book**: it owns the medium-large "
 "complexes the 120 must mosaic (North America alone, Heart, Soul, California, Sh2-129, full IC 1396, "
 "Rosette-with-room) at **2× the S30's sampling** and with true 3-filter SHO instead of dual-band. "
 "Unlike the S30's fixed frame, the **camera rotates** (manually, at setup) — so E–W-elongated giants "
 "(California, the IC 405+410 pair, the Belt) lay their long axis along the frame. Suggested **PA** per "
 "target below; set at setup, confirm with a plate solve.",
 "",
 "**Small targets (<25') are flagged** — those are 840mm features (Esprit 120 book). "
 "**Excluded as too low from JC:** Lagoon M8, Trifid M20, Eagle M16, Swan M17. "
 "**Excluded as overflow even here:** full Cygnus Loop, IC 1318 Sadr, Simeis 147, Heart+Soul pair, "
 "NGC 7000+Pelican combo — the round ~3° giants stay S30-crop or **2-panel mosaic** territory "
 "(the `output/trips/catskills_jun20/mosaic_veil.py` reproject+coadd pattern works for any of them). "
 "Box = green; DSS2 color (Ha reads brown here — through 3nm filters it's vivid SHO).",
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
     f"- **Coords (J2000):** {r['radm']} {r['decdm']}  ({r['ra']}°, {r['dec']}°) — *{r['src']}*",
     f"- **Type / size:** {r['typ']}, {r['maj']}'×{r['min']}'  → **{r['fit']}** in the Esprit 80 frame",
     f"- **Rotation:** {r['rot']}",
     f"- **Palette:** {r['pal']}",
     f"- **JC observability:** max altitude {r['maxalt']}°, peaks ~{r['peak']}",
     f"- **Note:** {r['note']}",
     ""]
(OUT/"emission_book.md").write_text("\n".join(md),encoding="utf-8")
print(f"\nWrote {len(rows)} targets -> {OUT}/emission_book.md + .csv + PNGs")
