"""Securite des comptes : double authentification (TOTP), codes de secours, mots de passe."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

COMMON = {"12345678", "123456789", "1234567890", "azertyuiop", "motdepasse", "password", "password1", "qwertyuiop",
          "00000000", "11111111", "abcdefgh", "iloveyou", "azerty123", "chantier", "abidjan1", "bonjour1"}


def password_problem(pw, email=""):
    """Retourne un message si le mot de passe est trop faible, sinon None."""
    if len(pw) < 8:
        return "Le mot de passe doit faire au moins 8 caractères."
    low = pw.lower()
    if low in COMMON or low.rstrip("0123456789!") in COMMON:
        return "Ce mot de passe est trop courant."
    if pw.isdigit():
        return "Utilisez des lettres en plus des chiffres."
    if email and email.split("@")[0].lower() in low and len(email.split("@")[0]) > 3:
        return "Le mot de passe ne doit pas contenir votre e-mail."
    return None


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def totp_now(secret, at=None):
    return _code(secret, int((at or time.time()) // 30))


def totp_ok(secret, code, at=None):
    code = "".join(c for c in (code or "") if c.isdigit())
    if len(code) != 6 or not secret:
        return False
    t = int((at or time.time()) // 30)
    return any(hmac.compare_digest(_code(secret, t + d), code) for d in (-1, 0, 1))


def otpauth_uri(secret, email, issuer="ChantierVrai"):
    label = urllib.parse.quote(f"{issuer}:{email}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(issuer)}&digits=6&period=30"


def backup_codes(n=8):
    return [f"{secrets.randbelow(10**8):08d}" for _ in range(n)]


def hash_code(code):
    return hashlib.sha256(("cv-backup:" + "".join(c for c in code if c.isdigit())).encode()).hexdigest()


def group(secret):
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
