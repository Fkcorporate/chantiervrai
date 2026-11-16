"""Attestation de l'appareil (applications natives) : prouve que la photo vient de la vraie
application ChantierVrai, installee depuis le store, sur un telephone non modifie.

Deroule : l'application demande un defi (nonce) au serveur, le fait signer par le systeme
(Play Integrity sur Android, App Attest sur iPhone) et l'envoie avec la photo.

Statuts enregistres sur la preuve :
  verifiee      appareil et application reconnus
  refusee       jeton invalide, defi incorrect, appareil modifie ou application non officielle
  non_verifiee  jeton recu mais verification non configuree sur ce serveur
  absente       aucun jeton (ancienne version de l'application, ou module natif absent)

Android (Play Integrity) - a configurer :
  PLAY_INTEGRITY_PACKAGE=ci.chantiervrai.app
  PLAY_INTEGRITY_SERVICE_ACCOUNT=/chemin/compte-de-service.json   (Google Cloud, API Play Integrity activee)
  Necessite le module Python « cryptography ».
iPhone (App Attest) : le jeton est enregistre. Sa verification (chaine de certificats Apple,
format CBOR) est a ajouter avec une bibliotheque dediee : le statut reste « non_verifiee ».
"""
import base64
import json
import time

from . import env, http_json

_google_token = {"value": None, "exp": 0}


def _google_access_token():
    if _google_token["value"] and _google_token["exp"] > time.time() + 60:
        return _google_token["value"]
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with open(env("PLAY_INTEGRITY_SERVICE_ACCOUNT"), encoding="utf-8") as fh:
        sa = json.load(fh)
    b64 = lambda d: base64.urlsafe_b64encode(d).rstrip(b"=")
    now = int(time.time())
    head = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = b64(json.dumps({"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/playintegrity",
                             "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600}).encode())
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = b64(key.sign(head + b"." + claims, padding.PKCS1v15(), hashes.SHA256()))
    code, body = http_json("https://oauth2.googleapis.com/token", {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": (head + b"." + claims + b"." + sig).decode()}, form=True)
    if code != 200:
        raise RuntimeError(f"Google OAuth : {code}")
    _google_token["value"], _google_token["exp"] = body["access_token"], now + int(body.get("expires_in", 3600))
    return _google_token["value"]


def _verify_android(token, nonce):
    pkg = env("PLAY_INTEGRITY_PACKAGE")
    code, body = http_json(f"https://playintegrity.googleapis.com/v1/{pkg}:decodeIntegrityToken",
                           {"integrity_token": token}, headers={"Authorization": f"Bearer {_google_access_token()}"})
    if code != 200 or not isinstance(body, dict):
        return "refusee"
    p = body.get("tokenPayloadExternal", {})
    ok_nonce = p.get("requestDetails", {}).get("nonce", "").rstrip("=") == nonce.rstrip("=")
    ok_pkg = p.get("requestDetails", {}).get("requestPackageName") == pkg
    ok_app = p.get("appIntegrity", {}).get("appRecognitionVerdict") == "PLAY_RECOGNIZED"
    ok_dev = "MEETS_DEVICE_INTEGRITY" in p.get("deviceIntegrity", {}).get("deviceRecognitionVerdict", [])
    return "verifiee" if ok_nonce and ok_pkg and ok_app and ok_dev else "refusee"


def verify(platform, token, nonce):
    if not token:
        return "absente"
    if not nonce:
        return "refusee"
    try:
        if platform == "android" and env("PLAY_INTEGRITY_PACKAGE") and env("PLAY_INTEGRITY_SERVICE_ACCOUNT"):
            return _verify_android(token, nonce)
    except Exception:
        return "non_verifiee"          # service injoignable : on n'accuse pas l'utilisateur
    return "non_verifiee"
