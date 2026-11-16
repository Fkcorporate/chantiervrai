"""Envoi des notifications : WhatsApp, SMS, e-mail.

Sans configuration, les messages sont seulement enregistres (statut
« simulé ») et visibles dans l'onglet Notifications de l'application.

WhatsApp et SMS via Twilio :
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
    TWILIO_SMS_FROM        (ex. +15005550006)
    TWILIO_WHATSAPP_FROM   (ex. +14155238886, numero WhatsApp Business valide)
E-mail via SMTP :
    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
Indicatif ajoute aux numeros locaux : DEFAULT_COUNTRY_CODE (225 par defaut).
"""
import smtplib
from email.message import EmailMessage

from . import env, http_json
from .payments import split_phone


def e164(phone):
    cc, local = split_phone(phone)
    if not local:
        return None
    return f"+{cc}{local}"


def configured(channel):
    if channel in ("sms", "whatsapp"):
        base = env("TWILIO_ACCOUNT_SID") and env("TWILIO_AUTH_TOKEN")
        return bool(base and env("TWILIO_SMS_FROM" if channel == "sms" else "TWILIO_WHATSAPP_FROM"))
    if channel == "email":
        return bool(env("SMTP_HOST") and env("SMTP_FROM"))
    return False


def send(channel, user, title, body, link=None):
    """Envoie un message. Retourne (statut, detail) avec statut in envoye|simule|echec."""
    text = f"ChantierVrai – {title}\n{body}" + (f"\n{link}" if link else "")
    if channel in ("sms", "whatsapp"):
        to = e164(user["phone"])
        if not to:
            return "echec", "Pas de numéro de téléphone"
        if not configured(channel):
            return "simule", f"À {to} (Twilio non configuré)"
        sid, tok = env("TWILIO_ACCOUNT_SID"), env("TWILIO_AUTH_TOKEN")
        if channel == "whatsapp":
            frm, to = "whatsapp:" + env("TWILIO_WHATSAPP_FROM"), "whatsapp:" + to
        else:
            frm = env("TWILIO_SMS_FROM")
        try:
            code, resp = http_json(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                                   {"From": frm, "To": to, "Body": text[:1500]}, form=True, auth=(sid, tok))
        except Exception as e:  # reseau
            return "echec", str(e)[:200]
        if code in (200, 201):
            return "envoye", resp.get("sid", "") if isinstance(resp, dict) else ""
        return "echec", (resp.get("message") if isinstance(resp, dict) else str(resp))[:200]
    if channel == "email":
        if not user["email"]:
            return "echec", "Pas d'e-mail"
        if not configured("email"):
            return "simule", f"À {user['email']} (SMTP non configuré)"
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = f"ChantierVrai – {title}", env("SMTP_FROM"), user["email"]
        msg.set_content(text)
        try:
            with smtplib.SMTP(env("SMTP_HOST"), int(env("SMTP_PORT", "587")), timeout=20) as s:
                s.starttls()
                if env("SMTP_USER"):
                    s.login(env("SMTP_USER"), env("SMTP_PASSWORD"))
                s.send_message(msg)
            return "envoye", ""
        except Exception as e:
            return "echec", str(e)[:200]
    return "echec", "Canal inconnu"


def send_push(tokens, title, body, data=None):
    """Notification sur le telephone (application mobile) via le service de push d'Expo.
    Actif par defaut ; EXPO_PUSH=0 pour le couper. EXPO_ACCESS_TOKEN si la securite renforcee est activee chez Expo."""
    if not tokens:
        return "echec", "Aucun appareil"
    if env("EXPO_PUSH", "1") == "0":
        return "simule", f"{len(tokens)} appareil(s) (push désactivé)"
    headers = {"Accept": "application/json"}
    if env("EXPO_ACCESS_TOKEN"):
        headers["Authorization"] = f"Bearer {env('EXPO_ACCESS_TOKEN')}"
    msgs = [{"to": t, "title": title[:120], "body": body[:500], "data": data or {}, "sound": "default"} for t in tokens]
    try:
        code, resp = http_json("https://exp.host/--/api/v2/push/send", msgs, headers=headers)
    except Exception as e:
        return "echec", str(e)[:200]
    if code == 200:
        return "envoye", ""
    return "echec", str(resp)[:200]
