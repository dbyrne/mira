from PIL import Image, ImageDraw, ImageFont
import math

src = r'C:\Users\david\.claude\uploads\75ab5805-3b1b-4c22-a936-edbbab3a4381\5640422a-20260610_1458287734268268165941523.jpg'
im = Image.open(src).convert('RGB')
W, H = im.size
sx, sy = W/600.0, H/450.0
d = ImageDraw.Draw(im)

def font(sz):
    try:
        return ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf', int(sz))
    except Exception:
        return ImageFont.load_default()

YEL=(255,210,0); CYA=(0,220,255); WHT=(255,255,255); RED=(255,90,90)
FS = int(15*sx)

def P(x, y):
    return (x*sx, y*sy)

def arrow(p1, p2, color, w=None, head=True):
    w = w or max(4, int(3*sx))
    d.line([p1, p2], fill=color, width=w)
    if head:
        ang = math.atan2(p2[1]-p1[1], p2[0]-p1[0]); L = 10*sx
        for da in (-0.5, 0.5):
            d.line([p2, (p2[0]-L*math.cos(ang-da), p2[1]-L*math.sin(ang-da))], fill=color, width=w)

def dblarrow(p1, p2, color):
    arrow(p1, p2, color); arrow(p2, p1, color)

def label(xy, lines, color, fs=FS):
    f = font(fs); pad = int(5*sx); lh = int(fs*1.3)
    w = max(d.textlength(t, font=f) for t in lines)
    d.rectangle([xy[0]-pad, xy[1]-pad, xy[0]+w+pad, xy[1]+lh*len(lines)+pad],
                fill=(0,0,0), outline=color, width=max(2,int(2*sx)))
    for i, t in enumerate(lines):
        d.text((xy[0], xy[1]+i*lh), t, fill=color, font=f)

def circ(c, r, color, w=None):
    w = w or max(4, int(3*sx))
    d.ellipse([c[0]-r, c[1]-r, c[0]+r, c[1]+r], outline=color, width=w)

# washer+nut on the test screw
circ(P(307,222), 22*sx, RED)
label(P(14,8), ['Confirmed: 8.7mm = the standard M4 flat washer,',
                'barely wider than the nut corners (8.1mm).',
                'Over a ~8mm slot that is <0.5mm of grip per',
                'side -> off-center it pulls straight through.'], RED)
arrow(P(212,82), P(292,210), RED)

# slot + pocket width measurement marks
dblarrow(P(292,302), P(322,302), YEL)
label(P(338,290), ['slot width', '(caliper it; ~8mm)'], YEL, int(13*sx))
dblarrow(P(272,330), P(344,330), CYA)
label(P(360,330), ['pocket width', '(caliper it; ~18-19mm)'], CYA, int(13*sx))

label(P(14,366), ['Washer rule: OD >= slot + 4mm  AND  <= pocket - 2mm',
                  '-> M4 FENDER washer 12mm OD (ID 4.3, ~1mm thick).',
                  '15mm only if the pocket measures >= 17mm.'], WHT)

label(P(330,120), ['Good news: screw length',
                   'looks right (healthy tail',
                   'past the nut). Recess hides',
                   'some of the stack, but the',
                   'nut+tail still sit proud -',
                   'keep them off ring flats',
                   'and away from the dew shield.'], CYA, int(13*sx))

out = r'C:\mira\output\scratch\dplate_underside_annotated.png'
im.save(out)
print('saved', out, im.size)
