"""Envoi des webhooks : POST JSON signe HMAC-SHA256, avec horodatage contre le rejeu.

En-tetes : X-ChantierVrai-Event, X-ChantierVrai-Delivery, X-ChantierVrai-Timestamp,
X-ChantierVrai-Signature: sha256=<hex de HMAC(secret, timestamp + "." + corps)>.
"""
import hashlib
import hmac
import ipaddress
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

EVENTS = {
    "etape.declaree": "Étape déclarée terminée par le chef de chantier",
    "etape.validee": "Étape validée : bon à payer émis (paiement suivi)",
    "etape.payee": "Étape validée et payée",
    "paiement.declare": "Paiement déclaré par le payeur, avec référence ou reçu",
    "paiement.confirme": "Paiement confirmé par le bénéficiaire",
    "paiement.conteste": "Paiement contesté par le bénéficiaire",
    "preuve.verifiee": "Preuve photo vérifiée",
    "preuve.refusee": "Preuve photo refusée",
    "controle.resultat": "Résultat d'un contrôle technique",
    "anomalie": "Anomalie : capteur hors seuil, non-conformité, écart d'inventaire",
    "commande.receptionnee": "Commande de matériaux reçue",
    "quantite.validee": "Quantité installée validée",
}
BACKOFF_MIN = [1, 5, 30, 120, 360, 720]


def signature(secret, timestamp, body):
    return "sha256=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def url_ok(url, allow_local=False):
    """https obligatoire, et pas d'adresse interne (protection contre les requetes vers le reseau du serveur)."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme != "https" and not (allow_local and u.scheme == "http"):
        return False
    host = u.hostname or ""
    if not host or host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        return allow_local
    try:
        ip = ipaddress.ip_address(host)
        return allow_local or ip.is_global
    except ValueError:
        return True


def resolves_public(url):
    try:
        host = urlparse(url).hostname
        return all(ipaddress.ip_address(info[4][0]).is_global for info in socket.getaddrinfo(host, None))
    except Exception:
        return False


def send(url, body, headers, timeout=8):
    """Retourne le code HTTP (0 si injoignable)."""
    if not resolves_public(url):
        return 0
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json",
                                                                         "User-Agent": "ChantierVrai-Webhook/1", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0
