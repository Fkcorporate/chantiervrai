"""Services externes de ChantierVrai.

Chaque service fonctionne sans configuration (mode simulation ou fonction
locale) et passe sur le vrai fournisseur des que ses variables
d'environnement sont renseignees.
"""
import json
import os
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30


def env(name, default=""):
    return os.environ.get(name, default).strip()


def http_json(url, payload=None, headers=None, method=None, form=False, auth=None, timeout=TIMEOUT):
    """Petit client HTTP sans dependance. Retourne (code, corps decode)."""
    headers = dict(headers or {})
    data = None
    if payload is not None:
        if form:
            data = urllib.parse.urlencode(payload).encode()
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            data = json.dumps(payload).encode()
            headers.setdefault("Content-Type", "application/json")
    if auth:
        import base64
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            raw = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    ctype_json = raw[:1] in (b"{", b"[")
    return code, (json.loads(raw) if ctype_json else raw)


def run_async(fn, *args, **kwargs):
    """Lance une tache en arriere-plan (synchrone si CV_SYNC=1, utile pour les tests)."""
    if env("CV_SYNC") == "1":
        return fn(*args, **kwargs)
    t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t
