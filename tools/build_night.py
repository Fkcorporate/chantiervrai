"""Génère les surcharges « Nuit » de static/style.css : chaque surface claire codée en dur devient une teinte sombre,
et chaque texte foncé devient clair. Relancer après une modification de style.css :  python3 tools/build_night.py"""
import os, re
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
css = open(os.path.join(BASE, "static", "style.css"), encoding="utf-8").read()
css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def hexrgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(c):
    a = [(v / 255) for v in c]
    a = [v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4 for v in a]
    return .2126 * a[0] + .7152 * a[1] + .0722 * a[2]


def parse_color(v):
    m = re.search(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", v)
    if m:
        return hexrgb(m.group(1)), 1.0
    m = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\)", v)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3))), float(m.group(4) or 1)
    if re.search(r"\bwhite\b", v):
        return (255, 255, 255), 1.0
    return None, None


def hue(c):
    r, g, b = c
    if g > r + 8 and g >= b:
        return "green"
    if r > b + 25 and r > g + 8:
        return "orange" if (r - g) >= (g - b) else "gold"
    if b > r + 8:
        return "blue"
    return "neutral"


TINT = {"green": "#11271C", "orange": "#2A1912", "gold": "#251F14", "blue": "#14202E", "neutral": "#101B16"}
TEXT = {"green": "#74DBA8", "orange": "#F3A188", "gold": "#E3C48E", "blue": "#A4C6F4", "neutral": "#ECE8DD"}
out = []
for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
    sel, body = m.group(1).strip(), m.group(2)
    if not sel or sel.startswith(("from", "to", "@")) or re.match(r"^[\d.%\s,]+$", sel) or ":root" in sel or "theme-" in sel:
        continue
    if re.search(r"\bbody\.(night|top-dark)\b", sel):
        continue
    # Surfaces déjà sombres quel que soit le thème (viseur, cartes « hero ») : on n'y touche pas
    if re.search(r"\.camera\b|\.ph-hero|\.ph-kicker|\.ph-cta|\.ph-th\b|\.ch-play|\.ch-badge", sel):
        continue
    decl = dict((k.strip(), v.strip()) for k, _, v in (d.partition(":") for d in body.split(";")) if k.strip())
    bgv = decl.get("background-color") or decl.get("background")
    new = []
    bg, a = parse_color(bgv) if bgv and "gradient" not in bgv and "url(" not in bgv else (None, None)
    light_bg = bg is not None and a >= .75 and lum(bg) > .55
    if light_bg:
        new.append(f"background:{TINT[hue(bg)] if lum(bg) < .93 else TINT['neutral']}")
        if bgv and "background" in decl and ("url(" in decl["background"]):
            new = []
    col = decl.get("color")
    cc, ca = parse_color(col) if col else (None, None)
    saturated_bg = bg is not None and a >= .75 and not light_bg and lum(bg) > .12
    unknown_bg = bool(bgv) and bg is None and "none" not in bgv and "transparent" not in bgv
    if cc is not None and not saturated_bg and not unknown_bg and lum(cc) < .35:
        if not (bg is not None and lum(bg) < .12):
            new.append("color:" + (TEXT[hue(cc)] if hue(cc) != "neutral" else ("#93A69D" if lum(cc) > .08 else "#ECE8DD")))
    elif light_bg and cc is None:
        new.append("color:#ECE8DD")
    bc = decl.get("border-color") or decl.get("border") or decl.get("border-bottom") or decl.get("border-top")
    if bc:
        b, _a = parse_color(bc)
        if b is not None and lum(b) > .55:
            prop = "border-color" if "border-color" in decl or "border" in decl else ("border-bottom-color" if "border-bottom" in decl else "border-top-color")
            new.append(f"{prop}:rgba(255,255,255,.1)")
    if new:
        sels = ",".join("body.theme-nuit " + s.strip() for s in sel.split(",") if s.strip() and not s.strip().startswith("body") and not s.strip().startswith("html"))
        if sels:
            out.append(sels + "{" + ";".join(new) + "}")
dest = os.path.join(BASE, "static", "themes-night.css")
open(dest, "w", encoding="utf-8").write("/* Généré par tools/build_night.py à partir de style.css : ne pas modifier à la main */\n" + "\n".join(out) + "\n")
print(len(out), "règles ->", dest)
