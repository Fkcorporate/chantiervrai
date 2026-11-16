"""Paiements : depot sur le compte sequestre et versement au chef de chantier.

- Sans configuration : mode SIMULATION. Les depots et versements sont
  confirmes immediatement et marques « simulation » partout dans l'interface.
- Avec CinetPay (agregateur Mobile Money : Wave, Orange Money, MTN, Moov) :
    CINETPAY_APIKEY, CINETPAY_SITE_ID          -> encaissement (depot du proprietaire)
    CINETPAY_TRANSFER_PASSWORD                 -> versement (API de transfert)
    PUBLIC_URL (ex. https://chantiervrai.ci)   -> adresses de retour et de notification

Important : garder l'argent du proprietaire avant de le verser au chef de
chantier est une activite de sequestre. En production, le compte marchand doit
etre ouvert au nom d'un partenaire agree (banque ou etablissement de paiement)
qui detient les fonds. A valider aussi dans l'environnement de test CinetPay
avant toute mise en service : les noms de champs de l'API de transfert.
"""
from . import env, http_json
from .i18n import _

CHECKOUT = "https://api-checkout.cinetpay.com/v2"
TRANSFER = "https://client.cinetpay.com/v1"


class SimulationProvider:
    name = "simulation"
    label = "Simulation (aucun argent réel)"
    real = False

    def deposit(self, tx_id, amount, description, return_url, notify_url):
        return {"status": "reussi", "provider_ref": f"SIM-D-{tx_id}", "payment_url": None}

    def check(self, tx_id):
        return "reussi"

    def payout(self, tx_id, amount, phone, name, notify_url):
        if not phone:
            return {"status": "echoue", "error": _("Le chef de chantier n'a pas de numéro Mobile Money.")}
        return {"status": "reussi", "provider_ref": f"SIM-V-{tx_id}"}


class CinetPayProvider:
    name = "cinetpay"
    label = "CinetPay (Mobile Money)"
    real = True

    def __init__(self):
        self.apikey = env("CINETPAY_APIKEY")
        self.site_id = env("CINETPAY_SITE_ID")
        self.transfer_password = env("CINETPAY_TRANSFER_PASSWORD")

    def deposit(self, tx_id, amount, description, return_url, notify_url):
        code, body = http_json(f"{CHECKOUT}/payment", {
            "apikey": self.apikey, "site_id": self.site_id, "transaction_id": tx_id,
            "amount": int(amount), "currency": "XOF", "description": description[:200],
            "return_url": return_url, "notify_url": notify_url, "channels": "ALL",
        })
        if isinstance(body, dict) and body.get("code") == "201":
            return {"status": "en_attente", "provider_ref": tx_id,
                    "payment_url": body["data"]["payment_url"]}
        return {"status": "echoue", "error": _err(body)}

    def check(self, tx_id):
        _, body = http_json(f"{CHECKOUT}/payment/check", {
            "apikey": self.apikey, "site_id": self.site_id, "transaction_id": tx_id})
        status = (body.get("data") or {}).get("status") if isinstance(body, dict) else None
        if status == "ACCEPTED":
            return "reussi"
        if status in ("REFUSED", "CANCELED"):
            return "echoue"
        return "en_attente"

    def _token(self):
        _, body = http_json(f"{TRANSFER}/auth/login",
                            {"apikey": self.apikey, "password": self.transfer_password}, form=True)
        return (body.get("data") or {}).get("token") if isinstance(body, dict) else None

    def payout(self, tx_id, amount, phone, name, notify_url):
        if not self.transfer_password:
            return {"status": "echoue", "error": _('CINETPAY_TRANSFER_PASSWORD manquant : versement à faire à la main.')}
        prefix, local = split_phone(phone)
        if not local:
            return {"status": "echoue", "error": _('Numéro Mobile Money du chef de chantier manquant.')}
        token = self._token()
        if not token:
            return {"status": "echoue", "error": _("Connexion à l'API de transfert CinetPay impossible.")}
        import json
        contact = [{"prefix": prefix, "phone": local, "name": name or "Chef", "surname": "chantier",
                    "email": "chef@chantiervrai.local"}]
        http_json(f"{TRANSFER}/transfer/contact?token={token}&lang=fr",
                  {"data": json.dumps(contact)}, form=True)
        amount = int(amount) - int(amount) % 5          # CinetPay : multiple de 5
        send = [{"prefix": prefix, "phone": local, "amount": amount,
                 "client_transaction_id": tx_id, "notify_url": notify_url}]
        _, body = http_json(f"{TRANSFER}/transfer/money/send/contact?token={token}&lang=fr",
                            {"data": json.dumps(send)}, form=True)
        if isinstance(body, dict) and str(body.get("code")) == "0":
            return {"status": "en_attente", "provider_ref": tx_id}
        return {"status": "echoue", "error": _err(body)}


def split_phone(phone):
    """'+225 07 00 00 00 00' -> ('225', '0700000000'). Indicatif par defaut : DEFAULT_COUNTRY_CODE."""
    digits = "".join(c for c in (phone or "") if c.isdigit() or c == "+")
    cc = env("DEFAULT_COUNTRY_CODE", "225")
    if digits.startswith("+"):
        d = digits[1:]
        for n in (3, 2, 1):
            if d[:n] == cc:
                return cc, d[n:]
        return d[:3], d[3:]
    if digits.startswith("00"):
        return digits[2:5], digits[5:]
    return cc, digits


def _err(body):
    if isinstance(body, dict):
        return str(body.get("message") or body.get("description") or body)[:200]
    return str(body)[:200]


def get_provider():
    if env("CINETPAY_APIKEY") and env("CINETPAY_SITE_ID"):
        return CinetPayProvider()
    return SimulationProvider()
