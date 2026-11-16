"""Copie des sauvegardes hors du serveur, vers un stockage compatible S3 :
Cloudflare R2, Backblaze B2, AWS S3, Scaleway, OVH, MinIO…

Aucune dépendance : les requêtes sont signées ici (AWS Signature Version 4), avec `requests`.

Configuration (variables d'environnement) :
    OFFSITE_ENDPOINT   https://<compte>.r2.cloudflarestorage.com   (ou https://s3.eu-west-3.amazonaws.com…)
    OFFSITE_BUCKET     nom du bucket (privé)
    OFFSITE_KEY_ID     identifiant de la clé d'accès
    OFFSITE_SECRET     secret de la clé d'accès
    OFFSITE_REGION     région (« auto » pour R2 ; us-east-1 par défaut)
    OFFSITE_PREFIX     dossier dans le bucket (chantiervrai/ par défaut)
Adresses « par chemin » (endpoint/bucket/clé), acceptées par tous ces fournisseurs.
"""
import datetime as _dt
import hashlib
import hmac
import os
import re
from urllib.parse import quote, urlsplit

EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


def configured():
    return all(env(k) for k in ("OFFSITE_ENDPOINT", "OFFSITE_BUCKET", "OFFSITE_KEY_ID", "OFFSITE_SECRET"))


def prefix():
    p = env("OFFSITE_PREFIX", "chantiervrai/").lstrip("/")
    return p if not p or p.endswith("/") else p + "/"


# ---------------------------------------------------------------------------
# Signature AWS Version 4
# ---------------------------------------------------------------------------
def _h(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def uri_encode(path):
    """Encodage S3 du chemin : tout sauf les caractères non réservés et « / »."""
    return quote(path, safe="/-_.~")


def sign(method, url, headers, payload_sha, key_id, secret, region, now=None, service="s3"):
    """Ajoute à `headers` les en-têtes x-amz-date, x-amz-content-sha256 et Authorization. Renvoie headers."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    amz = now.strftime("%Y%m%dT%H%M%SZ")
    day = amz[:8]
    parts = urlsplit(url)
    headers = dict(headers)
    headers["host"] = parts.netloc
    headers["x-amz-date"] = amz
    headers["x-amz-content-sha256"] = payload_sha
    canon_headers = {k.lower().strip(): re.sub(r"\s+", " ", str(v).strip()) for k, v in headers.items()}
    signed = ";".join(sorted(canon_headers))
    query = "&".join(sorted(
        "=".join(quote(x, safe="-_.~") for x in (kv.split("=", 1) + [""])[:2])
        for kv in parts.query.split("&") if kv))
    creq = "\n".join([method, uri_encode(parts.path or "/"), query,
                      "".join(f"{k}:{canon_headers[k]}\n" for k in sorted(canon_headers)), signed, payload_sha])
    scope = f"{day}/{region}/{service}/aws4_request"
    sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(creq.encode()).hexdigest()])
    k = _h(_h(_h(_h(("AWS4" + secret).encode(), day), region), service), "aws4_request")
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={signed}, Signature={sig}"
    del headers["host"]          # requests le remet lui-même, à l'identique
    return headers


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class Store:
    def __init__(self, endpoint=None, bucket=None, key_id=None, secret=None, region=None, session=None, timeout=120):
        import requests
        self.endpoint = (endpoint or env("OFFSITE_ENDPOINT")).rstrip("/")
        self.bucket = bucket or env("OFFSITE_BUCKET")
        self.key_id = key_id or env("OFFSITE_KEY_ID")
        self.secret = secret or env("OFFSITE_SECRET")
        self.region = region or env("OFFSITE_REGION", "us-east-1")
        self.http = session or requests.Session()
        self.timeout = timeout

    def _url(self, key, query=""):
        return f"{self.endpoint}/{self.bucket}/{uri_encode(key)}" + (f"?{query}" if query else "")

    def _do(self, method, key, data=b"", query="", extra=None, stream=False):
        url = self._url(key, query)
        sha = hashlib.sha256(data).hexdigest() if data else EMPTY_SHA
        headers = sign(method, url, extra or {}, sha, self.key_id, self.secret, self.region)
        r = self.http.request(method, url, data=data or None, headers=headers, timeout=self.timeout, stream=stream)
        return r

    def put(self, key, data, content_type="application/octet-stream"):
        r = self._do("PUT", key, data, extra={"content-type": content_type})
        if r.status_code >= 300:
            raise IOError(f"envoi refusé ({r.status_code}) : {r.text[:200]}")
        return True

    def put_file(self, key, path):
        with open(path, "rb") as fh:
            return self.put(key, fh.read())

    def get(self, key):
        r = self._do("GET", key)
        if r.status_code == 404:
            return None
        if r.status_code >= 300:
            raise IOError(f"lecture refusée ({r.status_code}) : {r.text[:200]}")
        return r.content

    def delete(self, key):
        r = self._do("DELETE", key)
        if r.status_code >= 300 and r.status_code != 404:
            raise IOError(f"suppression refusée ({r.status_code})")
        return True

    def list(self, pfx=""):
        """Clés et tailles sous un préfixe (ListObjectsV2, toutes les pages)."""
        out, token = [], None
        while True:
            q = "list-type=2&prefix=" + quote(pfx, safe="")
            if token:
                q += "&continuation-token=" + quote(token, safe="")
            url = f"{self.endpoint}/{self.bucket}?{q}"
            headers = sign("GET", url, {}, EMPTY_SHA, self.key_id, self.secret, self.region)
            r = self.http.get(url, headers=headers, timeout=self.timeout)
            if r.status_code >= 300:
                raise IOError(f"liste refusée ({r.status_code}) : {r.text[:200]}")
            body = r.text
            for m in re.finditer(r"<Contents>(.*?)</Contents>", body, re.S):
                k = re.search(r"<Key>(.*?)</Key>", m.group(1), re.S).group(1)
                size = re.search(r"<Size>(\d+)</Size>", m.group(1))
                out.append((_xml_unescape(k), int(size.group(1)) if size else 0))
            nxt = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", body, re.S)
            if "<IsTruncated>true</IsTruncated>" in body and nxt:
                token = _xml_unescape(nxt.group(1))
            else:
                return out


def _xml_unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
            .replace("&amp;", "&"))
