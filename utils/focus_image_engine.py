"""
FocusBeast Image Engine — Improved Design v3
5 themes. Auto-detects fonts (Windows / Linux / Pillow default).
No emojis. No external font files required.
"""

from PIL import Image, ImageDraw, ImageFont
import io, math
from dataclasses import dataclass
from typing import Tuple, Optional

# ── Font resolution ──────────────────────────────────────────────────────────
_BOLD = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]
_REG = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]

def _f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for p in (_BOLD if bold else _REG):
        try:
            return ImageFont.truetype(p, size)
        except:
            pass
    return ImageFont.load_default(size=size)

def _cx(draw, text: str, font, container_w: int, offset_x: int = 0) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return offset_x + (container_w - (bb[2] - bb[0])) // 2

def _lerp(a, b, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def _bytes(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ── 5 Themes ─────────────────────────────────────────────────────────────────
@dataclass
class Theme:
    name:          str
    label:         str
    discord_color: int
    bg:            Tuple[int,int,int]
    bg2:           Tuple[int,int,int]
    accent:        Tuple[int,int,int]   # primary highlight
    accent2:       Tuple[int,int,int]   # secondary highlight
    text:          Tuple[int,int,int]
    muted:         Tuple[int,int,int]
    panel:         Tuple[int,int,int]

THEMES = {
    "study": Theme("study","FOCUS MODE", 0x071131,
        (7,17,55),  (3,8,28),
        (255,255,255),(80,120,255),
        (255,255,255),(100,130,200),(11,22,70)),
    "lofi":  Theme("lofi", "LOFI BEATS", 0x160E26,
        (22,14,38), (10,6,20),
        (200,140,255),(140,80,220),
        (235,215,255),(150,120,190),(28,16,48)),
    "fire":  Theme("fire", "GRIND MODE", 0x1E0501,
        (30,8,2),   (14,3,1),
        (255,90,15),(200,50,0),
        (255,220,170),(180,100,50),(42,10,4)),
    "space": Theme("space","SPACE MODE", 0x020211,
        (4,4,22),   (2,2,12),
        (80,120,255),(40,80,200),
        (210,220,255),(120,140,220),(8,8,36)),
    "ocean": Theme("ocean","FLOW STATE", 0x020E1A,
        (4,18,42),  (2,8,22),
        (40,190,255),(0,140,220),
        (200,240,255),(90,170,210),(6,24,56)),
}

# ── Quotes ────────────────────────────────────────────────────────────────────
_QUOTES = [
    "The secret of getting ahead is getting started.",
    "Discipline is choosing what you want most over what you want now.",
    "Focus is the art of knowing what to ignore.",
    "The grind is the goal.",
    "One focused hour beats ten distracted ones.",
    "Consistency beats motivation. Show up anyway.",
    "Your future self is watching you right now.",
    "It always seems impossible until it is done.",
    "Work in silence. Let results speak.",
    "Champions train. Everyone else makes excuses.",
    "Today's effort is tomorrow's advantage.",
    "Push through. The other side is worth it.",
    "No shortcuts. Just reps.",
    "Build the habit. The results will follow.",
    "Make now count.",
    "The pain of discipline is less than the pain of regret.",
    "Stay in the room. Stay in the work.",
    "You are one session away from a breakthrough.",
    "Quiet the noise. Lock in.",
    "Every minute in that chair is a brick in the wall.",
]

def _quote(remaining: int, total: int) -> str:
    return _QUOTES[((total - remaining) // 180) % len(_QUOTES)]


# ── Rarity ────────────────────────────────────────────────────────────────────
RARITY_COLORS = {
    "common":    (160,160,160),
    "uncommon":  (60, 200, 80),
    "rare":      (80, 140,255),
    "legendary": (255,170, 20),
}
RARITY_LABELS = {
    "common":    "COMMON",
    "uncommon":  "UNCOMMON",
    "rare":      "RARE",
    "legendary": "LEGENDARY",
}

# ── Pet data ──────────────────────────────────────────────────────────────────
PIXEL_PETS = {
    "bunny":      {"rarity":"common",    "price":500,  "desc":"Soft and swift. Hops during your grind."},
    "fox":        {"rarity":"common",    "price":850,  "desc":"Clever and quick. Never misses a session."},
    "cat":        {"rarity":"common",    "price":1000,  "desc":"Mysterious and calm. Purrs at your focus."},
    "wolf":       {"rarity":"uncommon",  "price":1250,  "desc":"Loyal guardian. Howls at the moon for you."},
    "owl":        {"rarity":"uncommon",  "price":1850,  "desc":"Wise companion. Sharpens your focus aura."},
    "penguin":    {"rarity":"uncommon",  "price":3000,  "desc":"Chill vibes. Keeps you cool under pressure."},
    "dragon":     {"rarity":"rare",      "price":4500, "desc":"Ancient power. XP gains are doubled."},
    "unicorn":    {"rarity":"rare",      "price":6000, "desc":"Magical focus. Every session sparkles."},
    "phoenix":    {"rarity":"legendary", "price":8000, "desc":"Reborn from focus. The ultimate companion."},
    "galaxy_cat": {"rarity":"legendary", "price":10000, "desc":"Cosmic entity. Exists across all dimensions."},
}

_PET_BG = {
    "bunny":      ((28,18,10),(42,26,14)),
    "fox":        ((26,14,5), (40,20,8)),
    "cat":        ((18,14,24),(28,20,38)),
    "wolf":       ((10,12,20),(16,18,32)),
    "owl":        ((16,10,4), (26,16,6)),
    "penguin":    ((6,6,14),  (10,10,22)),
    "dragon":     ((4,18,8),  (8,28,12)),
    "unicorn":    ((20,8,26), (32,12,42)),
    "phoenix":    ((28,6,2),  (44,10,4)),
    "galaxy_cat": ((4,2,16),  (8,4,28)),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Pet artwork — geometric shapes, no emojis
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_pet(draw: ImageDraw.ImageDraw, species: str,
              ocx: int, ocy: int, size: int):
    s  = size / 100
    pt = lambda x,y: (int(ocx+x*s), int(ocy+y*s))
    el = lambda x,y,rx,ry: [int(ocx+(x-rx)*s),int(ocy+(y-ry)*s),
                             int(ocx+(x+rx)*s),int(ocy+(y+ry)*s)]
    w  = lambda v: max(1, int(v*s))
    fn = {"bunny":_pb,"fox":_pf,"cat":_pc,"wolf":_pw,"owl":_po,
          "penguin":_pg,"dragon":_pd,"unicorn":_pu,"phoenix":_pp,
          "galaxy_cat":_pgc}.get(species, _pc)
    fn(draw, pt, el, w)


def _pb(draw,pt,el,w):  # bunny
    C={"bd":(190,130,65),"dk":(130,85,38),"ol":(80,45,18),"ey":(20,12,5),"ns":(220,150,160),"by":(230,200,160),"ei":(230,160,170)}
    draw.ellipse(el(-28,-55,10,30),fill=C["dk"],outline=C["ol"],width=w(2))
    draw.ellipse(el(-28,-55,6,24), fill=C["ei"])
    draw.ellipse(el(22,-50,9,26),  fill=C["dk"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,28,42,38),   fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,32,26,26),   fill=C["by"])
    draw.ellipse(el(0,-14,34,30),  fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(-12,-18,7,7),  fill=C["ey"])
    draw.ellipse(el(-10,-20,2,2),  fill=(255,255,255))
    draw.ellipse(el(-2,-4,4,3),    fill=C["ns"])
    for ox,oy in [(-18,-2),(-22,0),(-18,2)]:
        draw.line([pt(ox,oy),pt(-6,oy)],fill=C["dk"],width=w(1.5))
    draw.ellipse(el(36,22,8,8),    fill=C["by"],outline=C["ol"],width=w(1.5))
    draw.ellipse(el(-20,58,18,10), fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(16,58,18,10),  fill=C["bd"],outline=C["ol"],width=w(2))


def _pf(draw,pt,el,w):  # fox
    C={"bd":(220,110,30),"lt":(245,165,70),"wh":(240,220,195),"dk":(140,60,10),"ol":(100,40,5),"ey":(30,15,5),"ns":(50,25,15)}
    draw.ellipse(el(40,30,28,42),  fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(52,28,16,16),  fill=(240,240,240))
    draw.ellipse(el(0,28,40,36),   fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,32,24,24),   fill=C["wh"])
    draw.polygon([pt(-22,-54),pt(-38,-28),pt(-8,-28)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(-22,-50),pt(-32,-32),pt(-12,-32)],fill=C["lt"])
    draw.polygon([pt(22,-54),pt(8,-28),pt(38,-28)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(22,-50),pt(12,-32),pt(32,-32)],fill=C["lt"])
    draw.ellipse(el(0,-16,33,28),  fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,-4,16,14),   fill=C["wh"])
    for ex in [-14,14]:
        draw.ellipse(el(ex,-22,6,6),  fill=C["ey"])
        draw.ellipse(el(ex-1,-24,2,2),fill=(255,255,255))
    draw.ellipse(el(0,2,5,4),      fill=C["ns"])
    for lx in [-18,14]:
        draw.ellipse(el(lx,60,12,10),fill=C["bd"],outline=C["ol"],width=w(2))


def _pc(draw,pt,el,w):  # cat
    C={"bd":(165,148,175),"lt":(200,185,212),"dk":(90,75,105),"ol":(55,42,68),"ey":(50,160,200),"pu":(15,10,20),"ns":(220,120,150),"st":(130,115,145)}
    draw.ellipse(el(0,28,40,36),   fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,30,26,26),   fill=C["lt"])
    draw.polygon([pt(-22,-52),pt(-36,-24),pt(-8,-24)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(-22,-46),pt(-30,-28),pt(-14,-28)],fill=C["lt"])
    draw.polygon([pt(22,-52),pt(8,-24),pt(36,-24)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(22,-46),pt(14,-28),pt(30,-28)],fill=C["lt"])
    draw.ellipse(el(0,-14,33,28),  fill=C["bd"],outline=C["ol"],width=w(2))
    for fy in [-28,-22,-16]:
        draw.line([pt(-8,fy),pt(8,fy)],fill=C["st"],width=w(2))
    for ex in [-13,13]:
        draw.ellipse(el(ex,-19,8,7),  fill=C["ey"])
        draw.ellipse(el(ex,-19,3,5),  fill=C["pu"])
        draw.ellipse(el(ex-4,-22,2,2),fill=(255,255,255))
    draw.polygon([pt(0,-4),pt(-4,1),pt(4,1)],fill=C["ns"])
    draw.line([pt(0,2),pt(-5,6)],fill=C["dk"],width=w(1.5))
    draw.line([pt(0,2),pt(5,6)], fill=C["dk"],width=w(1.5))
    for oy in [-2,2]:
        draw.line([pt(-8,oy),pt(-24,oy-2)],fill=C["dk"],width=w(1.2))
        draw.line([pt(8,oy), pt(24,oy-2)], fill=C["dk"],width=w(1.2))
    for lx in [-18,14]:
        draw.ellipse(el(lx,60,14,9),fill=C["bd"],outline=C["ol"],width=w(2))


def _pw(draw,pt,el,w):  # wolf
    C={"bd":(120,125,145),"lt":(170,175,195),"ol":(38,42,55),"ey":(60,120,210),"pu":(10,10,15),"ns":(40,40,50),"by":(220,220,230)}
    draw.ellipse(el(0,30,42,36),   fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,34,26,26),   fill=C["by"])
    draw.polygon([pt(-20,-54),pt(-36,-20),pt(-4,-20)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(-20,-48),pt(-30,-24),pt(-10,-24)],fill=C["lt"])
    draw.polygon([pt(20,-54),pt(4,-20),pt(36,-20)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(20,-48),pt(10,-24),pt(30,-24)],fill=C["lt"])
    draw.ellipse(el(0,-14,34,29),  fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,-2,18,13),   fill=C["lt"])
    for ex in [-14,14]:
        draw.ellipse(el(ex,-22,7,7),   fill=C["ey"])
        draw.ellipse(el(ex,-22,3,4),   fill=C["pu"])
        draw.ellipse(el(ex-2,-24,2,2), fill=(255,255,255))
    draw.ellipse(el(0,2,6,4),      fill=C["ns"])
    for lx in [-18,12]:
        draw.ellipse(el(lx,62,14,9),fill=C["bd"],outline=C["ol"],width=w(2))


def _po(draw,pt,el,w):  # owl
    C={"bd":(145,108,55),"lt":(195,158,90),"ol":(60,38,12),"er":(240,200,60),"ey":(20,15,5),"bk":(210,155,50),"by":(220,200,160),"wg":(110,80,35)}
    draw.ellipse(el(0,14,46,50),   fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,18,30,36),   fill=C["by"])
    draw.ellipse(el(-38,20,18,34), fill=C["wg"],outline=C["ol"],width=w(2))
    draw.ellipse(el(38,20,18,34),  fill=C["wg"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,-22,36,32),  fill=C["bd"],outline=C["ol"],width=w(2))
    draw.polygon([pt(-18,-50),pt(-30,-26),pt(-6,-26)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(18,-50),pt(6,-26),pt(30,-26)],fill=C["bd"],outline=C["ol"])
    for ex in [-14,14]:
        draw.ellipse(el(ex,-22,14,14),fill=C["er"])
        draw.ellipse(el(ex,-22,10,10),fill=C["ey"])
        draw.ellipse(el(ex-2,-24,3,3),fill=(255,255,255))
    draw.polygon([pt(-5,-6),pt(5,-6),pt(0,4)],fill=C["bk"])


def _pg(draw,pt,el,w):  # penguin
    C={"bd":(20,20,30),"by":(240,240,245),"bk":(255,190,50),"ft":(255,160,40),"ey":(255,255,255),"pu":(10,10,20),"sh":(50,50,80)}
    draw.ellipse(el(0,18,38,52),   fill=C["bd"],outline=C["sh"],width=w(2))
    draw.ellipse(el(0,16,24,40),   fill=C["by"])
    draw.ellipse(el(0,-26,30,28),  fill=C["bd"],outline=C["sh"],width=w(2))
    draw.ellipse(el(-44,18,16,34), fill=C["bd"],outline=C["sh"],width=w(1.5))
    draw.ellipse(el(44,18,16,34),  fill=C["bd"],outline=C["sh"],width=w(1.5))
    for ex,ey in [(-10,-30),(10,-30)]:
        draw.ellipse(el(ex,ey,8,8),    fill=C["ey"])
        draw.ellipse(el(ex,ey,4,4),    fill=C["pu"])
        draw.ellipse(el(ex-2,ey-2,2,2),fill=(200,200,255))
    draw.polygon([pt(-6,-16),pt(6,-16),pt(0,-8)],fill=C["bk"])
    draw.ellipse(el(-14,68,14,8),  fill=C["ft"])
    draw.ellipse(el(14,68,14,8),   fill=C["ft"])


def _pd(draw,pt,el,w):  # dragon
    C={"bd":(35,160,60),"dk":(18,100,35),"lt":(80,220,100),"by":(160,235,170),"ol":(12,70,22),"ey":(255,215,40),"pu":(10,15,10),"hn":(200,230,80),"wg":(25,130,50),"fi":(255,100,20)}
    draw.polygon([pt(-40,-10),pt(-75,-50),pt(-60,10),pt(-30,30)],fill=C["wg"],outline=C["ol"])
    draw.polygon([pt(40,-10),pt(75,-50),pt(60,10),pt(30,30)],fill=C["wg"],outline=C["ol"])
    draw.ellipse(el(0,28,40,36),   fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,30,26,24),   fill=C["by"])
    draw.ellipse(el(0,-20,28,34),  fill=C["bd"],outline=C["ol"],width=w(2))
    draw.polygon([pt(-10,-50),pt(-18,-28),pt(-4,-28)],fill=C["hn"],outline=C["ol"])
    draw.polygon([pt(10,-50),pt(4,-28),pt(18,-28)],fill=C["hn"],outline=C["ol"])
    draw.ellipse(el(0,-8,16,10),   fill=C["lt"])
    draw.ellipse(el(-5,-6,3,2),    fill=C["fi"])
    draw.ellipse(el(5,-6,3,2),     fill=C["fi"])
    for ex in [-12,12]:
        draw.ellipse(el(ex,-26,8,8),  fill=C["ey"])
        draw.ellipse(el(ex,-26,3,5),  fill=C["pu"])
        draw.ellipse(el(ex-2,-28,2,2),fill=(255,255,220))
    for lx in [-18,14]:
        draw.ellipse(el(lx,60,14,9),fill=C["dk"],outline=C["ol"],width=w(2))
        for toe in range(3):
            draw.line([pt(lx-10+toe*10,66),pt(lx-12+toe*10,74)],fill=C["dk"],width=w(2.5))


def _pu(draw,pt,el,w):  # unicorn
    C={"bd":(230,185,255),"lt":(250,225,255),"ol":(120,60,175),"ey":(20,12,30),"m1":(255,160,210),"m2":(180,120,255),"m3":(120,200,255),"hn":(255,215,50),"hf":(140,80,200)}
    draw.ellipse(el(0,24,46,40),   fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(-12,-4,20,28), fill=C["bd"],outline=C["ol"],width=w(2))
    for mx,my,mr,col in [(-20,-30,14,C["m1"]),(-24,-18,12,C["m2"]),(-22,-6,10,C["m3"]),(-20,6,9,C["m1"])]:
        draw.ellipse(el(mx,my,mr,mr),fill=col)
    draw.ellipse(el(0,-24,26,24),  fill=C["bd"],outline=C["ol"],width=w(2))
    draw.polygon([pt(0,-56),pt(-6,-28),pt(6,-28)],fill=C["hn"],outline=(200,160,20))
    draw.line([pt(-1,-52),pt(-4,-36)],fill=(255,245,180),width=w(1.5))
    draw.ellipse(el(-10,-28,7,7),  fill=C["ey"])
    draw.ellipse(el(-12,-30,2,2),  fill=(255,255,255))
    for lx,ly in [(-20,50),(-8,52),(8,52),(20,50)]:
        x0,y0=pt(lx-6,ly); x1,y1=pt(lx+6,ly+22)
        draw.rounded_rectangle([x0,y0,x1,y1],radius=max(1,int(5*w(1)/1)),fill=C["bd"],outline=C["ol"])
    for tx,ty,col in [(52,20,C["m1"]),(58,32,C["m2"]),(56,44,C["m3"])]:
        draw.ellipse(el(tx,ty,10,14),fill=col)


def _pp(draw,pt,el,w):  # phoenix
    C={"bd":(220,80,15),"lt":(255,160,40),"ol":(120,20,5),"ey":(255,230,60),"pu":(30,10,5),"bk":(240,170,40),"f1":(255,80,10),"f2":(255,160,20),"f3":(255,220,60)}
    for p1,p2,p3,c in [
        (pt(-50,55),pt(-30,20),pt(-10,60),C["f1"]),
        (pt(-30,62),pt(-10,22),pt(10,65), C["f2"]),
        (pt(-10,65),pt(10,20), pt(30,62), C["f2"]),
        (pt(10,60), pt(30,20), pt(50,55), C["f3"]),
        (pt(30,55), pt(50,15), pt(65,50), C["f1"]),
        (pt(-65,50),pt(-50,15),pt(-30,55),C["f1"]),
    ]: draw.polygon([p1,p2,p3],fill=c)
    draw.polygon([pt(-10,0),pt(-70,-30),pt(-80,20),pt(-55,50),pt(-20,40)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(-15,5),pt(-62,-22),pt(-68,18),pt(-48,40),pt(-22,34)],fill=C["lt"])
    draw.polygon([pt(10,0),pt(70,-30),pt(80,20),pt(55,50),pt(20,40)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(15,5),pt(62,-22),pt(68,18),pt(48,40),pt(22,34)],fill=C["lt"])
    draw.ellipse(el(0,22,28,32),   fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,24,18,22),   fill=C["lt"])
    for cx2,cy2,col in [(-8,-54,C["f3"]),(0,-58,C["f2"]),(8,-54,C["f3"]),(14,-50,C["f1"]),(-14,-50,C["f1"])]:
        draw.polygon([pt(cx2,cy2),pt(cx2-5,-38),pt(cx2+5,-38)],fill=col)
    draw.ellipse(el(0,-26,22,22),  fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(-8,-30,8,8),   fill=C["ey"])
    draw.ellipse(el(-8,-30,4,4),   fill=C["pu"])
    draw.ellipse(el(-10,-32,2,2),  fill=(255,255,220))
    draw.polygon([pt(4,-26),pt(18,-22),pt(6,-18)],fill=C["bk"],outline=C["ol"])


def _pgc(draw,pt,el,w):  # galaxy cat
    C={"bd":(80,40,160),"lt":(130,70,220),"ol":(25,10,60),"ey":(80,210,255),"pu":(10,8,25),"ns":(200,80,255),"st":(100,50,190),"sr":(255,220,80),"by":(110,60,200)}
    draw.ellipse(el(0,28,40,36),   fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(0,30,26,26),   fill=C["by"])
    for sx,sy in [(-8,26),(4,34),(-4,42)]:
        draw.polygon([pt(sx,sy),pt(sx-3,sy+5),pt(sx+3,sy+5)],fill=C["sr"])
    draw.polygon([pt(-22,-52),pt(-36,-22),pt(-8,-22)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(-22,-46),pt(-30,-28),pt(-14,-28)],fill=C["lt"])
    draw.polygon([pt(22,-52),pt(8,-22),pt(36,-22)],fill=C["bd"],outline=C["ol"])
    draw.polygon([pt(22,-46),pt(14,-28),pt(30,-28)],fill=C["lt"])
    draw.ellipse(el(0,-14,33,28),  fill=C["bd"],outline=C["ol"],width=w(2))
    for fy in [-26,-20,-14]:
        draw.line([pt(-10,fy),pt(10,fy)],fill=C["st"],width=w(2))
    for ex in [-12,12]:
        draw.ellipse(el(ex,-20,10,9),  fill=C["ey"])
        draw.ellipse(el(ex,-20,4,6),   fill=C["pu"])
        draw.ellipse(el(ex-2,-22,3,3), fill=(200,240,255))
    draw.polygon([pt(0,-4),pt(-4,1),pt(4,1)],fill=C["ns"])
    for oy in [-1,3]:
        draw.line([pt(-8,oy),pt(-26,oy-2)],fill=C["ol"],width=w(1.5))
        draw.line([pt(8,oy), pt(26,oy-2)], fill=C["ol"],width=w(1.5))
    for lx in [-18,14]:
        draw.ellipse(el(lx,60,14,9),fill=C["bd"],outline=C["ol"],width=w(2))
    draw.ellipse(el(54,40,6,6),    fill=C["sr"])


# ═══════════════════════════════════════════════════════════════════════════════
# Image Engine
# ═══════════════════════════════════════════════════════════════════════════════

class ImageEngine:

    # ── Timer ─────────────────────────────────────────────────────────────────
    def render_timer(self, theme_name: str, remaining: int, total: int,
                     break_time: int, pet_key: str = None, pet_name: str = None,
                     member_names: list = None,
                     xp_per_min: int = 10, coins_per_min: int = 5) -> io.BytesIO:

        T    = THEMES.get(theme_name, THEMES["study"])
        W, H = 1200, 675

        img  = Image.new("RGB", (W, H), T.bg)
        draw = ImageDraw.Draw(img)

        # BG gradient
        for y in range(H):
            draw.line([(0,y),(W,y)], fill=_lerp(T.bg, T.bg2, y/H))

        # Dot grid
        gc = _lerp(T.bg, T.panel, 2.2)
        for gx in range(0, W, 40):
            for gy in range(0, H, 40):
                draw.ellipse([gx-1,gy-1,gx+1,gy+1], fill=gc)

        # Left vertical accent bar
        draw.rectangle([0, 0, 4, H], fill=T.accent2)

        # Top accent bar + glow
        draw.rectangle([0, 0, W, 6], fill=T.accent)
        for i in range(10):
            a = int(35*(1-i/10))
            r,g,b = T.accent2
            draw.line([(4,6+i),(W,6+i)], fill=(r,g,b))

        # Theme label + session hint
        draw.text((20, 20), T.label,             font=_f(12),      fill=T.accent)
        draw.text((20, 38), f"{remaining//60}:{remaining%60:02d} remaining", font=_f(9), fill=T.muted)

        # % complete top-right
        pct     = int((1 - remaining/max(total,1))*100)
        pct_str = f"{pct}% COMPLETE"
        pf      = _f(12)
        pb      = draw.textbbox((0,0), pct_str, font=pf)
        draw.text((W-10-(pb[2]-pb[0]), 20), pct_str, font=pf, fill=T.muted)

        # ── Main timer zone (left of pet panel) ───────────────────────────────
        pet_panel_w = 235 if (pet_key and pet_key in PIXEL_PETS) else 0
        zone_w      = W - pet_panel_w - 8

        # Giant timer
        ts = f"{remaining//60:02d}:{remaining%60:02d}"
        tf = _f(182, bold=True)
        tx = _cx(draw, ts, tf, zone_w, 4)
        draw.text((tx+5, 112), ts, font=tf, fill=_lerp(T.bg2,(0,0,0),0.55))
        draw.text((tx,   108), ts, font=tf, fill=T.text)

        # Rule under timer
        tb  = draw.textbbox((0,0), ts, font=tf)
        tby = 108 + (tb[3]-tb[1]) + 10
        draw.rectangle([20, tby, zone_w-10, tby+1], fill=T.panel)

        # Progress bar — gradient fill
        bx, by, bw, bh = 20, tby+14, zone_w-30, 13
        draw.rounded_rectangle([bx,by,bx+bw,by+bh], radius=6, fill=T.panel)
        prog = max(0.0, 1-remaining/max(total,1))
        fw   = int(bw * prog)
        if fw > 6:
            # Gradient from accent2 to accent
            tmp = Image.new("RGB",(fw,bh), T.accent2)
            for x in range(fw):
                col = _lerp(T.accent2, T.accent, x/max(fw,1))
                for y2 in range(bh):
                    tmp.putpixel((x,y2), col)
            img.paste(tmp, (bx, by))
            # Re-apply rounded mask
            mask = Image.new("L",(fw,bh),0)
            md   = ImageDraw.Draw(mask)
            md.rounded_rectangle([0,0,fw-1,bh-1],radius=6,fill=255)
            img.paste(tmp, (bx,by), mask=mask)
            # Cap glow
            draw.ellipse([bx+fw-10,by-6,bx+fw+10,by+bh+6], fill=T.accent)

        # Quote
        q  = _quote(remaining, total)
        qf = _f(19)
        qy = by + bh + 16
        draw.text((_cx(draw, q, qf, zone_w, 4), qy), q, font=qf, fill=T.muted)

        # 3 Stat pills
        pills = [
            (f"{total//60} MIN", "SESSION"),
            (f"{break_time} MIN", "BREAK"),
            (f"+{xp_per_min} XP", "PER MIN"),
        ]
        pw2, ph2 = 178, 62
        gap2     = 16
        tot_w2   = len(pills)*(pw2+gap2)-gap2
        px0      = max(20, (zone_w-tot_w2)//2)
        pills_y  = qy + 40
        for i,(v,lbl) in enumerate(pills):
            px2 = px0 + i*(pw2+gap2)
            draw.rounded_rectangle([px2,pills_y,px2+pw2,pills_y+ph2], radius=10, fill=T.panel)
            draw.rounded_rectangle([px2,pills_y,px2+pw2,pills_y+3],   radius=10, fill=T.accent2)
            draw.text((_cx(draw,v,  _f(20,True),pw2,px2), pills_y+10), v,   font=_f(20,True),fill=T.text)
            draw.text((_cx(draw,lbl,_f(10),     pw2,px2), pills_y+40), lbl, font=_f(10),     fill=T.muted)

        # Member list
        if member_names:
            ml_y = H - 56
            draw.text((20, ml_y),    "IN SESSION", font=_f(9), fill=T.muted)
            shown = member_names[:8]
            rest  = len(member_names) - len(shown)
            ns    = "  ·  ".join(shown) + (f"  +{rest} more" if rest else "")
            draw.text((20, ml_y+14), ns, font=_f(13, bold=True), fill=T.text)

        # Bottom rule + hint
        draw.rectangle([20, H-18, W-20, H-17], fill=T.panel)
        hint = f"Stay in voice  ·  +{xp_per_min} XP & +{coins_per_min} coins per minute"
        draw.text((_cx(draw, hint, _f(11), W), H-13), hint, font=_f(11), fill=T.muted)

        # ── Pet panel ─────────────────────────────────────────────────────────
        if pet_key and pet_key in PIXEL_PETS:
            px2, py2 = W-pet_panel_w+4, 20
            pw3, ph3 = pet_panel_w-8,  H-40
            draw.rounded_rectangle([px2,py2,px2+pw3,py2+ph3], radius=14, fill=T.panel)
            draw.rounded_rectangle([px2,py2,px2+pw3,py2+4],   radius=14, fill=T.accent2)
            draw.text((_cx(draw,"COMPANION",_f(9),pw3,px2), py2+12), "COMPANION", font=_f(9), fill=T.muted)

            _draw_pet(draw, pet_key, px2+pw3//2, py2+142, 100)

            nm = pet_name or pet_key.replace("_"," ").title()
            draw.text((_cx(draw,nm,_f(15,True),pw3,px2), py2+ph3-56), nm, font=_f(15,True), fill=T.text)
            rl  = RARITY_LABELS[PIXEL_PETS[pet_key]["rarity"]]
            rc  = RARITY_COLORS[PIXEL_PETS[pet_key]["rarity"]]
            draw.text((_cx(draw,rl,_f(9),pw3,px2), py2+ph3-32), rl, font=_f(9), fill=rc)

        return _bytes(img)

    # ── Pet card ─────────────────────────────────────────────────────────────
    def render_timer(self, theme_name: str, remaining: int, total: int,
                     break_time: int, pet_key: str = None, pet_name: str = None,
                     member_names: list = None,
                     xp_per_min: int = 10, coins_per_min: int = 5) -> io.BytesIO:
        T = THEMES.get(theme_name, THEMES["study"])
        W, H = 1200, 675

        img = Image.new("RGB", (W, H), T.bg)
        draw = ImageDraw.Draw(img)

        for y in range(H):
            draw.line([(0, y), (W, y)], fill=_lerp(T.bg, T.bg2, y / H))

        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for radius in range(320, 40, -18):
            alpha = int(24 * (1 - radius / 320))
            gd.ellipse([60 - radius, -140 - radius, 60 + radius, -140 + radius], fill=(*T.accent, alpha))
            gd.ellipse([W - 120 - radius, H - 90 - radius, W - 120 + radius, H - 90 + radius], fill=(*T.accent2, alpha))
        img.paste(glow, mask=glow.split()[3])

        for gx in range(0, W, 42):
            for gy in range(0, H, 42):
                draw.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=_lerp(T.bg2, T.panel, 0.55))

        draw.rounded_rectangle([24, 24, W - 24, H - 24], radius=26, outline=_lerp(T.panel, T.accent2, 0.45), width=2)

        pet_panel_w = 252 if (pet_key and pet_key in PIXEL_PETS) else 0
        left_x = 48
        left_w = W - pet_panel_w - 96

        draw.rounded_rectangle([left_x, 36, left_x + 164, 74], radius=18, fill=T.panel)
        draw.rounded_rectangle([left_x + 12, 48, left_x + 58, 62], radius=7, fill=T.accent2)
        draw.text((left_x + 22, 47), "SV", font=_f(14, True), fill=T.bg2)
        draw.text((left_x + 72, 43), "SEVERUS FOCUS", font=_f(12, True), fill=T.text)
        draw.text((left_x + 72, 58), T.label, font=_f(10), fill=T.muted)

        pct = int((1 - remaining / max(total, 1)) * 100)
        chip = f"{pct}% COMPLETE"
        chip_font = _f(12, True)
        chip_box = draw.textbbox((0, 0), chip, font=chip_font)
        chip_w = chip_box[2] - chip_box[0] + 28
        draw.rounded_rectangle([left_x + left_w - chip_w, 36, left_x + left_w, 72], radius=18, fill=T.panel)
        draw.text((left_x + left_w - chip_w + 14, 47), chip, font=chip_font, fill=T.accent)

        main_top = 104
        main_bottom = H - 122
        draw.rounded_rectangle([left_x, main_top, left_x + left_w, main_bottom], radius=26, fill=_lerp(T.panel, T.bg2, 0.28))
        draw.rounded_rectangle([left_x, main_top, left_x + left_w, main_top + 6], radius=26, fill=T.accent2)

        ts = f"{remaining // 60:02d}:{remaining % 60:02d}"
        tf = _f(168, True)
        tx = _cx(draw, ts, tf, left_w, left_x)
        draw.text((tx + 6, 146), ts, font=tf, fill=_lerp(T.bg2, (0, 0, 0), 0.45))
        draw.text((tx, 140), ts, font=tf, fill=T.text)

        draw.text((_cx(draw, "Deep work in progress", _f(20), left_w, left_x), 292), "Deep work in progress", font=_f(20), fill=T.muted)

        pb_x, pb_y, pb_w, pb_h = left_x + 42, 338, left_w - 84, 18
        draw.rounded_rectangle([pb_x, pb_y, pb_x + pb_w, pb_y + pb_h], radius=9, fill=_lerp(T.bg2, T.panel, 0.9))
        progress = max(0.0, 1 - remaining / max(total, 1))
        fill_w = int(pb_w * progress)
        if fill_w > 0:
            gradient = Image.new("RGB", (max(fill_w, 1), pb_h), T.accent2)
            for x in range(max(fill_w, 1)):
                col = _lerp(T.accent2, T.accent, x / max(fill_w, 1))
                for y2 in range(pb_h):
                    gradient.putpixel((x, y2), col)
            mask = Image.new("L", (max(fill_w, 1), pb_h), 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle([0, 0, max(fill_w - 1, 0), pb_h - 1], radius=9, fill=255)
            img.paste(gradient, (pb_x, pb_y), mask)
            draw.ellipse([pb_x + fill_w - 14, pb_y - 5, pb_x + fill_w + 14, pb_y + pb_h + 5], fill=T.accent)

        quote = _quote(remaining, total)
        draw.text((_cx(draw, quote, _f(18), left_w, left_x), 384), quote, font=_f(18), fill=T.muted)

        stat_cards = [
            ("SESSION", f"{total // 60} min"),
            ("BREAK", f"{break_time} min"),
            ("REWARD", f"+{xp_per_min} XP / +{coins_per_min}C"),
        ]
        card_y = 434
        card_gap = 18
        card_w = int((left_w - 84 - card_gap * 2) / 3)
        for idx, (label, value) in enumerate(stat_cards):
            sx = left_x + 42 + idx * (card_w + card_gap)
            draw.rounded_rectangle([sx, card_y, sx + card_w, card_y + 86], radius=18, fill=T.panel)
            draw.rounded_rectangle([sx, card_y, sx + card_w, card_y + 5], radius=18, fill=T.accent2)
            draw.text((sx + 16, card_y + 18), label, font=_f(10), fill=T.muted)
            draw.text((sx + 16, card_y + 42), value, font=_f(20, True), fill=T.text)

        member_box_y = 540
        draw.rounded_rectangle([left_x + 42, member_box_y, left_x + left_w - 42, member_box_y + 68], radius=18, fill=T.panel)
        draw.text((left_x + 60, member_box_y + 14), "ROOM MEMBERS", font=_f(10), fill=T.muted)
        shown = (member_names or [])[:8]
        rest = max(len(member_names or []) - len(shown), 0)
        roster = " | ".join(shown) if shown else "Waiting for participants"
        if rest:
            roster += f" | +{rest} more"
        draw.text((left_x + 60, member_box_y + 36), roster, font=_f(16, True), fill=T.text)

        footer = "Stay in voice for steady focus rewards and a clean completion bonus."
        draw.text((_cx(draw, footer, _f(11), W), H - 42), footer, font=_f(11), fill=T.muted)

        if pet_key and pet_key in PIXEL_PETS:
            px, py = W - pet_panel_w - 44, 104
            pw, ph = pet_panel_w, 504
            draw.rounded_rectangle([px, py, px + pw, py + ph], radius=24, fill=_lerp(T.panel, T.bg2, 0.2))
            draw.rounded_rectangle([px, py, px + pw, py + 6], radius=24, fill=T.accent)
            draw.text((px + 24, py + 22), "COMPANION", font=_f(10), fill=T.muted)
            draw.text((px + 24, py + 44), "Focus partner online", font=_f(16, True), fill=T.text)

            _draw_pet(draw, pet_key, px + pw // 2, py + 182, 116)

            pet_title = pet_name or pet_key.replace("_", " ").title()
            rarity = PIXEL_PETS[pet_key]["rarity"]
            rarity_label = RARITY_LABELS[rarity]
            rarity_color = RARITY_COLORS[rarity]
            draw.text((_cx(draw, pet_title, _f(18, True), pw, px), py + 322), pet_title, font=_f(18, True), fill=T.text)
            draw.text((_cx(draw, rarity_label, _f(10), pw, px), py + 350), rarity_label, font=_f(10), fill=rarity_color)

            tip_box_y = py + 388
            draw.rounded_rectangle([px + 20, tip_box_y, px + pw - 20, tip_box_y + 78], radius=18, fill=T.panel)
            draw.text((px + 34, tip_box_y + 16), "SYNC BONUS", font=_f(10), fill=T.muted)
            draw.text((px + 34, tip_box_y + 38), "Keep the room active and finish together.", font=_f(14, True), fill=T.text)

        return _bytes(img)

    def render_pet_card(self, species: str, pet_name: str, level: int,
                        xp: int, happiness: int, active: bool = False) -> io.BytesIO:
        pd   = PIXEL_PETS.get(species, list(PIXEL_PETS.values())[0])
        rc   = RARITY_COLORS[pd["rarity"]]
        W, H = 600, 760
        bg1, bg2 = _PET_BG.get(species, ((12,12,20),(20,20,32)))

        img  = Image.new("RGB",(W,H),bg1)
        draw = ImageDraw.Draw(img)
        for y in range(H):
            draw.line([(0,y),(W,y)],fill=_lerp(bg1,bg2,y/H))
        for gx in range(0,W,45):
            for gy in range(0,H,45):
                draw.ellipse([gx-1,gy-1,gx+1,gy+1],fill=_lerp(bg1,bg2,2.0))

        # Rarity glow at top
        glow = Image.new("RGBA",(W,H),(0,0,0,0))
        gd   = ImageDraw.Draw(glow)
        for r in range(210,0,-14):
            a = int(26*(1-r/210))
            gd.ellipse([W//2-r,-r//2,W//2+r,r],fill=(*rc,a))
        img.paste(glow,mask=glow.split()[3])

        # Top bar + badge
        draw.rectangle([0,0,W,5],fill=rc)
        badge = RARITY_LABELS[pd["rarity"]]
        bf    = _f(13,True)
        bw    = bf.getbbox(badge)[2]+36
        bx2   = (W-bw)//2
        draw.rounded_rectangle([bx2,14,bx2+bw,44],radius=10,fill=rc)
        draw.text((_cx(draw,badge,bf,W),20),badge,font=bf,fill=(8,8,8))

        # Pet art
        _draw_pet(draw, species, W//2, 218, 165)

        # Name
        draw.text((_cx(draw,pet_name,_f(46,True),W),375),pet_name,font=_f(46,True),fill=(245,245,255))
        sp = species.replace("_"," ").upper()
        draw.text((_cx(draw,sp,_f(13),W),436),sp,font=_f(13),fill=rc)
        draw.text((_cx(draw,pd["desc"],_f(13),W),460),pd["desc"],font=_f(13),fill=(155,155,175))

        # Stats panel
        sx,sy,sw,sh = 28,505,W-56,206
        draw.rounded_rectangle([sx,sy,sx+sw,sy+sh],radius=18,fill=_lerp(bg2,(0,0,0),0.35))
        draw.rounded_rectangle([sx,sy,sx+sw,sy+5], radius=18,fill=rc)

        draw.text((sx+26,sy+18),f"LV. {level}",font=_f(36,True),fill=(245,245,255))

        # XP bar
        xn  = level*100
        bx3,by3,bw3,bh3 = sx+26,sy+76,sw-52,10
        draw.text((bx3,sy+58),f"XP  {xp} / {xn}",font=_f(12),fill=rc)
        draw.rounded_rectangle([bx3,by3,bx3+bw3,by3+bh3],radius=5,fill=_lerp(bg1,(0,0,0),0.5))
        xf = int(bw3*min(xp/max(xn,1),1))
        if xf: draw.rounded_rectangle([bx3,by3,bx3+xf,by3+bh3],radius=5,fill=rc)

        # Happiness bar
        hy = sy+126
        hc = (80,220,80) if happiness>60 else (220,160,40) if happiness>30 else (220,60,60)
        draw.text((bx3,sy+108),f"HAPPINESS  {happiness}%",font=_f(12),fill=hc)
        draw.rounded_rectangle([bx3,hy,bx3+bw3,hy+bh3],radius=5,fill=_lerp(bg1,(0,0,0),0.5))
        hf = int(bw3*happiness/100)
        if hf: draw.rounded_rectangle([bx3,hy,bx3+hf,hy+bh3],radius=5,fill=hc)

        # Active badge
        if active:
            draw.rounded_rectangle([sx+sw-146,sy+18,sx+sw-18,sy+50],radius=10,fill=(30,190,70))
            draw.text((sx+sw-134,sy+27),"ACTIVE",font=_f(14,True),fill=(255,255,255))

        return _bytes(img)

    # ── Pet shop card ─────────────────────────────────────────────────────────
    def render_pet_shop_card(self, species: str) -> io.BytesIO:
        pd   = PIXEL_PETS.get(species, list(PIXEL_PETS.values())[0])
        rc   = RARITY_COLORS[pd["rarity"]]
        W, H = 480, 450
        bg1, bg2 = _PET_BG.get(species,((12,12,20),(20,20,32)))

        img  = Image.new("RGB",(W,H),bg1)
        draw = ImageDraw.Draw(img)
        for y in range(H):
            draw.line([(0,y),(W,y)],fill=_lerp(bg1,bg2,y/H))
        for gx in range(0,W,45):
            for gy in range(0,H,45):
                draw.ellipse([gx-1,gy-1,gx+1,gy+1],fill=_lerp(bg1,bg2,2.0))

        glow = Image.new("RGBA",(W,H),(0,0,0,0))
        gd   = ImageDraw.Draw(glow)
        for r in range(160,0,-12):
            a = int(24*(1-r/160))
            gd.ellipse([W//2-r,-r//2,W//2+r,r],fill=(*rc,a))
        img.paste(glow,mask=glow.split()[3])

        draw.rectangle([0,0,W,4],fill=rc)
        badge = RARITY_LABELS[pd["rarity"]]
        bf    = _f(12,True)
        bw    = bf.getbbox(badge)[2]+28
        bx2   = (W-bw)//2
        draw.rounded_rectangle([bx2,14,bx2+bw,38],radius=9,fill=rc)
        draw.text((_cx(draw,badge,bf,W),19),badge,font=bf,fill=(8,8,8))

        _draw_pet(draw, species, W//2, 186, 135)

        name = species.replace("_"," ").title()
        draw.text((_cx(draw,name,_f(28,True),W),307),name,font=_f(28,True),fill=(245,245,255))
        draw.text((_cx(draw,pd["desc"],_f(12),W),352),pd["desc"],font=_f(12),fill=(150,150,170))

        ps  = f"{pd['price']:,}  COINS"
        pf2 = _f(18,True)
        pw2 = pf2.getbbox(ps)[2]+48
        ppx = (W-pw2)//2
        draw.rounded_rectangle([ppx,390,ppx+pw2,428],radius=12,fill=_lerp(bg2,(0,0,0),0.5))
        draw.rounded_rectangle([ppx,390,ppx+pw2,394],radius=12,fill=(200,170,40))
        draw.text((_cx(draw,ps,pf2,W),398),ps,font=pf2,fill=(220,185,55))

        return _bytes(img)

    # ── Profile card ─────────────────────────────────────────────────────────
    def render_profile(self, username: str, xp: int, coins: int,
                       total_focus: int, sessions: int,
                       active_pet: dict = None) -> io.BytesIO:
        W, H   = 960, 520
        bg1    = (6,6,14)
        bg2    = (10,10,22)
        acc    = (100,130,255)

        img  = Image.new("RGB",(W,H),bg1)
        draw = ImageDraw.Draw(img)
        for y in range(H):
            draw.line([(0,y),(W,y)],fill=_lerp(bg1,bg2,y/H))
        for gx in range(0,W,55):
            for gy in range(0,H,55):
                draw.ellipse([gx-1,gy-1,gx+1,gy+1],fill=(14,14,28))

        # Left vertical bar
        draw.rectangle([0,0,4,H],fill=acc)
        draw.rectangle([0,0,W,5],fill=acc)

        cx2 = 48
        draw.text((cx2,28), username, font=_f(44,True), fill=(250,250,255))
        level = max(1,int(xp**0.45)//5)
        draw.text((cx2,86), f"LEVEL  {level}", font=_f(14), fill=acc)

        # XP bar
        xpn = int(((level+1)*5)**(1/0.45))
        xpp = int((level*5)**(1/0.45)) if level>1 else 0
        xbw = 356
        xf  = int(xbw*min((xp-xpp)/max(xpn-xpp,1),1))
        draw.text((cx2,112),f"{xp:,} XP  /  {xpn:,} to next",font=_f(10),fill=(100,110,160))
        by2 = 130
        draw.rounded_rectangle([cx2,by2,cx2+xbw,by2+8],radius=4,fill=(18,20,42))
        if xf>2: draw.rounded_rectangle([cx2,by2,cx2+xf,by2+8],radius=4,fill=acc)

        # 4 stat cards
        cards = [
            ("TOTAL XP",   f"{xp:,}",              acc),
            ("COINS",      f"{coins:,}",            (210,175,35)),
            ("HOURS",      f"{total_focus/60:.1f}", (55,195,110)),
            ("SESSIONS",   str(sessions),            (185,90,230)),
        ]
        cw, ch = 182, 116
        ry     = 180
        for i,(lbl,val,col) in enumerate(cards):
            cx3 = cx2+i*(cw+14)
            draw.rounded_rectangle([cx3,ry,cx3+cw,ry+ch],radius=13,fill=(13,15,32))
            draw.rounded_rectangle([cx3,ry,cx3+cw,ry+4], radius=13,fill=col)
            draw.text((cx3+14,ry+14),val,font=_f(26,True),fill=(245,245,255))
            draw.text((cx3+14,ry+56),lbl,font=_f(10),     fill=(90,100,140))
            draw.rounded_rectangle([cx3+14,ry+80,cx3+cw-14,ry+84],radius=3,fill=_lerp((13,15,32),col,0.4))

        # Focus progress
        fb_y = 334
        fbw  = cw*4+14*3
        draw.text((cx2,fb_y),"FOCUS PROGRESS",font=_f(9),fill=(80,90,130))
        draw.rounded_rectangle([cx2,fb_y+20,cx2+fbw,fb_y+32],radius=6,fill=(14,16,36))
        ff = int(fbw*min(total_focus/60,100)/100)
        if ff: draw.rounded_rectangle([cx2,fb_y+20,cx2+ff,fb_y+32],radius=6,fill=(55,195,110))
        for pv,pl in [(0.1,"10h"),(0.25,"25h"),(0.5,"50h"),(1.0,"100h")]:
            mx = cx2+int(fbw*pv)
            draw.line([(mx,fb_y+16),(mx,fb_y+36)],fill=(28,32,60))
            draw.text((mx-8,fb_y+38),pl,font=_f(9),fill=(70,80,120))

        # Milestones
        ml_y = 410
        draw.text((cx2,ml_y),"MILESTONES",font=_f(9),fill=(80,90,130))
        for i,(nm,unlocked,col) in enumerate([
            ("First Session",sessions>=1,         acc),
            ("10 Sessions",  sessions>=10,        (55,195,110)),
            ("50 Hours",     total_focus>=3000,   (210,175,35)),
            ("1000 XP",      xp>=1000,            (185,90,230)),
        ]):
            mx2 = cx2+i*198
            draw.rounded_rectangle([mx2,ml_y+20,mx2+180,ml_y+54],radius=8,fill=col if unlocked else (16,18,36))
            draw.text((mx2+10,ml_y+31),nm,font=_f(11),fill=(8,8,8) if unlocked else (50,55,80))

        # Pet panel right
        if active_pet:
            sp  = active_pet.get("species","cat")
            pd  = PIXEL_PETS.get(sp,list(PIXEL_PETS.values())[0])
            rc2 = RARITY_COLORS[pd["rarity"]]
            px2,py2,pw3,ph3 = W-234,24,206,H-48
            draw.rounded_rectangle([px2,py2,px2+pw3,py2+ph3],radius=18,fill=(12,14,28))
            draw.rounded_rectangle([px2,py2,px2+pw3,py2+4],  radius=18,fill=rc2)
            draw.text((_cx(draw,"PET",_f(9),pw3,px2),py2+12),"PET",font=_f(9),fill=(80,90,130))
            _draw_pet(draw, sp, px2+pw3//2, py2+184, 126)
            pn = active_pet.get("name",sp.title())
            draw.text((_cx(draw,pn,_f(17,True),pw3,px2), py2+304),pn,font=_f(17,True),fill=(245,245,255))
            draw.text((_cx(draw,RARITY_LABELS[pd["rarity"]],_f(9),pw3,px2),py2+330),RARITY_LABELS[pd["rarity"]],font=_f(9),fill=rc2)
            lv2 = active_pet.get("level",1)
            draw.text((_cx(draw,f"LEVEL  {lv2}",_f(12),pw3,px2),py2+352),f"LEVEL  {lv2}",font=_f(12),fill=acc)
            pxp2 = active_pet.get("xp",0)
            mbx=px2+18; mbw2=pw3-36; mby=py2+382
            draw.rounded_rectangle([mbx,mby,mbx+mbw2,mby+6],radius=3,fill=(18,20,42))
            mf=int(mbw2*min(pxp2/max(lv2*100,1),1))
            if mf: draw.rounded_rectangle([mbx,mby,mbx+mf,mby+6],radius=3,fill=rc2)

        # Footer
        draw.rectangle([0,H-36,W,H-35],fill=(18,20,42))
        ft = "Use /timer to earn XP and coins  ·  /petshop to adopt companions"
        draw.text((_cx(draw,ft,_f(10),W),H-26),ft,font=_f(10),fill=(60,70,100))

        return _bytes(img)
