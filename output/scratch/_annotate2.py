from PIL import Image, ImageDraw, ImageFont
import math

src = r'C:\Users\david\.claude\uploads\ec9d3b9a-fcf5-454f-b43e-9a182933e0c4\92a70384-20260609_1142595227164848879987261.jpg'
im = Image.open(src).convert('RGB')
d = ImageDraw.Draw(im)

def font(sz):
    try:
        return ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf', sz)
    except Exception:
        return ImageFont.load_default()

YEL=(255,210,0); CYA=(0,225,255); GRN=(120,255,120); WHT=(255,255,255)

def arrow(p1,p2,color,w=16):
    d.line([p1,p2],fill=color,width=w)
    ang=math.atan2(p2[1]-p1[1],p2[0]-p1[0]); L=55
    for da in (-0.5,0.5):
        d.line([p2,(p2[0]-L*math.cos(ang-da),p2[1]-L*math.sin(ang-da))],fill=color,width=w)

def label(xy,lines,color,fs=58):
    f=font(fs); pad=18; lh=fs+12
    w=max(d.textlength(t,font=f) for t in lines)
    d.rectangle([xy[0]-pad,xy[1]-pad,xy[0]+w+pad,xy[1]+lh*len(lines)+pad],fill=(0,0,0),outline=color,width=8)
    for i,t in enumerate(lines):
        d.text((xy[0],xy[1]+i*lh),t,fill=color,font=f)

def circ(c,r,color,w=14):
    d.ellipse([c[0]-r,c[1]-r,c[0]+r,c[1]+r],outline=color,width=w)

# CYAN = device side: MeLE's wide holes + the bracket's wide slot banks (they mate)
d.rectangle([975,1190,1275,1985],outline=CYA,width=14)   # left slot bank
d.rectangle([1835,1190,2130,1985],outline=CYA,width=14)  # right slot bank
circ((2459,1590),95,CYA)   # MeLE hole L
circ((3421,1561),95,CYA)   # MeLE hole R
# double-headed span lines showing equal wide spacing
d.line([(1125,2030),(1980,2030)],fill=CYA,width=10)
d.line([(2459,2120),(3421,2120)],fill=CYA,width=10)

# YELLOW = rail side: the narrow center pedestal holes -> green plate
circ((1440,1322),85,YEL)
circ((1440,1682),85,YEL)

label((110,110),['(1) GREEN 355mm PLATE = the rail.'],GRN,58)
arrow((360,300),(560,1110),GRN)

label((1150,2240),['(2) NARROW center pair (~30mm) =','     the bracket-to-PLATE bolts.','     Bracket likely sits pedestal-DOWN:','     these bolt into the green plate,','     slots face UP for the MeLE.'],YEL,52)
arrow((1430,2210),(1440,1790),YEL)

label((780,70),['(3) WIDE slot banks (~80mm apart) = where the MeLE mounts.','     The slots slide so the bolts hit the MeLE holes exactly.'],CYA,52)
arrow((1150,360),(1125,1180),CYA)
arrow((1900,360),(1980,1180),CYA)

label((2520,110),['(4) MeLE base holes are the SAME','     wide ~80mm pair  ->  they line up','     with the slot banks in (3),','     NOT the center holes.'],CYA,52)
arrow((2900,470),(2900,1480),CYA)

label((2980,2620),['CYAN = MeLE <-> bracket (wide pair)','YELLOW = bracket <-> plate (narrow pair)'],WHT,46)

out=r'C:\mira\output\buckeye_mounting_v2.png'
im.save(out)
print('saved',out)
