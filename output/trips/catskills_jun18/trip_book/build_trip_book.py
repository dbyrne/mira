#!/usr/bin/env python
"""Catskills dark-site trip book — S30 Pro + Esprit 80 combined.

One book for the one night: every candidate gets a single DSS framing chart
with BOTH rig footprints drawn (cyan = S30 3.91x2.20 fixed ~N-S; green =
Esprit 80 3.37x2.25 at the suggested PA), June-13 altitude tracks, per-rig
filter/sub recommendations, and — where one exists — the famous JWST/Hubble
image of the object (downloaded once, credited, linked).

Run:  python output/trips/catskills_jun18/trip_book/build_trip_book.py
Needs internet (hips2fits + esahubble/esawebb CDNs); astropy for altitudes.
"""
import io, math, csv
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFont

OUT = Path("output/trips/catskills_jun18/trip_book"); OUT.mkdir(parents=True, exist_ok=True)
LAT, LON = 42.1, -74.4                      # Catskills
FOV = 5.5; PX = 1100; PPD = PX / FOV
S30 = (3.91, 2.20, 4.0)                     # long, short, fixed tilt (~N-S)
E80 = (3.37, 2.25)                          # long, short; PA per target
CYA = (0, 225, 255); GRN = (120, 255, 120); WHT = (255, 255, 255); YEL = (255, 210, 0)

HST = "https://cdn.esahubble.org/archives/images/screen/{0}.jpg"
JWST = "https://cdn.esawebb.org/archives/images/screen/{0}.jpg"
HPAGE = "https://esahubble.org/images/{0}/"
WPAGE = "https://esawebb.org/images/{0}/"

# (slug, name, common, chart RA, chart Dec, size, window, e80_pa,
#  s30 rec, e80 rec, why-dark-site,
#  [(label, id, url_tmpl, page_tmpl, credit)...], [(ra, dec, marklabel)...])
T = [
 ("m13","M13","Hercules Cluster",250.42,36.46,"20' GC","EARLY 22:50-00:30 (high at dusk, sinking W)",0,
  "IR broadband, 30-60s","L (or LRGB), 60s — hold the core with GHS, not saturation",
  "resolved stars to the core; a dark sky doubles the outskirts",
  [("Hubble","opo0840a",HST,HPAGE,"NASA, ESA, and the Hubble Heritage Team (STScI/AURA)")],[]),
 ("m101","M101","Pinwheel Galaxy",210.80,54.35,"29' face-on galaxy","EARLY 22:50-00:30 (the plan's Esprit early block)",0,
  "IR broadband (low SB — dark site only)","LRGB — the official plan-v2 early alternate",
  "the canonical dark-site-only galaxy: mean SB ~23.9, invisible from JC",
  [("Hubble","heic0602a",HST,HPAGE,"NASA, ESA, K. Kuntz (JHU), F. Bresolin (U. Hawaii), J. Trauger (JPL), J. Mould (NOAO), Y.-H. Chu (U. Illinois), and STScI")],[]),
 ("m51","M51","Whirlpool Galaxy",202.47,47.20,"11'x7' galaxy pair","EARLY 22:50-00:00 (sinking NW)",0,
  "IR broadband (deep JC data exists — only the tidal halo is new)","LRGB if M101 is taken",
  "the faint tidal debris around the pair is dark-sky-only",
  [("JWST","potm2308a",JWST,WPAGE,"ESA/Webb, NASA & CSA, A. Adamo (Stockholm University) and the FEAST JWST team"),
   ("Hubble","heic0506a",HST,HPAGE,"NASA, ESA, S. Beckwith (STScI), and the Hubble Heritage Team (STScI/AURA)")],[]),
 ("m57","M57","Ring Nebula",283.40,33.03,"1.4' PN","QUICK GRAB after 23:00 (climbing all night)",0,
  "dot at 3.66\"/px — skip or 15min novelty","~85px at 1.94\"/px — quick HOO snack, not a main course",
  "honestly? small on both rigs. The Webb/Hubble frames below are the show",
  [("JWST","weic2320a",JWST,WPAGE,"ESA/Webb, NASA, CSA, M. Barlow (UCL), N. Cox (ACRI-ST), R. Wesson (Cardiff University)"),
   ("Hubble","heic1310a",HST,HPAGE,"NASA, ESA, and the Hubble Heritage Team (STScI/AURA)")],[]),
 ("ic1396","IC 1396","Elephant Trunk (full shell)",324.78,57.50,"170'x140' HII","ALL NIGHT (33° at dark -> 65° at 03:00) — S30 PRIMARY",0,
  "PRIMARY: LP 60s (test 120s), full moonless window","tight at PA 0 (rim kiss) — the SHO version is a JC project, save dark time",
  "LP from a dark site digs the dark lanes + rim shocks JC mush flattens",
  [],[(324.05,57.49,"Trunk"),(325.877,58.78,"mu Cep")]),
 ("iris","NGC 7023","Iris + vdB 141 Ghost",317.25,68.20,"frame pairs the Iris with the Ghost 1.4° E","ALL NIGHT (38° -> 61°, no flip) — ESPRIT 80 PRIMARY",90,
  "IR broadband: the whole dusty field, small scale","PRIMARY: LRGB — RGB 22:50-00:50, L 00:50-03:05 (plan v2)",
  "reflection nebula + LDN dust: THE thing Bortle-9 can never show you",
  [("Hubble","heic0915a",HST,HPAGE,"NASA & ESA")],[(315.40,68.163,"Iris"),(319.11,68.265,"Ghost")]),
 ("ngc7000_pelican","NGC 7000","North America + Pelican",314.10,44.35,"combo ~2.2° E-W","ALL NIGHT riser (43° at 00:00 -> 74°+)",0,
  "combo in ONE frame — spans ~2.2° E-W = exactly the frame, center carefully","green box = NA alone (the combo overflows the 80)",
  "LP makes it work even in JC — at a dark site the Ha goes 3-D; good S30 plan-B",
  [],[(314.75,44.30,"NGC 7000"),(313.40,44.37,"Pelican")]),
 ("veil_west","NGC 6960","Western Veil (Witch's Broom)",311.40,30.72,"70'x8' SNR filament","RISER 00:00+ (53° at 01:00, climbing)",10,
  "single frame, LP — or revive the shelved 2-panel full-loop kit","HOO: ~1.5h Ha + 1.5h OIII fits the window",
  "OIII filaments are urban-LP's first casualty; dark sky doubles the lacework",
  [("Hubble","heic1520a",HST,HPAGE,"NASA, ESA, and the Hubble Heritage Team (STScI/AURA)")],[(311.40,30.72,"52 Cyg")]),
 ("ngc6888","NGC 6888","Crescent Nebula",303.00,38.35,"18'x12' WR bubble","ALL NIGHT (high in Cygnus)",60,
  "small — context frame only","HOO/SHO — you HAVE JC data; dark site adds the faint OIII envelope",
  "the soap-bubble OIII shell around the crescent is the dark-site prize",
  [("Hubble","opo0023a",HST,HPAGE,"NASA, B. D. Moore and J. J. Hester (Arizona State University)")],[]),
 ("cocoon_b168","IC 5146","Cocoon + B168 dark river",327.60,47.40,"12' neb + 1.5° dark lane","RISER 00:30+ (45° at 01:00)",105,
  "IR broadband — LP would erase the dark river","LRGB at PA~105: the river flows along the long axis",
  "B168 is a *dark* nebula — it only exists against a dark-site star field",
  [],[(328.38,47.27,"Cocoon")]),
 ("squid","Sh2-129","Flying Bat + OU4 Squid",317.95,59.95,"150'x120' (Squid ~60')","ALL NIGHT (Cepheus, circumpolar)",0,
  "LP long stare — SAMPLE it (the real Squid wants 6h+ of OIII)","OIII-only if feeling brave",
  "OU4 is one of the faintest OIII objects amateurs image — dark site is table stakes",
  [],[]),
 ("fireworks","NGC 6946","Fireworks Galaxy + NGC 6939",308.30,60.40,"11' galaxy + open cluster","ALL NIGHT (circumpolar)",45,
  "IR broadband, both in frame","LRGB — galaxy + cluster pair composition",
  "low-SB face-on (SB~23) = dark-site-only; 10 SNe in a century",
  [("Hubble","potw2101a",HST,HPAGE,"ESA/Hubble & NASA")],[(308.72,60.15,"NGC 6946"),(307.90,60.65,"NGC 6939")]),
 ("m16_m17","M16 + M17","Eagle + Swan, ONE frame",274.95,-14.97,"pair spans ~2.9° N-S","SOUTH WINDOW 00:30-02:30 (peaks ~33°) — needs the southern horizon",0,
  "the killer frame: pair is N-S = made for the fixed long axis, LP","fits at PA 0 (2.9° vs 3.37°) if the S30 is on IC 1396",
  "the Pillars of Creation live inside your frame — see below what Webb sees there",
  [("JWST — the Pillars, inside M16","weic2216b",JWST,WPAGE,"NASA, ESA, CSA, STScI; J. DePasquale, A. Koekemoer, A. Pagan (STScI)"),
   ("Hubble — the Pillars","heic1501a",HST,HPAGE,"NASA, ESA, and the Hubble Heritage Team (STScI/AURA)")],
  [(274.70,-13.78,"M16"),(275.20,-16.17,"M17")]),
 ("m8_m20","M8 + M20","Lagoon + Trifid",270.75,-23.70,"pair 1.6° apart","SOUTH WINDOW ~00:30-01:30, VERY low (peaks ~23°) — horizon-permitting, 30-45min",20,
  "both in one frame, LP, brief","skip — airmass eats 1.94\"/px resolution",
  "a pure dark-site treat shot through 2.5 airmasses — manage expectations",
  [("Hubble — Lagoon core","heic1808a",HST,HPAGE,"NASA, ESA, STScI")],
  [(270.90,-24.38,"M8"),(270.62,-23.03,"M20")]),
 ("m27","M27","Dumbbell Nebula",299.90,22.72,"8'x6' PN","LATE 02:00-03:05 (transits ~70° at dawn-end)",30,
  "small","HOO quick hit — 250px across, bright, 30-45min is real data",
  "bright PN cores barely care about sky — but the faint outer shell does",
  [("Hubble","heic0301a",HST,HPAGE,"NASA and the Hubble Heritage Team (STScI/AURA)")],[]),
]


def font(sz):
    try:
        return ImageFont.truetype("arialbd.ttf", sz)
    except Exception:
        return ImageFont.load_default()


def fetch_dss(ra, dec):
    url = ("https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
           f"?hips=CDS/P/DSS2/color&ra={ra}&dec={dec}&fov={FOV}&width={PX}&height={PX}"
           "&projection=TAN&coordsys=icrs&format=jpg")
    return Image.open(io.BytesIO(requests.get(url, timeout=120).content)).convert("RGB")


def projector(ra0, dec0):
    a0, d0 = math.radians(ra0), math.radians(dec0)
    scale = PX / math.radians(FOV)

    def offs(ra, dec):
        a, d = math.radians(ra), math.radians(dec)
        cosc = math.sin(d0)*math.sin(d) + math.cos(d0)*math.cos(d)*math.cos(a - a0)
        xi = math.cos(d)*math.sin(a - a0)/cosc
        eta = (math.cos(d0)*math.sin(d) - math.sin(d0)*math.cos(d)*math.cos(a - a0))/cosc
        return math.degrees(xi), math.degrees(eta)        # deg E, deg N of center

    def to_px(de, dn):
        return PX/2 - math.radians(de)*scale, PX/2 - math.radians(dn)*scale

    return offs, to_px


def draw_fov(d, to_px, ce, cn, long_deg, short_deg, pa, color, width=4):
    th = math.radians(pa)
    pts = []
    for sl, ss in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        l, s = sl*long_deg/2, ss*short_deg/2
        # long axis points north at pa=0; rotate N->E by pa
        e = s*math.cos(th) + l*math.sin(th)
        n = -s*math.sin(th) + l*math.cos(th)
        pts.append(to_px(ce + e, cn + n))
    d.polygon(pts, outline=color, width=width)


def chart(t):
    slug, name, common, ra, dec, size, window, pa = t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7]
    img = fetch_dss(ra, dec)
    d = ImageDraw.Draw(img)
    offs, to_px = projector(ra, dec)
    # S30 fixed frame, centered on chart center
    draw_fov(d, to_px, 0, 0, S30[0], S30[1], S30[2], CYA)
    # E80 at suggested PA; NGC 7000 row centers the 80 on NA alone
    e80_c = offs(314.75, 44.30) if slug == "ngc7000_pelican" else (0, 0)
    draw_fov(d, to_px, e80_c[0], e80_c[1], E80[0], E80[1], pa, GRN)
    f, fs = font(26), font(19)
    d.text((12, 8), f"{name}  ({common})", fill=WHT, font=f)
    d.text((12, 42), f"{size}  |  cyan = S30 3.91°×2.20° fixed  |  green = Esprit 80 3.37°×2.25° @ PA {pa:03d}°",
           fill=(255, 235, 160), font=fs)
    for mra, mdec, ml in t[12]:
        x, y = to_px(*offs(mra, mdec))
        d.ellipse([x-10, y-10, x+10, y+10], outline=YEL, width=3)
        d.text((x+14, y-26), ml, fill=YEL, font=fs)
    d.line([PX-50, 76, PX-50, 40], fill=WHT, width=3); d.text((PX-58, 14), "N", fill=WHT, font=fs)
    d.line([PX-50, 76, PX-86, 76], fill=WHT, width=3); d.text((PX-108, 66), "E", fill=WHT, font=fs)
    d.line([20, PX-24, 20+PPD, PX-24], fill=WHT, width=4); d.text((20, PX-52), "1°", fill=WHT, font=fs)
    p = OUT / f"{slug}.png"; img.save(p)
    return p.name


def altitudes():
    """alt at 23:00 / 01:00 / 03:00 EDT for the night of Sat 2026-06-13."""
    import numpy as np
    from astropy.time import Time
    from astropy.coordinates import EarthLocation, AltAz, SkyCoord
    import astropy.units as u
    site = EarthLocation(lat=LAT*u.deg, lon=LON*u.deg, height=500*u.m)
    times = Time(["2026-06-14 03:00", "2026-06-14 05:00", "2026-06-14 07:00"])  # UT = EDT+4
    aa = AltAz(obstime=times, location=site)
    out = {}
    for t in T:
        c = SkyCoord(t[3]*u.deg, t[4]*u.deg)
        out[t[0]] = [round(float(a)) for a in c.transform_to(aa).alt.deg]
    return out


def get_space(slug, images):
    got = []
    for entry in images:
        lab, iid, tmpl, page, credit = entry
        fn = OUT / f"{slug}_{iid}.jpg"
        if not fn.exists():
            r = requests.get(tmpl.format(iid), timeout=120)
            r.raise_for_status()
            fn.write_bytes(r.content)
        got.append((lab, fn.name, page.format(iid), credit))
        print(f"  space: {fn.name}")
    return got


alts = altitudes()
rows = []
for t in T:
    print(t[1], "...")
    png = chart(t)
    space = get_space(t[0], t[11])
    rows.append(dict(slug=t[0], name=t[1], common=t[2], ra=t[3], dec=t[4], size=t[5],
                     window=t[6], pa=t[7], s30=t[8], e80=t[9], why=t[10],
                     alt=alts[t[0]], png=png, space=space))

with open(OUT / "trip_book.csv", "w", newline="", encoding="utf-8") as fcsv:
    w = csv.writer(fcsv)
    w.writerow(["name", "common", "ra", "dec", "size", "window", "alt23", "alt01", "alt03", "s30", "e80"])
    for r in rows:
        w.writerow([r["name"], r["common"], r["ra"], r["dec"], r["size"], r["window"],
                    *r["alt"], r["s30"], r["e80"]])

md = ["# Catskills dark-site trip book — S30 Pro + Esprit 80, one night, one menu",
 "",
 "Built for **Sat June 13, 2026** (astro dark 22:50→03:05 EDT, 2% moon below the horizon",
 "all night — see `../plan.md` for the committed primaries). Every chart carries **both**",
 "rig footprints: **cyan = S30 Pro** (3.91°×2.20° measured, fixed long axis ≈N–S),",
 "**green = Esprit 80 ED** (3.37°×2.25°, rotated to the suggested PA). Same sky, two",
 "instruments — pick per target, not per book.",
 "",
 "Where a famous **JWST / Hubble** frame of the object exists it's included for scale-awe:",
 "your wide field contains the whole object; Webb's contains a couple of light-years of it.",
 "Space images are NASA/ESA/CSA/STScI releases (CC BY 4.0), credited per image, linked to",
 "their release pages.",
 "",
 "| Target | What | Window | 23:00 | 01:00 | 03:00 | S30 Pro | Esprit 80 |",
 "|---|---|---|---|---|---|---|---|"]
for r in rows:
    md.append(f"| {r['name']} | {r['common']} | {r['window'].split('(')[0].strip()} | "
              f"{r['alt'][0]}° | {r['alt'][1]}° | {r['alt'][2]}° | {r['s30']} | {r['e80']} |")
md.append("")
for r in rows:
    md += [f"## {r['name']} — {r['common']}", "",
           f"![{r['name']}]({r['png']})", "",
           f"- **Center (J2000):** {r['ra']:.2f}°, {r['dec']:+.2f}°  |  **Size:** {r['size']}",
           f"- **Window:** {r['window']}  |  **Alt 23:00/01:00/03:00:** {r['alt'][0]}°/{r['alt'][1]}°/{r['alt'][2]}°",
           f"- **S30 Pro:** {r['s30']}",
           f"- **Esprit 80:** {r['e80']} (PA {r['pa']:03d}°)",
           f"- **Why at a dark site:** {r['why']}", ""]
    for lab, fn, page, credit in r["space"]:
        md += [f"**{lab}** ([release]({page})):", "", f"![{lab}]({fn})", "",
               f"*Credit: {credit}*", ""]
(OUT / "trip_book.md").write_text("\n".join(md), encoding="utf-8")
print(f"\nWrote {len(rows)} targets -> {OUT}/trip_book.md + .csv + charts + space images")
