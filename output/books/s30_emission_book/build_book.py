#!/usr/bin/env python
"""S30 Pro emission-nebula 'image book' — single-frame, wide-field.

S30 Pro: IMX585 OSC (11.14×6.26mm) at the MEASURED effective focal length —
plate solves consistently give 3.66"/px => eff. fl ≈ 163mm (not the nominal
150mm) => 3.91°×2.20°, LP dual-band (Ha+OIII). Wide FOV => this book features
the LARGE emission complexes (the ones the Esprit book excludes as mosaics)
plus medium targets, and flags small objects as 'Esprit territory'. Frame is
FIXED (long axis ≈ N-S, ~4° tilt, no rotator) so there's no per-target
rotation — E-W extents are judged against the SHORT 2.20° axis.

Run:  python output/books/s30_emission_book/build_book.py
"""
import io, math, csv, traceback
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFont

OUT = Path("output/books/s30_emission_book"); OUT.mkdir(parents=True, exist_ok=True)
LAT = 40.7178
FOV = 5.5; PX = 1000; PPD = PX / FOV
EFF_FL = 163.0                                    # measured: 3.66"/px plate scale
S30_L = math.degrees(2*math.atan(11.14/2/EFF_FL))  # 3.91° long (≈N-S)
S30_S = math.degrees(2*math.atan(6.26/2/EFF_FL))   # 2.20° short (≈E-W)
LMAX = S30_L*60                                    # 235'
SMAX = S30_S*60                                    # 132'

# id (SIMBAD), common, const, type, maj', min', palette, fb RA, fb Dec, note
T = [
 ("NGC 7000","North America (+Pelican)","Cyg","HII",120,100,"Ha+OIII",314.75,44.30,"NGC7000+IC5070 combo spans ~2.2° E-W = exactly the frame — center carefully (test frame first)"),
 ("Cygnus Loop","Veil (full loop)","Cyg","SNR",180,170,"HOO (OIII-rich)",312.50,30.90,"~3° wide E-W vs the 2.20° axis — full loop is a 2-panel RA split (trips/catskills_jun18 kit); one frame = the N-S height, E/W arcs clipped"),
 ("Sh2-119","Clamshell","Cyg","HII",90,90,"Ha+OIII",319.62,43.93,"fits whole; 68 Cyg"),
 ("IC 1318","Sadr / Butterfly","Cyg","HII",180,170,"Ha+OIII",305.55,40.25,"Gamma Cyg complex ~3° round — overflows the 2.20° E-W axis; crop the Butterfly or 2-panel"),
 ("IC 1396","Elephant's Trunk (full)","Cep","HII",170,140,"Ha+OIII",324.74,57.50,"full nebula + cluster + trunk"),
 ("IC 1805","Heart","Cas","HII",100,90,"Ha+OIII",38.20,61.50,"Heart alone (Heart+Soul pair ~5° overflows)"),
 ("IC 1848","Soul","Cas","HII",60,40,"Ha+OIII",42.70,60.40,"pairs with Heart"),
 ("NGC 1499","California","Per","HII",145,40,"Ha+OIII",60.00,36.40,"E-W elongated — OVERFLOWS the fixed 2.20° E-W axis by ~13'; clip the ends or use a rotatable rig (Esprit 80 book)"),
 ("IC 405","Flaming Star (+Tadpoles)","Aur","HII",150,120,"Ha+OIII",78.00,34.30,"IC405+IC410+IC417 Auriga trio; late-fall"),
 ("NGC 2237","Rosette","Mon","HII",80,70,"Ha+OIII",97.95,4.95,"fits well; low alt from JC; late fall"),
 ("Sh2-129","Flying Bat (Ou4 Squid)","Cep","HII",150,120,"HOO",317.80,59.40,"OIII Squid very faint — dark-site"),
 ("NGC 7822","Ced 214 / Sh2-171","Cep","HII",90,60,"Ha+OIII",0.50,67.50,"pillars; circumpolar"),
 ("Sh2-157","Lobster Claw (+M52/Bubble)","Cas","HII",90,60,"Ha+OIII",345.40,61.50,"rich wide field with NGC7635+M52"),
 ("Sh2-155","Cave","Cep","HII",50,30,"Ha+OIII",343.49,62.62,"fits comfortably"),
 ("Sh2-132","Lion","Cep","HII",40,30,"Ha+OIII",335.00,56.10,"faint"),
 ("Simeis 147","Spaghetti (Sh2-240)","Tau","SNR",180,180,"HOO",84.62,28.00,"huge faint SNR ~3° round — overflows E-W; dark-site only; late fall"),
 ("IC 443","Jellyfish","Gem","SNR",50,40,"HOO",94.20,22.50,"SNR; fall/winter"),
 ("NGC 2174","Monkey Head","Ori","HII",40,30,"Ha+OIII",91.00,20.30,"fall/winter"),
 ("NGC 2264","Christmas Tree / Cone","Mon","HII",40,20,"Ha+OIII",100.25,9.90,"cluster + Cone; late fall"),
 ("IC 5146","Cocoon (+B168 trail)","Cyg","HII",12,12,"Ha+OIII",328.38,47.27,"neb small but the dark trail fills the wide frame"),
 ("NGC 281","Pacman","Cas","HII",35,30,"Ha+OIII",13.20,56.62,"borderline small at 4\"/px"),
 ("NGC 6888","Crescent","Cyg","WR bubble",18,12,"HOO",303.00,38.35,"SMALL — better on Esprit; ok as IC1318 context"),
 ("Sh2-101","Tulip","Cyg","HII",16,9,"Ha+OIII",301.57,35.27,"SMALL — Esprit territory"),
 ("M27","Dumbbell","Vul","PN",8,6,"HOO",299.90,22.72,"SMALL/tiny — long-FL target"),
 # --- WINTER (RA 05h-07h): Orion / Taurus / CMa ---
 ("M42","Orion Nebula (+Running Man)","Ori","HII",90,60,"HOO",83.82,-5.39,"flagship winter; M42+M43+NGC1977 one frame"),
 ("IC 434","Belt: Flame+Horsehead","Ori","HII",90,60,"Ha+OIII",85.24,-2.46,"Alnitak/Flame/Horsehead region"),
 ("IC 2177","Seagull","CMa","HII",150,50,"Ha+OIII",105.50,-10.70,"low from JC (~39°); spans the wide frame"),
 ("NGC 2359","Thor's Helmet","CMa","WR bubble",10,8,"HOO",109.42,-13.20,"SMALL+low — Esprit/long-FL target"),
 ("M1","Crab","Tau","SNR",6,4,"HOO",83.63,22.01,"SMALL/tiny — long-FL target"),
]

def simbad_coord(qid, fra, fdec):
    try:
        from astroquery.simbad import Simbad
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        r = Simbad.query_object(qid)
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

def draw_box(img,label,sub):
    d=ImageDraw.Draw(img); cx=cy=PX/2
    try: f=ImageFont.truetype("arial.ttf",22); fs=ImageFont.truetype("arial.ttf",17)
    except: f=fs=ImageFont.load_default()
    w=S30_S*PPD; h=S30_L*PPD     # long axis vertical (N-S)
    d.rectangle([cx-w/2,cy-h/2,cx+w/2,cy+h/2],outline=(0,225,255),width=3)
    d.text((10,8),label,fill=(255,255,255),font=f)
    d.text((10,32),sub,fill=(150,235,255),font=fs)
    d.line([PX-50,70,PX-50,35],fill=(255,255,255),width=2); d.text((PX-58,14),"N",fill=(255,255,255),font=fs)
    d.line([PX-50,70,PX-85,70],fill=(255,255,255),width=2); d.text((PX-104,60),"E",fill=(255,255,255),font=fs)
    d.line([20,PX-22,20+PPD,PX-22],fill=(255,255,255),width=3); d.text((20,PX-46),"1°",fill=(255,255,255),font=fs)
    return img

def classify(maj,mn):
    if maj<40: return "small"
    if maj<=0.85*LMAX and mn<=0.9*SMAX: return "fits"
    if maj<=LMAX: return "tight"
    return "overflow"

rows=[]
for qid,common,const,typ,maj,mn,pal,fra,fdec,note in T:
    try:
        ra,dec,src=simbad_coord(qid,fra,fdec)
        maxalt=90-abs(LAT-dec); pk=peak_month(ra); fit=classify(maj,mn)
        # classify() assumes the object's long axis can ride the frame's long
        # (N-S) axis. These targets' E-W extent exceeds the fixed 2.20° (132')
        # short axis — California's 145' run E-W, and the ~3° round giants
        # overflow in every direction E-W — so they overflow regardless of
        # what classify() says about the N-S fit.
        if qid in ("NGC 1499","Cygnus Loop","IC 1318","Simeis 147"): fit="EW-overflow"
        img=fetch(ra,dec)
        sub=f"{typ} | {maj}'×{mn}' | LP {pal} | maxAlt {maxalt:.0f}° | peak {pk} | {fit}"
        draw_box(img,f"{qid}  ({common})  — {const}",sub)
        slug=qid.replace(" ","_"); png=OUT/f"{slug}.png"; img.save(png)
        rows.append(dict(qid=qid,common=common,const=const,typ=typ,radm=hms(ra),decdm=dms(dec),
            ra=round(ra,3),dec=round(dec,3),maj=maj,min=mn,pal=pal,maxalt=round(maxalt),
            peak=pk,fit=fit,src=src,note=note,png=png.name))
        print(f"OK  {qid:<13}{common:<26}{src:<8}alt{maxalt:4.0f} {fit:<8}{pk}")
    except Exception as e:
        print(f"ERR {qid}: {e}"); traceback.print_exc()

with open(OUT/"emission_book.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

so={"Jul":0,"Aug":1,"Sep":2,"Oct":3,"Nov":4,"Dec":5,"Jan":6}
rows.sort(key=lambda r:(so.get(r["peak"],9),-r["maxalt"]))
md=["# S30 Pro — Emission Nebula Image Book (single-frame, wide-field)","",
 f"Single-frame framing previews for **emission nebulae** that suit the ZWO Seestar S30 Pro "
 f"(**{S30_L:.2f}°×{S30_S:.2f}°** — the *measured* field, 3.66\"/px plate scale / eff. 163mm fl, "
 f"not the nominal-150mm 4.25°×2.39° — **LP dual-band Ha+OIII**) from Jersey City this "
 "**summer/fall**. The S30's wide field makes it the *complement* of the Esprit book: it owns the "
 "**large complexes** (North America+Pelican, full IC 1396, Heart, Clamshell, the Auriga trio) that "
 "overflow the Esprit, while **small targets** (Crescent, Tulip, M27) are flagged — those belong on "
 "the Esprit at 840mm. The ~3° round giants (full Veil, Sadr, Simeis 147) overflow even this frame's "
 "E–W axis — flagged **EW-overflow** below: crop, or 2-panel them in RA.",
 "",
 f"**Fixed frame:** the S30 has no rotator; the long ({S30_L:.2f}°) axis sits ≈**N–S** (~4° tilt). So framing "
 f"is choose-the-center only. **E–W-elongated targets (California, 145') overflow the narrower {S30_S:.2f}° axis** — "
 "clip the ends or hand them to a rotatable rig. Box = cyan; DSS2 color (Ha reads brown; through the LP it's red/teal HOO).",
 "",
 "| Target | Common | Type | Size | Fit | Palette | maxAlt(JC) | Peak |",
 "|---|---|---|---|---|---|---|---|"]
for r in rows:
    md.append(f"| {r['qid']} | {r['common']} | {r['typ']} | {r['maj']}'×{r['min']}' | {r['fit']} | "
              f"LP {r['pal']} | {r['maxalt']}° | {r['peak']} |")
md.append("")
for r in rows:
    md+=[f"## {r['qid']} — {r['common']}  ({r['const']})","",
     f"![{r['qid']}]({r['png']})","",
     f"- **Coords (J2000):** {r['radm']} {r['decdm']}  ({r['ra']}°, {r['dec']}°) — *{r['src']}*",
     f"- **Type / size:** {r['typ']}, {r['maj']}'×{r['min']}'  → **{r['fit']}** in the S30 frame",
     f"- **Palette:** LP dual-band ({r['pal']})",
     f"- **JC observability:** max altitude {r['maxalt']}°, peaks ~{r['peak']}",
     f"- **Note:** {r['note']}",""]
(OUT/"emission_book.md").write_text("\n".join(md),encoding="utf-8")
print(f"\nWrote {len(rows)} targets -> {OUT}/emission_book.md + .csv + PNGs")
