"""Notes vocales du chantier : transcription puis resume.

Transcription : OPENAI_API_KEY (modele TRANSCRIBE_MODEL, whisper-1 par defaut), langue detectee.
Resume et classement : ANTHROPIC_API_KEY (AI_MODEL). Sans cle, la note est gardee et ecoutable telle quelle.
"""
import json
import re
import secrets
import urllib.error
import urllib.request

from . import env, http_json

CATEGORIES = ("avancement", "probleme", "materiaux", "question", "autre")
CATEGORY_LABEL = {"avancement": {"fr": "Avancement", "en": "Progress"}, "probleme": {"fr": "Problème", "en": "Problem"},
                  "materiaux": {"fr": "Matériaux", "en": "Materials"}, "question": {"fr": "Question", "en": "Question"},
                  "autre": {"fr": "Autre", "en": "Other"}}


def can_transcribe():
    return bool(env("OPENAI_API_KEY"))


def transcribe(raw, filename="note.ogg", content_type="audio/ogg"):
    """Texte de la note vocale, ou None sans service configure."""
    if not can_transcribe():
        return None
    boundary = "----cv" + secrets.token_hex(8)
    parts = []
    for name, value in (("model", env("TRANSCRIBE_MODEL", "whisper-1")),):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n".encode() + raw + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", data=b"".join(parts), method="POST",
                                 headers={"Authorization": "Bearer " + env("OPENAI_API_KEY"),
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read())
    except (urllib.error.URLError, ValueError) as e:
        raise RuntimeError(f"Transcription : {e}")
    return (body.get("text") or "").strip() or None


def summarise(text, project_name, step_name, lang="fr"):
    """{resume, categorie, urgent, materiaux} a partir de la transcription. Sans IA : debut du texte."""
    text = (text or "").strip()
    if not text:
        return None
    if not env("ANTHROPIC_API_KEY"):
        return simple(text)
    prompt = (f"Note vocale d'un chef de chantier (chantier « {project_name} », étape « {step_name} »), transcrite :\n\n{text}\n\n"
              "Réponds uniquement par un objet JSON : "
              f'{{"resume": "1 ou 2 phrases claires pour le propriétaire, en {"anglais" if lang == "en" else "français"}", '
              '"categorie": "avancement"|"probleme"|"materiaux"|"question"|"autre", '
              '"urgent": true|false (accident, danger, arrêt du chantier, décision attendue sous 48 h), '
              '"materiaux": [{"materiau": "...", "quantite": "..."}] (besoins ou livraisons cités)}')
    code, body = http_json("https://api.anthropic.com/v1/messages",
                           {"model": env("AI_MODEL", "claude-sonnet-5-5"), "max_tokens": 500,
                            "messages": [{"role": "user", "content": prompt}]},
                           headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}, timeout=60)
    if code != 200 or not isinstance(body, dict):
        raise RuntimeError(f"Résumé : {code}")
    out = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    r = json.loads(m.group(0)) if m else {}
    cat = r.get("categorie") if r.get("categorie") in CATEGORIES else guess_category(text)
    return {"resume": str(r.get("resume") or text[:220])[:600], "categorie": cat, "urgent": bool(r.get("urgent")),
            "materiaux": [x for x in (r.get("materiaux") or []) if isinstance(x, dict)][:10]}


def simple(text):
    """Resume sans IA : debut du texte, categorie et urgence devinees par mots-cles."""
    text = (text or "").strip()
    short = text if len(text) <= 220 else text[:217].rsplit(" ", 1)[0] + "…"
    return {"resume": short, "categorie": guess_category(text),
            "urgent": bool(re.search(r"urgent|accident|bless|effondr|danger|injur|collapse", text, re.I)), "materiaux": []}


def guess_category(text):
    t = text.lower()
    if re.search(r"probl|fissur|fuite|cass|retard|pluie|bless|accident|manque", t):
        return "probleme"
    if re.search(r"ciment|sac|fer|agglo|sable|gravier|livr|command|tôle|tole", t):
        return "materiaux"
    if "?" in t:
        return "question"
    if re.search(r"fini|termin|coul|mont|pos|avanc", t):
        return "avancement"
    return "autre"
