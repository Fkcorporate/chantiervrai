"""Comptage des livraisons et des elements du plan sur les photos.

Trois chiffres compares : la quantite commandee (ou prevue au plan), celle comptee par l'IA sur la photo guidee,
celle declaree par le chef. Un ecart au-dela de la tolerance est signale au proprietaire avant le paiement.
L'IA (ANTHROPIC_API_KEY) ne compte que ce qu'elle voit ; sans elle, la comparaison se fait entre commande et chef.
"""
import json
import re

from . import env, http_json
from .quality import _b64

API = "https://api.anthropic.com/v1/messages"
MIN_CONFIDENCE = 0.6          # en dessous, le comptage de l'IA est affiche mais ne bloque rien


def t(fr, en):
    return {"fr": fr, "en": en}


def _p(d, lang):
    return (d or {}).get(lang) or (d or {}).get("fr") or ""


GUIDES = {
    "Ciment": t("Rangez les sacs en rangées régulières, une pile par rangée, et photographiez de face puis de dessus : chaque sac doit se voir.",
                "Stack the bags in regular rows and photograph from the front then from above: every bag must show."),
    "Fer à béton": t("Photographiez les bottes par le bout, de face et de près : chaque extrémité de barre doit être visible.",
                     "Photograph the bundles end-on, close up: every bar end must be visible."),
    "Parpaings": t("Rangées régulières : une photo de face de la pile et une de côté pour compter les rangs en hauteur.",
                   "Regular rows: one photo of the stack from the front and one from the side to count the courses."),
    "Tôles": t("Photographiez la tranche de la pile, de près : chaque tôle doit se voir.", "Photograph the edge of the stack, close up: every sheet must show."),
    "Bois de coffrage": t("Photographiez les planches par le bout, de face.", "Photograph the boards end-on, from the front."),
    "Carreaux": t("Cartons empilés, étiquettes tournées vers l'appareil.", "Stacked boxes, labels facing the camera."),
    "Sable": t("Volume : photographiez le camion chargé, benne visible, avant de décharger. Le nombre de voyages compte.",
               "Volume: photograph the loaded truck, bed visible, before unloading. The number of trips counts."),
    "Gravier": t("Volume : photographiez le camion chargé, benne visible, avant de décharger. Le nombre de voyages compte.",
                 "Volume: photograph the loaded truck, bed visible, before unloading. The number of trips counts."),
}
DEFAULT_GUIDE = t("Étalez ou alignez les articles pour que chacun soit visible, puis photographiez de face.",
                  "Spread or line up the items so each one shows, then photograph from the front.")
VOLUME = ("Sable", "Gravier")


def guide(material, lang):
    return _p(GUIDES.get(material, DEFAULT_GUIDE), lang)


def tolerance(expected):
    """Petites quantites (portes, poteaux) : au chiffre pres. Grosses livraisons (sacs, agglos) : 2 %."""
    n = expected or 0
    return 0.5 if n < 50 else max(1.0, 0.02 * n)


def compare(expected, declared, ai=None, ai_conf=None):
    """Statut d'une ligne : ok, ecart (le chef declare autre chose que prevu) ou a_verifier (l'IA contredit le chef)."""
    if declared is None:
        return "a_faire"
    tol = tolerance(expected)
    if ai is not None and (ai_conf or 0) >= MIN_CONFIDENCE and abs(ai - declared) > tolerance(declared):
        return "a_verifier"
    if expected is not None and abs(declared - expected) > tol:
        return "ecart"
    return "ok"


def ai_enabled():
    return bool(env("ANTHROPIC_API_KEY"))


def count(images, items, context, lang="fr"):
    """items : [{"id", "nom", "unite", "attendu"}]. Retourne {id: {"compte", "confiance", "methode", "remarque"}} et une remarque."""
    content = []
    for i, img in enumerate(images):
        content += [{"type": "text", "text": f"Photo {i} :"},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(img)}}]
    lines = "\n".join(f"- {x['id']} : {x['nom']} ({x['unite']})" for x in items)
    content.append({"type": "text", "text": (
        f"{context}\nCompte sur les photos les éléments suivants :\n{lines}\n"
        "Règles : compte uniquement ce qui est visible. Si une pile cache des éléments, compte les rangées et les colonnes "
        "visibles et dis-le dans « methode » ; baisse alors la confiance. Si un élément n'est pas sur les photos, mets null. "
        "Ne recopie jamais la quantité attendue : tu ne la connais pas.\n"
        f"Réponds uniquement par un objet JSON, textes en {'anglais' if lang == 'en' else 'français'} : "
        '{"elements": [{"id": "<id>", "compte": nombre ou null, "confiance": 0..1, "methode": "...", "remarque": "..."}], '
        '"remarque": "une phrase sur la qualité des photos pour compter"}')})
    code, body = http_json(API, {"model": env("AI_MODEL", "claude-sonnet-5-5"), "max_tokens": 1500,
                                 "messages": [{"role": "user", "content": content}]},
                           headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}, timeout=120)
    if code != 200 or not isinstance(body, dict):
        raise RuntimeError(f"Comptage : {code}")
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    r = json.loads(m.group(0)) if m else {}
    out = {}
    for e in r.get("elements") or []:
        if not isinstance(e, dict):
            continue
        try:
            n = None if e.get("compte") is None else float(e["compte"])
        except (TypeError, ValueError):
            n = None
        out[str(e.get("id"))] = {"compte": n, "confiance": max(0.0, min(1.0, float(e.get("confiance") or 0))),
                                 "methode": str(e.get("methode") or "")[:200], "remarque": str(e.get("remarque") or "")[:300]}
    return out, str(r.get("remarque") or "")[:300]
