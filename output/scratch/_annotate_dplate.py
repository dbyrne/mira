from PIL import Image, ImageDraw, ImageFont
import math

src = r'C:\Users\david\.claude\uploads\75ab5805-3b1b-4c22-a936-edbbab3a4381\87bbc307-20260610_1443191090828249634901792.jpg'
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

def arrow(p1, p2, color, w=None):
    w = w or max(4, int(3*sx))
    d.line([p1, p2], fill=color, width=w)
    ang = math.atan2(p2[1]-p1[1], p2[0]-p1[0]); L = 12*sx
    for da in (-0.5, 0.5):
        d.line([p2, (p2[0]-L*math.cos(ang-da), p2[1]-L*math.sin(ang-da))], fill=color, width=w)

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

circ(P(262,243), 22*sx, YEL)          # 1/4-20 head, left end of slot
circ(P(352,207), 16*sx, RED)          # M4, right end of slot
d.rectangle([*P(238,196), *P(380,262)], outline=WHT, width=max(3,int(2*sx)))

label(P(14,8), ['SLOT = the shoe rail. A bare screw cannot mount',
                'here - nothing to thread into. The joint is a',
                'SANDWICH: head in shoe countersink -> shoe ->',
                'slot -> FENDER WASHER -> NYLOC NUT below.'], WHT)
arrow(P(200,92), P(284,198), WHT)

label(P(14,116), ['1/4-20: head spans the slot, but its real',
                  'job is PLATE -> RING TAPS. Thread-check',
                  'first: handle screws M6? -> use M6x16,',
                  'and the 1/4-20s stay in the bin.'], YEL)
arrow(P(238,162), P(259,228), YEL)

label(P(12,300), ['M4 "falls through" = expected (slot is wider',
                  'than its head). 12mm fender washer + nyloc',
                  'fixes it. Use BOTH M4s per shoe (32mm apart)',
                  '= no rotation. Stack wants M4 x20-25;',
                  'shoe-kit x8/x10 are too short.'], RED)
arrow(P(230,298), P(348,222), RED)

label(P(364,366), ['Fwd overhang: nuts/tails must',
                   'clear the DEW SHIELD below',
                   '(it slides!). Short tails there,',
                   'or put shoe behind the ring.'], CYA)

out = r'C:\mira\output\scratch\dplate_slot_annotated.png'
im.save(out)
print('saved', out, im.size)
