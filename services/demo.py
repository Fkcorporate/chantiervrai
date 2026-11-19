"""Donnees de demonstration : comptes, chantiers, preuves dessinees, paiements, inspection.
Pour les demonstrations commerciales et les captures d'ecran. Ne jamais lancer sur une base reelle."""
import random

from PIL import Image, ImageDraw, ImageFilter

PASSWORD = "Demo-Chantier-2026"


def site_photo(stage, seed, size=(1280, 960)):
    """Photo de chantier dessinee : fondations, soubassement, dalle, murs."""
    rnd = random.Random(seed)
    w, h = size
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    horizon = int(h * (0.42 + rnd.uniform(-0.04, 0.04)))
    for y in range(horizon):                                   # ciel
        t = y / horizon
        d.line([(0, y), (w, y)], fill=(int(120 + 90 * t), int(170 + 60 * t), int(220 + 25 * t)))
    for y in range(horizon, h):                                # sol de laterite
        t = (y - horizon) / (h - horizon)
        d.line([(0, y), (w, y)], fill=(int(168 - 30 * t), int(92 - 20 * t), int(54 - 10 * t)))
    for _ in range(5):                                         # vegetation au loin
        x = rnd.randint(0, w); r = rnd.randint(40, 110)
        d.ellipse([x - r, horizon - r, x + r, horizon + r // 3], fill=(46 + rnd.randint(0, 30), 96 + rnd.randint(0, 40), 52))
    for _ in range(1400):                                      # texture du sol
        x, y = rnd.randint(0, w), rnd.randint(horizon, h)
        c = rnd.randint(-25, 25)
        d.point((x, y), fill=(150 + c, 80 + c, 48 + c))
    left, right = int(w * 0.16), int(w * 0.84)
    base = int(h * 0.72)
    block = (182, 182, 176)
    if stage == 0:                                             # tranchees + ferraillage
        for i in range(3):
            y = base - i * 55
            d.rectangle([left + i * 40, y, right - i * 40, y + 26], fill=(92, 52, 30))
            for x in range(left + i * 40, right - i * 40, 22):
                d.line([(x, y + 4), (x + 10, y + 22)], fill=(70, 70, 72), width=3)
            d.line([(left + i * 40, y + 6), (right - i * 40, y + 6)], fill=(60, 60, 64), width=4)
            d.line([(left + i * 40, y + 18), (right - i * 40, y + 18)], fill=(60, 60, 64), width=4)
    else:
        courses = {1: 4, 2: 5, 3: 13}.get(stage, 13)
        bh, bw = max(8, int(h * 0.031)), max(20, int(w * 0.061))
        top = base - courses * bh
        for c in range(courses):                               # rangs de parpaings
            y = base - (c + 1) * bh
            off = (bw // 2) if c % 2 else 0
            for x in range(left - off, right, bw):
                x0, x1 = max(x, left), min(x + bw - 4, right)
                if x1 > x0:
                    shade = rnd.randint(-10, 10)
                    d.rectangle([x0, y, x1, y + bh - 4], fill=(block[0] + shade, block[1] + shade, block[2] + shade))
        if stage >= 2:                                          # dalle et poteaux
            sl = int(h * 0.035)
            d.rectangle([left - 30, top - sl, right + 30, top], fill=(150, 150, 146))
            for x in (left, (left + right) // 2, right - 26):
                d.rectangle([x, top - sl, x + 26, base], outline=(120, 120, 116), width=3)
            for x in range(left - 20, right + 20, 30):
                d.line([(x, top - sl), (x, top - 2 * sl)], fill=(70, 70, 72), width=3)
        if stage == 3:
            d.rectangle([int(w * 0.40), top + int(h * 0.06), int(w * 0.52), base], fill=(70, 52, 40))   # ouverture de porte
    for i in range(rnd.randint(2, 4)):                         # sacs de ciment
        x = rnd.randint(int(w * 0.05), int(w * 0.25)); y = rnd.randint(int(h * 0.80), int(h * 0.90))
        d.rounded_rectangle([x, y, x + 70, y + 40], radius=8, fill=(222, 214, 196), outline=(170, 160, 140))
    x = rnd.randint(int(w * 0.70), int(w * 0.88))              # tas de sable
    d.pieslice([x - 110, int(h * 0.80), x + 110, int(h * 0.98)], 180, 360, fill=(214, 182, 120))
    return im.filter(ImageFilter.GaussianBlur(0.6))


def pano(stage, seed=0):
    """Photo 360 equirectangulaire d'un etage en construction (4000 x 2000).
    stage 1 : poteaux et dalle ; stage 2 : murs en parpaings montes entre les poteaux."""
    rnd = random.Random(seed)
    w, h = 4000, 2000
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h // 2):                                 # ciel
        t = y / (h / 2)
        d.line([(0, y), (w, y)], fill=(int(120 + 80 * t), int(170 + 50 * t), int(225 + 20 * t)))
    for y in range(h // 2, h):                              # dalle beton
        t = (y - h / 2) / (h / 2)
        d.line([(0, y), (w, y)], fill=(int(150 - 40 * t), int(146 - 40 * t), int(138 - 40 * t)))
    horizon = h // 2
    cols = 8
    for i in range(cols):
        cx = int((i + 0.5) * w / cols)
        if stage >= 2 and i % 2 == 0:                       # mur entre ce poteau et le suivant
            x0, x1 = cx, cx + w // cols
            d.rectangle([x0, horizon - 330, x1, horizon + 260], fill=(176, 170, 158))
            for row in range(0, 590, 42):
                y = horizon - 330 + row
                d.line([(x0, y), (x1, y)], fill=(140, 134, 124), width=3)
                off = 0 if (row // 42) % 2 else 60
                for x in range(x0 + off, x1, 120):
                    d.line([(x, y), (x, y + 42)], fill=(140, 134, 124), width=3)
        d.rectangle([cx - 38, horizon - 420, cx + 38, horizon + 300], fill=(186, 182, 172))
        d.line([(cx - 38, horizon - 420), (cx - 38, horizon + 300)], fill=(120, 116, 108), width=4)
        for k in range(3):                                  # fers en attente
            d.line([(cx - 20 + k * 20, horizon - 420), (cx - 20 + k * 20, horizon - 520)], fill=(90, 60, 40), width=5)
    d.rectangle([0, horizon - 440, w, horizon - 418], fill=(160, 156, 148))   # rive de dalle haute
    for _i in range(25):                                    # sacs, parpaings, outils
        x, y = rnd.randint(0, w - 80), rnd.randint(horizon + 320, h - 80)
        d.rectangle([x, y, x + rnd.randint(40, 90), y + rnd.randint(25, 50)], fill=rnd.choice([(196, 186, 160), (150, 150, 150), (110, 90, 70)]))
    return im


def aerial(stage, seed=0, size=(1600, 1000)):
    """Vue du dessus dessinée (orthophoto de démonstration) : terrain, bornes, emprise, dalle puis murs."""
    rnd = random.Random(seed)
    w, h = size
    im = Image.new("RGB", size, (92, 118, 64))
    d = ImageDraw.Draw(im)
    for _ in range(900):                                        # végétation autour
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(6, 26)
        g = rnd.randint(70, 120)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(40 + g // 3, g, 40 + g // 4))
    d.rectangle([0, h - 150, w, h - 70], fill=(170, 112, 70))  # piste en latérite
    px0, py0, px1, py1 = 420, 150, 1180, 760                    # parcelle
    d.rectangle([px0, py0, px1, py1], fill=(184, 110, 64))
    for _ in range(400):
        x, y = rnd.randint(px0, px1), rnd.randint(py0, py1)
        c = rnd.randint(-18, 18)
        d.point((x, y), fill=(184 + c, 110 + c, 64 + c))
    for (bx, by) in ((px0, py0), (px1, py0), (px1, py1), (px0, py1)):
        d.rectangle([bx - 6, by - 6, bx + 6, by + 6], fill=(240, 240, 235))
    hx0, hy0, hx1, hy1 = 560, 260, 1040, 640                    # emprise de la maison
    if stage >= 1:
        d.rectangle([hx0 - 10, hy0 - 10, hx1 + 10, hy1 + 10], outline=(120, 74, 44), width=14)
    if stage >= 2:
        d.rectangle([hx0, hy0, hx1, hy1], fill=(168, 168, 162))
        for x in range(hx0, hx1, 40):
            d.line([(x, hy0), (x, hy1)], fill=(150, 150, 145), width=1)
    if stage >= 3:
        for (a, b, c_, e) in ((hx0, hy0, hx1, hy0 + 22), (hx0, hy1 - 22, hx1, hy1), (hx0, hy0, hx0 + 22, hy1), (hx1 - 22, hy0, hx1, hy1),
                              (hx0, 450, 820, 472), (800, hy0, 822, 640)):
            d.rectangle([a, b, c_, e], fill=(214, 210, 198))
    if stage >= 4:
        d.rectangle([hx0, hy0, hx1, hy1], fill=(196, 196, 190))
        d.rectangle([hx0 + 40, hy0 + 40, hx0 + 160, hy0 + 140], fill=(120, 120, 116))
    for _ in range(4 + stage * 2):                              # tas de sable, parpaings, ouvriers
        x, y = rnd.randint(px0 + 20, px1 - 60), rnd.randint(py0 + 20, py1 - 60)
        if hx0 - 20 < x < hx1 + 20 and hy0 - 20 < y < hy1 + 20:
            continue
        if rnd.random() < 0.5:
            d.ellipse([x, y, x + 60, y + 44], fill=(222, 196, 140))
        else:
            d.rectangle([x, y, x + 50, y + 36], fill=(150, 150, 150))
    return im.filter(ImageFilter.GaussianBlur(0.6))
