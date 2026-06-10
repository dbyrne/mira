from PIL import Image, ImageDraw, ImageFont
import math

src = r'C:\Users\david\.claude\uploads\ec9d3b9a-fcf5-454f-b43e-9a182933e0c4\92a70384-20260609_1142595227164848879987261.jpg'
im = Image.open(src).convert('RGB')
d = ImageDraw.Draw(im)

def font(sz, bold=True):
    try:
        return ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf' if bold else r'C:\Windows\Fonts\arial.ttf', sz)
    except Exception:
        return ImageFont.load_default()

YEL=(255,210,0); CYA=(0,220,255); GRN=(120,255,120); WHT=(255,255,255)

def arrow(p1,p2,color,w=16):
    d.line([p1,p2],fill=color,width=w)
    ang=math.atan2(p2[1]-p1[1],p2[0]-p1[0]); L=55
    for da in (-0.5,0.5):
        d.line([p2,(p2[0]-L*math.cos(ang-da),p2[1]-L*math.sin(ang-da))],fill=color,width=w)

def label(xy,lines,color,fs=60):
    f=font(fs)
    pad=18; lh=fs+12
    w=max(d.textlength(t,font=f) for t in lines)
    box=[xy[0]-pad,xy[1]-pad,xy[0]+w+pad,xy[1]+lh*len(lines)+pad]
    d.rectangle(box,fill=(0,0,0),outline=color,width=8)
    for i,t in enumerate(lines):
        d.text((xy[0],xy[1]+i*lh),t,fill=color,font=f)

# CYAN: the two raised center holes = MeLE attaches here
for c in [(1440,1322),(1440,1682)]:
    d.ellipse([c[0]-95,c[1]-95,c[0]+95,c[1]+95],outline=CYA,width=14)
# YELLOW: the two side slot banks = bolt down to plate
d.rectangle([975,1190,1275,1985],outline=YEL,width=12)
d.rectangle([1835,1190,2130,1985],outline=YEL,width=12)

label((120,120),['(1) GREEN 355mm PLATE = the rail.','     The bottom layer. Everything','     ultimately bolts to THIS.'],GRN,60)
arrow((430,360),(610,1120),GRN)

label((1330,90),['(2) BRACKET BASE  ->  bolt DOWN','     here. Bolts drop through these','     yellow SIDE SLOTS into the','     plate. Use 2+  =  cannot rotate.'],YEL,60)
arrow((1450,560),(1120,1220),YEL)
arrow((1900,560),(1980,1220),YEL)

label((760,2230),['(3) These 2 RAISED CENTER HOLES face UP.','     They do NOT touch the plate ->','     the MeLE screws onto THESE.'],CYA,60)
arrow((1180,2210),(1440,1760),CYA)

label((2500,110),['(4) FLIP the MeLE over and screw its','     base onto (3). This silver face goes','     DOWN onto the bracket center pad.'],CYA,60)
arrow((2980,420),(2950,1120),CYA)

label((2950,2700),['YELLOW = bracket -> plate','CYAN = MeLE -> bracket'],WHT,50)

out=r'C:\mira\output\buckeye_mounting_annotated.png'
im.save(out)
print('saved',out, im.size)
