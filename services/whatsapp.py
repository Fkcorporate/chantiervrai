"""WhatsApp pour le chef de chantier : il envoie photos, position et notes vocales dans un fil WhatsApp.

Transport : Twilio (le meme compte que les alertes WhatsApp sortantes).
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
    Dans la console Twilio, l'adresse « A message comes in » du numero WhatsApp pointe vers
    https://<votre-domaine>/whatsapp/entrant (methode POST).
    TWILIO_WEBHOOK_URL : adresse publique exacte de ce webhook si l'application est derriere un proxy
    (sert a verifier la signature X-Twilio-Signature).
Sans configuration : simulateur integre (/whatsapp/simulateur), memes regles, memes reponses.

Limite assumee : WhatsApp retire la position et la date des photos. La position est donc celle que le chef
partage dans le fil (moins de 30 minutes avant ou apres la photo) et la date celle de la reception. Ces preuves
sont marquees « recues par WhatsApp » ; un chantier qui exige la camera de l'application les refuse.
"""
import base64
import hashlib
import hmac
import re
import unicodedata
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

from . import env

LOCATION_MINUTES = 30            # ecart maximal entre la photo et la position partagee
PENDING_MAX = 10                 # photos gardees en attente de position


def configured():
    return bool(env("TWILIO_ACCOUNT_SID") and env("TWILIO_AUTH_TOKEN") and env("TWILIO_WHATSAPP_FROM"))


def display_number():
    return env("WHATSAPP_DISPLAY_NUMBER") or env("TWILIO_WHATSAPP_FROM")


def wa_link():
    n = re.sub(r"\D", "", display_number() or "")
    return f"https://wa.me/{n}" if n else None


def norm(text):
    """Minuscules, sans accents ni ponctuation : « Terminé ! » -> « termine »."""
    t = unicodedata.normalize("NFD", (text or "").strip().lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


COMMANDS = {
    "aide": ("aide", "menu", "help", "bonjour", "salut", "hello", "hi", "start", "commencer"),
    "chantiers": ("chantier", "chantiers", "site", "sites", "projet", "projets"),
    "etape": ("etape", "etapes", "ou en est", "avancement", "stage", "status", "statut"),
    "termine": ("termine", "terminee", "fini", "finie", "fin", "done", "finished", "etape terminee"),
    "oui": ("oui", "o", "yes", "y", "ok", "confirme", "confirmer"),
    "non": ("non", "n", "no", "annuler", "cancel"),
    "paiements": ("paiement", "paiements", "payment", "payments", "argent", "paye"),
}


def command(text):
    """(commande, argument) reconnus dans un message texte, ou (None, texte)."""
    n = norm(text)
    if re.fullmatch(r"\d{1,2}", n):
        return "numero", int(n)
    m = re.fullmatch(r"(recu|received|reçu)\s+(\d+)", n)
    if m:
        return "recu", int(m.group(2))
    m = re.fullmatch(r"(probleme|problem)\s+(\d+)\s*(.*)", n)
    if m:
        return "probleme", (int(m.group(2)), text.split(None, 2)[2] if len(text.split(None, 2)) > 2 else "")
    for cmd, words in COMMANDS.items():
        if n in words:
            return cmd, None
    return None, text


TEXTS = {
    "fr": {
        "inconnu": "Bonjour. Ce numéro n'est lié à aucun compte ChantierVrai. Créez un compte « Chef de chantier » avec ce numéro de téléphone, rejoignez votre chantier avec le code du propriétaire, puis écrivez-nous à nouveau.",
        "pas_chef": "Votre compte ChantierVrai n'est chef d'aucun chantier en cours. Rejoignez d'abord le chantier avec le code donné par le propriétaire.",
        "aide": "ChantierVrai – {chantier}\n• Envoyez vos photos du chantier.\n• Partagez votre position (📎 > Position) quand vous êtes sur le terrain : elle valide les photos.\n• Envoyez une note vocale pour expliquer l'avancement ou un problème.\nCommandes : ETAPE (où en est le chantier), TERMINE (déclarer l'étape finie), PAIEMENTS, CHANTIER (changer de chantier), AIDE.",
        "choisir": "Vous suivez plusieurs chantiers. Répondez par le numéro :\n{liste}",
        "choisi": "Chantier choisi : {chantier}. Envoyez vos photos et partagez votre position.",
        "position_ok": "Position reçue ({d} m du terrain).",
        "position_loin": "Position reçue, mais à {d} m du terrain (limite {r} m) : les photos seront refusées. Prenez-les sur le chantier.",
        "attente_position": "Photo reçue. Pour la valider, partagez votre position maintenant (📎 > Position > Envoyer ma position actuelle). Vous avez {m} minutes.",
        "photo_ok": "✅ Photo vérifiée et envoyée au propriétaire ({etape}).",
        "photo_suspect": "⚠️ Photo envoyée, mais elle ressemble beaucoup à une photo déjà envoyée : le propriétaire va la comparer.",
        "photo_refusee": "❌ Photo refusée : {raisons}.",
        "photo_expiree": "❌ {n} photo(s) sans position partagée à temps : renvoyez-les depuis le chantier avec votre position.",
        "video": "Les vidéos ne sont pas acceptées par WhatsApp. Filmez depuis l'application ChantierVrai.",
        "pas_etape": "Aucune étape en cours n'accepte de photo sur ce chantier.",
        "etape": "{chantier}\nÉtape en cours : {etape} ({statut})\nPhotos vérifiées pour cette étape : {n}\nMontant à la validation : {montant} FCFA",
        "termine_confirmer": "Déclarer « {etape} » terminée ? Le propriétaire sera prévenu pour vérifier et payer. Répondez OUI pour confirmer, NON pour annuler.",
        "rien_a_confirmer": "Rien à confirmer. Écrivez AIDE pour voir les commandes.",
        "annule": "Annulé.",
        "vocal_ok": "🎙️ Note vocale reçue et transmise au propriétaire.{resume}",
        "vocal_sans_texte": "🎙️ Note vocale reçue et transmise au propriétaire (transcription non disponible).",
        "note_ok": "📝 Message transmis au propriétaire.",
        "paiements": "Paiements à confirmer :\n{liste}\nRépondez RECU <numéro> quand l'argent est arrivé, ou PROBLEME <numéro> <explication>.",
        "paiements_aucun": "Aucun paiement en attente de votre confirmation.",
        "paiement_inconnu": "Paiement n° {n} introuvable ou déjà traité.",
        "media_erreur": "Le fichier n'a pas pu être récupéré. Renvoyez-le.",
    },
    "en": {
        "inconnu": "Hello. This number is not linked to any ChantierVrai account. Create a “Site foreman” account with this phone number, join your site with the owner's code, then write to us again.",
        "pas_chef": "Your ChantierVrai account is not foreman of any ongoing site. First join the site with the code given by the owner.",
        "aide": "ChantierVrai – {chantier}\n• Send your site photos.\n• Share your location (📎 > Location) when you are on site: it validates the photos.\n• Send a voice note to explain progress or a problem.\nCommands: STAGE (site status), DONE (declare the stage finished), PAYMENTS, SITE (switch site), HELP.",
        "choisir": "You follow several sites. Reply with the number:\n{liste}",
        "choisi": "Site selected: {chantier}. Send your photos and share your location.",
        "position_ok": "Location received ({d} m from the plot).",
        "position_loin": "Location received, but {d} m from the plot (limit {r} m): photos will be rejected. Take them on site.",
        "attente_position": "Photo received. To validate it, share your location now (📎 > Location > Send your current location). You have {m} minutes.",
        "photo_ok": "✅ Photo verified and sent to the owner ({etape}).",
        "photo_suspect": "⚠️ Photo sent, but it looks very similar to a photo already sent: the owner will compare them.",
        "photo_refusee": "❌ Photo rejected: {raisons}.",
        "photo_expiree": "❌ {n} photo(s) without a location shared in time: send them again from the site with your location.",
        "video": "Videos are not accepted through WhatsApp. Film from the ChantierVrai app.",
        "pas_etape": "No ongoing stage accepts photos on this site.",
        "etape": "{chantier}\nCurrent stage: {etape} ({statut})\nVerified photos for this stage: {n}\nAmount on approval: {montant} FCFA",
        "termine_confirmer": "Declare “{etape}” finished? The owner will be notified to check and pay. Reply YES to confirm, NO to cancel.",
        "rien_a_confirmer": "Nothing to confirm. Write HELP to see the commands.",
        "annule": "Cancelled.",
        "vocal_ok": "🎙️ Voice note received and passed on to the owner.{resume}",
        "vocal_sans_texte": "🎙️ Voice note received and passed on to the owner (transcription not available).",
        "note_ok": "📝 Message passed on to the owner.",
        "paiements": "Payments to confirm:\n{liste}\nReply RECEIVED <number> when the money has arrived, or PROBLEM <number> <explanation>.",
        "paiements_aucun": "No payment awaiting your confirmation.",
        "paiement_inconnu": "Payment no. {n} not found or already handled.",
        "media_erreur": "The file could not be retrieved. Send it again.",
    },
}


def say(lang, key, **kw):
    return TEXTS.get(lang if lang in TEXTS else "fr", TEXTS["fr"])[key].format(**kw)


def twiml(messages):
    body = "".join(f"<Message>{escape(m)}</Message>" for m in messages if m)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def valid_signature(url, params, signature):
    """Signature Twilio : HMAC-SHA1 de l'adresse suivie des parametres tries (cle puis valeur)."""
    token = env("TWILIO_AUTH_TOKEN")
    if not token or not signature:
        return False
    data = url + "".join(k + v for k, v in sorted(params.items()))
    digest = base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(digest, signature)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch_media(url, max_bytes=20 * 1024 * 1024):
    """Telecharge un media Twilio : authentifie sur api.twilio.com, puis l'adresse signee sans authentification."""
    sid, tok = env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN")
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=30) as r:
            return r.read(max_bytes), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            with urllib.request.urlopen(e.headers["Location"], timeout=30) as r:
                return r.read(max_bytes), r.headers.get("Content-Type", "")
        raise


def phone_from(value):
    """« whatsapp:+2250700000000 » -> « +2250700000000 »."""
    return (value or "").replace("whatsapp:", "").strip()
