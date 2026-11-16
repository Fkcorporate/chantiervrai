"""Analyse des images.

1. Toujours actif, en local (Pillow + numpy) : empreinte visuelle de chaque
   photo pour reperer les photos quasi identiques (photo d'ecran, recadrage)
   et mesurer la ressemblance avec les photos deja verifiees du chantier.
2. Avec ANTHROPIC_API_KEY : un modele de vision reconnait l'etape de
   construction visible, dit s'il s'agit du meme chantier que la photo de
   reference, et lit les factures (fournisseur, lignes, quantites, prix).
   Modele : AI_MODEL (claude-sonnet-5-5 par defaut).
"""
import base64
import io
import os
import json
import re

import numpy as np
from PIL import Image, ImageFilter

from . import env, http_json

API = "https://api.anthropic.com/v1/messages"


# --------------------------------------------------------------------------
# Local
# --------------------------------------------------------------------------
CROPS = (1.0, 0.94, 0.88, 0.80)      # cadrages compares : plein cadre, recadrages legers, ecran avec son bord


def _dhash256(img):
    """dHash 16 x 16 (256 bits) sur une image floutee : robuste au moire, au flou et a la dominante de couleur."""
    g = np.asarray(img.convert("L").filter(ImageFilter.GaussianBlur(2)).resize((17, 16), Image.BILINEAR), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return "".join("1" if b else "0" for b in bits)


def multi_hash(img):
    """Empreintes du plein cadre et de cadrages centres : un recadrage ou la photo d'un ecran retombe sur l'une d'elles."""
    w, h = img.size
    out = {}
    for c in CROPS:
        dx, dy = int(w * (1 - c) / 2), int(h * (1 - c) / 2)
        out[str(c)] = f"{int(_dhash256(img.crop((dx, dy, w - dx, h - dy))), 2):064x}"
    return out


def multi_distance(a, b):
    """Distance 0-1 entre deux empreintes multiples : la plus faible entre le plein cadre de l'une et un cadrage de l'autre."""
    best = 1.0
    full_a, full_b = int(a["1.0"], 16), int(b["1.0"], 16)
    for c in a:
        best = min(best, bin(full_a ^ int(b[c], 16)).count("1") / 256, bin(int(a[c], 16) ^ full_b).count("1") / 256)
    return best


def features(img):
    """Empreinte visuelle : dHash 64 bits + histogramme de couleurs 64 cases."""
    g = np.asarray(img.convert("L").resize((9, 8), Image.BILINEAR), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    dh = 0
    for b in bits:
        dh = (dh << 1) | int(b)
    small = np.asarray(img.convert("RGB").resize((64, 64)), dtype=np.uint8) // 64
    idx = small[..., 0] * 16 + small[..., 1] * 4 + small[..., 2]
    hist = np.bincount(idx.flatten(), minlength=64).astype(float)
    hist /= hist.sum() or 1
    return {"dhash": f"{dh:016x}", "hist": [round(x, 4) for x in hist], "mh": multi_hash(img)}


def nearest(feat, refs):
    """Preuve la plus ressemblante : (distance 0-1, indice dans refs). Empreinte multiple si disponible, sinon dHash 64."""
    best, idx = None, None
    for i, r in enumerate(refs):
        if feat.get("mh") and r.get("mh"):
            d = multi_distance(feat["mh"], r["mh"])
        else:
            d = bin(int(feat["dhash"], 16) ^ int(r["dhash"], 16)).count("1") / 64
        if best is None or d < best:
            best, idx = d, i
    return best, idx


def compare(feat, refs):
    """Compare une empreinte aux empreintes de reference.
    Retourne (distance dHash minimale, ressemblance couleur maximale 0-1)."""
    best_d, best_s = None, None
    a = int(feat["dhash"], 16)
    ha = np.array(feat["hist"])
    for r in refs:
        d = bin(a ^ int(r["dhash"], 16)).count("1")
        s = float(np.minimum(ha, np.array(r["hist"])).sum())
        best_d = d if best_d is None else min(best_d, d)
        best_s = s if best_s is None else max(best_s, s)
    return best_d, best_s


def change_ratio(img_a, img_b, threshold=40):
    """Part des pixels qui ont change entre deux images (0-1), apres alignement de taille."""
    size = (256, 256)
    a = np.asarray(img_a.convert("L").resize(size), dtype=np.int16)
    b = np.asarray(img_b.convert("L").resize(size), dtype=np.int16)
    # normalisation de luminosite pour ne pas compter les differences d'eclairage
    a = (a - a.mean()) / (a.std() or 1) * 50
    b = (b - b.mean()) / (b.std() or 1) * 50
    return float((np.abs(a - b) > threshold).mean())


def change_map(img_a, img_b, threshold=40):
    """Image des changements : pixels modifies en orange sur l'image recente."""
    size = (512, 512)
    base = img_b.convert("RGB").resize(size)
    a = np.asarray(img_a.convert("L").resize(size), dtype=np.int16)
    b = np.asarray(img_b.convert("L").resize(size), dtype=np.int16)
    a = (a - a.mean()) / (a.std() or 1) * 50
    b = (b - b.mean()) / (b.std() or 1) * 50
    mask = np.abs(a - b) > threshold
    out = np.asarray(base).copy()
    out[mask] = (0.4 * out[mask] + 0.6 * np.array([217, 95, 31])).astype(np.uint8)
    return Image.fromarray(out)


# --------------------------------------------------------------------------
# Modele de vision (optionnel)
# --------------------------------------------------------------------------
def ai_enabled():
    return bool(env("ANTHROPIC_API_KEY"))


def _jpeg_b64(img, max_side=1024):
    im = img.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def _call(content, max_tokens=900):
    code, body = http_json(API, {
        "model": env("AI_MODEL", "claude-sonnet-5-5"), "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }, headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}, timeout=60)
    if code != 200 or not isinstance(body, dict):
        raise RuntimeError(f"API vision : {code} {str(body)[:200]}")
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("Réponse de l'IA illisible")
    return json.loads(m.group(0))


def analyse_photo(img, ref_img, step_names, current_step):
    content = []
    if ref_img is not None:
        content += [{"type": "text", "text": "Photo de référence du chantier (déjà vérifiée) :"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _jpeg_b64(ref_img)}}]
    content += [{"type": "text", "text": "Nouvelle photo envoyée par le chef de chantier :"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _jpeg_b64(img)}}]
    content.append({"type": "text", "text": (
        "Tu contrôles un chantier de construction pour un propriétaire qui vit à l'étranger.\n"
        f"Étapes prévues, dans l'ordre : {', '.join(step_names)}.\n"
        f"Étape déclarée en cours : {current_step}.\n"
        "Réponds uniquement par un objet JSON avec ces clés :\n"
        '"chantier" (true si la nouvelle photo montre bien un chantier de construction),\n'
        '"meme_chantier" (true, false, ou null s\'il n\'y a pas de photo de référence),\n'
        '"etape" (le nom exact de l\'étape la plus avancée visible, choisi dans la liste),\n'
        '"confiance" (nombre entre 0 et 1),\n'
        '"description" (une phrase en français : ce qu\'on voit, et tout signe de fraude possible '
        "comme une photo d'écran ou un autre bâtiment).")})
    r = _call(content)
    return {
        "construction": bool(r.get("chantier", True)),
        "same_site": r.get("meme_chantier"),
        "step": str(r.get("etape") or "")[:80],
        "confidence": float(r.get("confiance") or 0),
        "description": str(r.get("description") or "")[:400],
    }


def read_invoice(raw, media_type):
    if media_type == "application/pdf":
        block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": base64.b64encode(raw).decode()}}
    else:
        block = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": _jpeg_b64(Image.open(io.BytesIO(raw)), 1600)}}
    r = _call([block, {"type": "text", "text": (
        "Lis cette facture de matériaux de construction. Réponds uniquement par un objet JSON :\n"
        '{"fournisseur": str, "numero": str, "date": "AAAA-MM-JJ", "total": nombre en FCFA,\n'
        ' "lignes": [{"materiau": str, "unite": str, "quantite": nombre, "prix_unitaire": nombre}]}\n'
        "Utilise null pour ce qui est illisible.")}], max_tokens=2000)
    lines = []
    for ln in r.get("lignes") or []:
        try:
            lines.append({"material": str(ln.get("materiau") or "")[:80], "unit": str(ln.get("unite") or "")[:20],
                          "qty": float(ln.get("quantite") or 0), "unit_price": float(ln.get("prix_unitaire") or 0)})
        except (TypeError, ValueError):
            continue
    return {"supplier": str(r.get("fournisseur") or "")[:120], "number": str(r.get("numero") or "")[:60],
            "date": str(r.get("date") or "")[:10], "total": float(r.get("total") or 0), "lines": lines}


# --------------------------------------------------------------------------
# Floutage des visages (photos publiees sur le portail citoyen)
# --------------------------------------------------------------------------
def blur_faces(img):
    """Pixelise les visages detectes. Retourne (image, nombre de visages, detection_disponible).
    Necessite opencv-python-headless ; sans lui, l'image est rendue telle quelle."""
    try:
        import cv2
    except ImportError:
        return img, 0, False
    rgb = np.asarray(img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    found, loaded = [], 0
    folder = getattr(getattr(cv2, "data", None), "haarcascades", "")
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        if not os.path.exists(os.path.join(folder, name)):
            continue
        casc = cv2.CascadeClassifier(os.path.join(folder, name))
        if not casc.empty():
            loaded += 1
            found += list(casc.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)))
    if not loaded:
        return img, 0, False
    out = rgb.copy()
    h, w = out.shape[:2]
    for (x, y, fw, fh) in found:
        m = int(max(fw, fh) * 0.25)
        x0, y0, x1, y1 = max(x - m, 0), max(y - m, 0), min(x + fw + m, w), min(y + fh + m, h)
        zone = out[y0:y1, x0:x1]
        small = cv2.resize(zone, (max(1, (x1 - x0) // 14), max(1, (y1 - y0) // 14)), interpolation=cv2.INTER_LINEAR)
        out[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    return Image.fromarray(out), len(found), True


def read_plan(raw, media_type):
    """Lit un plan d'architecte (image ou PDF) : pieces, surfaces, longueurs de murs, ouvertures.
    Ne lit que ce qui est ecrit sur le plan ; rien sur la structure porteuse."""
    if media_type == "application/pdf":
        block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": base64.b64encode(raw).decode()}}
    else:
        block = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": _jpeg_b64(Image.open(io.BytesIO(raw)), 1600)}}
    r = _call([block, {"type": "text", "text": (
        "Voici un plan d'architecte (plan de niveau). Lis uniquement ce qui est écrit ou mesurable sur le plan : "
        "cotes, surfaces indiquées, échelle. N'invente rien : mets null quand ce n'est pas lisible. "
        "Ne donne aucune information sur la structure porteuse (poteaux, ferraillage, fondations).\n"
        "Réponds uniquement par un objet JSON avec ces clés :\n"
        '"echelle" (texte, ex. "1/100", ou null), "niveaux" (nombre de niveaux représentés),\n'
        '"pieces" (liste d\'objets {"nom": texte, "surface_m2": nombre ou null}),\n'
        '"surface_totale_m2" (surface habitable totale), "longueur_murs_exterieurs_m", "longueur_murs_interieurs_m",\n'
        '"hauteur_sous_plafond_m" (si indiquée, sinon null), "portes" (nombre), "fenetres" (nombre),\n'
        '"confiance" (0 à 1), "remarques" (une phrase en français : ce qui est incertain).')}], max_tokens=1500)

    def num(x):
        try:
            v = float(x)
            return v if v >= 0 else None
        except (TypeError, ValueError):
            return None
    rooms = [{"name": str(p.get("nom") or "")[:60], "area": num(p.get("surface_m2"))}
             for p in (r.get("pieces") or [])[:60] if isinstance(p, dict)]
    return {"scale": (str(r["echelle"])[:20] if r.get("echelle") else None), "levels": int(num(r.get("niveaux")) or 1),
            "rooms": rooms, "floor_area": num(r.get("surface_totale_m2")) or (round(sum(x["area"] or 0 for x in rooms), 2) or None),
            "ext_walls": num(r.get("longueur_murs_exterieurs_m")), "int_walls": num(r.get("longueur_murs_interieurs_m")),
            "height": num(r.get("hauteur_sous_plafond_m")), "doors": int(num(r.get("portes")) or 0),
            "windows": int(num(r.get("fenetres")) or 0), "confidence": num(r.get("confiance")),
            "remarks": str(r.get("remarques") or "")[:400], "source": "ia"}


def compare_panos(img_before, img_after, zone_name):
    """Compare deux photos 360 de la meme zone : ce qui a avance, ce qui a change, ce qui semble anormal."""
    def pano(img):
        im = img.convert("RGB").resize((1600, 800))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(buf.getvalue()).decode()}}
    r = _call([{"type": "text", "text": f"Photo 360° équirectangulaire de la zone « {zone_name} », visite précédente :"},
               pano(img_before), {"type": "text", "text": "Même zone, visite récente :"}, pano(img_after),
               {"type": "text", "text": (
                   "Tu aides un propriétaire à suivre son chantier. Compare les deux visites. Ne déduis rien sur la solidité "
                   "de la structure. Réponds uniquement par un objet JSON : "
                   '"progres" (une phrase en français : ce qui a été réalisé entre les deux visites), '
                   '"changements" (liste de 5 éléments au plus, courts), '
                   '"a_verifier" (liste de 3 éléments au plus : ce qui mérite une vérification sur place, ou liste vide), '
                   '"meme_lieu" (true ou false : les deux photos montrent-elles le même endroit ?).')}], max_tokens=700)
    return {"progress": str(r.get("progres") or "")[:300],
            "changes": [str(x)[:120] for x in (r.get("changements") or [])[:5]],
            "check": [str(x)[:120] for x in (r.get("a_verifier") or [])[:3]],
            "same_place": r.get("meme_lieu")}
