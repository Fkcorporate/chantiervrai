"""Mise en production : signature S3 (exemples officiels AWS), copie des sauvegardes vers un faux stockage S3
qui vérifie chaque signature, envoi incrémental des fichiers, restauration complète, page de santé,
tâches planifiées protégées, alertes (erreur serveur, sauvegarde en échec ou en retard).
Lancement : python3 test_production.py   (ou avec DATABASE_URL=postgresql://… pour PostgreSQL)
"""
import datetime as dt
import hashlib
import io
import os
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_prod_")
for k in ("OFFSITE_ENDPOINT", "OFFSITE_BUCKET", "OFFSITE_KEY_ID", "OFFSITE_SECRET", "ALERT_EMAILS", "CRON_TOKEN"):
    os.environ.pop(k, None)
PG = os.environ.get("DATABASE_URL", "").startswith("postgres")
if PG:
    from services import db as _DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        from tests_support import pgwire
        _DB.set_driver(pgwire)
    _c = _DB.connect("")
    _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public"); _c.commit(); _c.close()

from services import offsite as OFF
from services import ops as OPS

ok = 0


def check(cond, label):
    global ok
    assert cond, label
    ok += 1
    print("  ok ", label)


# ---------------------------------------------------------------------------
print("Signature AWS Version 4 (exemples de la documentation AWS)")
KID, SEC = "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
T0 = dt.datetime(2013, 5, 24, tzinfo=dt.timezone.utc)
h = OFF.sign("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"range": "bytes=0-9"}, OFF.EMPTY_SHA, KID, SEC, "us-east-1", now=T0)
check(h["Authorization"].endswith("f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"), "GET d'un objet")
body = b"Welcome to Amazon S3."
h = OFF.sign("PUT", "https://examplebucket.s3.amazonaws.com/test$file.text",
             {"date": "Fri, 24 May 2013 00:00:00 GMT", "x-amz-storage-class": "REDUCED_REDUNDANCY"},
             hashlib.sha256(body).hexdigest(), KID, SEC, "us-east-1", now=T0)
check(h["Authorization"].endswith("98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd"), "PUT d'un objet (caractère spécial encodé)")
h = OFF.sign("GET", "https://examplebucket.s3.amazonaws.com/?max-keys=2&prefix=J", {}, OFF.EMPTY_SHA, KID, SEC, "us-east-1", now=T0)
check(h["Authorization"].endswith("34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7"), "liste des objets (paramètres triés)")


# ---------------------------------------------------------------------------
# Faux stockage S3 : refuse toute requête dont la signature n'est pas exacte.
class FakeS3(BaseHTTPRequestHandler):
    objects, rejected = {}, []

    def log_message(self, *a):
        pass

    def _auth_ok(self, body):
        auth = self.headers.get("Authorization", "")
        m = re.match(r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/s3/aws4_request, SignedHeaders=([^,]+), Signature=(\w+)", auth)
        if not m or m.group(1) != "cle-test":
            return False
        if hashlib.sha256(body).hexdigest() != self.headers.get("x-amz-content-sha256") and body:
            return False
        when = dt.datetime.strptime(self.headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        others = {k: self.headers[k] for k in m.group(4).split(";") if k not in ("host", "x-amz-date", "x-amz-content-sha256")}
        url = f"http://{self.headers['Host']}{self.path}"
        again = OFF.sign(self.command, url, others, self.headers["x-amz-content-sha256"], "cle-test", "secret-test", m.group(3), now=when)
        return again["Authorization"] == auth

    def _key(self):
        path = urlsplit(self.path).path
        parts = path.lstrip("/").split("/", 1)
        return parts[0], unquote(parts[1]) if len(parts) > 1 else ""

    def _reply(self, code, data=b"", ctype="application/xml"):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def do_PUT(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if not self._auth_ok(body):
            FakeS3.rejected.append(self.path); return self._reply(403, b"<Error>SignatureDoesNotMatch</Error>")
        b, k = self._key(); FakeS3.objects[(b, k)] = body; self._reply(200)

    def do_DELETE(self):
        if not self._auth_ok(b""):
            return self._reply(403)
        FakeS3.objects.pop(self._key(), None); self._reply(204)

    def do_GET(self):
        if not self._auth_ok(b""):
            FakeS3.rejected.append(self.path); return self._reply(403, b"<Error>SignatureDoesNotMatch</Error>")
        b, k = self._key()
        q = parse_qs(urlsplit(self.path).query)
        if "list-type" in q:
            pfx = q.get("prefix", [""])[0]
            keys = sorted(kk for (bb, kk) in FakeS3.objects if bb == b and kk.startswith(pfx))
            start = int(q.get("continuation-token", ["0"])[0])
            page = keys[start:start + 3]                      # pages de 3 : la pagination est testée
            more = start + 3 < len(keys)
            xml = "<ListBucketResult>" + "".join(
                f"<Contents><Key>{kk.replace('&', '&amp;')}</Key><Size>{len(FakeS3.objects[(b, kk)])}</Size></Contents>" for kk in page)
            xml += f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>"
            if more:
                xml += f"<NextContinuationToken>{start + 3}</NextContinuationToken>"
            return self._reply(200, (xml + "</ListBucketResult>").encode())
        if (b, k) not in FakeS3.objects:
            return self._reply(404, b"<Error>NoSuchKey</Error>")
        self._reply(200, FakeS3.objects[(b, k)], "application/octet-stream")


srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeS3)
threading.Thread(target=srv.serve_forever, daemon=True).start()
ENDPOINT = f"http://127.0.0.1:{srv.server_address[1]}"

print("Client S3 contre un stockage qui vérifie les signatures")
st = OFF.Store(ENDPOINT, "seau", "cle-test", "secret-test", "auto")
st.put("essai/a b é.txt", b"bonjour")
check(st.get("essai/a b é.txt") == b"bonjour", "envoi et lecture (nom avec espace et accent)")
for i in range(7):
    st.put(f"essai/n{i}", b"x" * i)
check(len(st.list("essai/")) == 8, "liste complète sur plusieurs pages")
st.delete("essai/n0")
check(st.get("essai/n0") is None and not FakeS3.rejected, "suppression ; aucune signature refusée")
bad = OFF.Store(ENDPOINT, "seau", "cle-test", "mauvais-secret", "auto")
try:
    bad.put("x", b"y"); refused = False
except IOError:
    refused = True
check(refused, "mauvais secret : envoi refusé et signalé")
FakeS3.rejected.clear()

# ---------------------------------------------------------------------------
import app as A
from PIL import Image

A.app.config["TESTING"] = True
A.app.config["STAFF_2FA"] = False


@A.app.route("/__panne")
def _panne():
    raise RuntimeError("panne simulée")


A.app.config["PROPAGATE_EXCEPTIONS"] = False
assert "Propriétaire" in A.app.test_cli_runner().invoke(args=["demo"]).output
s = A.connect()
cli = A.app.test_cli_runner()


def setting(k):
    d = A.connect(); v = A.get_setting(k, None, d); d.close(); return v


print("Sauvegarde vérifiée, sans copie distante")
out = cli.invoke(args=["sauvegarde"]).output
check("Sauvegardé et vérifié" in out and setting("ops_backup_ok") == "1", "sauvegarde faite et relue")
h = A.app.test_client().get("/sante")
j = h.get_json()
check(h.status_code == 200 and j["statut"] == "ok" and j["copie_distante"] == "non configurée" and j["sauvegarde_heures"] < 1,
      "page de santé : application, base, disque, sauvegarde du jour")
bad_dump = os.path.join(os.environ["CV_INSTANCE"], "abime.db")
open(bad_dump, "wb").write(b"pas une base")
check(not OPS.verify_dump(bad_dump)[0], "une sauvegarde abîmée est détectée")

print("Copie distante")
os.environ.update(OFFSITE_ENDPOINT=ENDPOINT, OFFSITE_BUCKET="seau", OFFSITE_KEY_ID="cle-test", OFFSITE_SECRET="secret-test",
                  OFFSITE_REGION="auto", OFFSITE_PREFIX="cv/")
out = cli.invoke(args=["sauvegarde"]).output
base = [k for (b, k) in FakeS3.objects if k.startswith("cv/base/")]
files = [k for (b, k) in FakeS3.objects if k.startswith("cv/fichiers/")]
n_local = sum(len(f) for _r, _d, f in os.walk(A.UPLOAD_DIR))
check(len(base) == 1 and base[0].endswith(".sql.gz" if PG else ".db"), "base copiée hors du serveur")
check(len(files) >= 5 and len(files) >= n_local - 2, f"photos et documents copiés ({len(files)} fichiers sur {n_local}) {out[-400:]}")
check(setting("ops_offsite_ok") == "1" and not FakeS3.rejected, "état « copie à jour », toutes les signatures acceptées")
arch = [f for f in os.listdir(os.path.join(A.INSTANCE_DIR, "sauvegardes")) if f.startswith("fichiers-")]
check(len(arch) == 1, "avec la copie distante, plus de nouvelle archive locale des fichiers (seule celle d'avant reste)")
before = len(FakeS3.objects)
out = cli.invoke(args=["sauvegarde"]).output
check("0 envoyé(s)" in out, "deuxième passage : aucun fichier renvoyé (incrémental)")
Image.new("RGB", (40, 40), "red").save(os.path.join(A.UPLOAD_DIR, "nouvelle.jpg"))
out = cli.invoke(args=["sauvegarde"]).output
check("1 envoyé(s)" in out and ("seau", "cv/fichiers/nouvelle.jpg") in FakeS3.objects, "un nouveau fichier part seul")

print("Restauration complète depuis la copie distante")
pr = s.execute("SELECT filename FROM proofs WHERE filename IS NOT NULL LIMIT 1").fetchone()[0]
os.remove(os.path.join(A.UPLOAD_DIR, pr))
n_users = s.execute("SELECT COUNT(*) FROM users").fetchone()[0]
s.execute("DELETE FROM activity"); s.execute("UPDATE projects SET name = 'ABÎMÉ'"); s.commit()
r = cli.invoke(args=["restaurer", "--distant", "--avec-fichiers"])
check(r.exit_code != 0 and "--oui" in r.output, "restauration : confirmation exigée")
r = cli.invoke(args=["restaurer", "--distant", "--avec-fichiers", "--oui"])
check(r.exit_code == 0, f"restauration lancée {r.output[-300:]}")
s.close(); s = A.connect()
check(s.execute("SELECT COUNT(*) FROM projects WHERE name = 'ABÎMÉ'").fetchone()[0] == 0
      and s.execute("SELECT COUNT(*) FROM users").fetchone()[0] == n_users
      and s.execute("SELECT COUNT(*) FROM activity").fetchone()[0] > 0, "base revenue à l'état de la sauvegarde")
check(os.path.exists(os.path.join(A.UPLOAD_DIR, pr)), "photo perdue redescendue du stockage distant")
c = A.app.test_client()
t = re.search(r'name="csrf" value="([^"]+)"', c.get("/connexion").get_data(as_text=True)).group(1)
check(c.post("/connexion", data=dict(email="aminata@demo.chantiervrai.ci", password="Demo-Chantier-2026", csrf=t)).status_code == 302
      and c.get(f"/photos/{s.execute('SELECT id FROM proofs WHERE filename = ?', (pr,)).fetchone()[0]}").status_code == 200,
      "après restauration : connexion et photo accessibles")

print("Tâches planifiées")
tc = A.app.test_client()
check(tc.post("/taches/relancer").status_code == 403, "sans jeton : refusé")
os.environ["CRON_TOKEN"] = "jeton-long-de-test"
check(tc.post("/taches/relancer", headers={"Authorization": "Bearer faux"}).status_code == 403, "mauvais jeton : refusé")
check(tc.post("/taches/inconnue", headers={"Authorization": "Bearer jeton-long-de-test"}).status_code == 404, "tâche inconnue")
r = tc.post("/taches/quotidien", headers={"Authorization": "Bearer jeton-long-de-test"})
check(r.status_code == 202 and r.get_json()["started"] and setting("ops_daily_last"), "tâche quotidienne lancée par le planificateur")
d = A.connect(); A.set_setting(d, "lock_relancer", dt.datetime.now(dt.timezone.utc).isoformat()); d.commit(); d.close()
r = tc.post("/taches/relancer", headers={"Authorization": "Bearer jeton-long-de-test"})
check(r.status_code == 200 and not r.get_json()["started"], "tâche déjà en cours : pas lancée deux fois")

print("Alertes")
os.environ["ALERT_EMAILS"] = "tech@exemple.ci"
r = A.app.test_client().get("/__panne")
check(r.status_code == 500 and setting("alert_err_RuntimeError_GET /__panne"), "erreur serveur : équipe alertée")
first = setting("alert_err_RuntimeError_GET /__panne")
A.app.test_client().get("/__panne")
check(setting("alert_err_RuntimeError_GET /__panne") == first, "même erreur répétée : une seule alerte par heure")
d = A.connect(); A.set_setting(d, "ops_backup_last", (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=40)).isoformat()); d.commit(); d.close()
with A.app.test_request_context():
    lines = A.retry_tasks()
check(any("en retard" in x for x in lines) and setting("alert_backup_late"), "sauvegarde de plus de 36 h : alerte")
j = A.app.test_client().get("/sante").get_json()
check(j["alerte"] and j["statut"] == "ok", "page de santé : retard signalé sans faire redémarrer le service")
os.environ["OFFSITE_SECRET"] = "mauvais"
with A.app.test_request_context():
    lines = A.backup_and_copy()
check(any("ÉCHEC de la copie distante" in x for x in lines) and setting("ops_offsite_ok") == "0" and setting("alert_offsite"),
      "copie distante en échec : état mis à jour et équipe alertée")

print("Administration")
A.app.test_cli_runner().invoke(args=["creer-admin", "awa@demo.chantiervrai.ci"])
c = A.app.test_client()
t = re.search(r'name="csrf" value="([^"]+)"', c.get("/connexion").get_data(as_text=True)).group(1)
c.post("/connexion", data=dict(email="awa@demo.chantiervrai.ci", password="Demo-Chantier-2026", csrf=t))
h = c.get("/admin").get_data(as_text=True).replace("&#39;", "'")
check('id="exploitation"' in h and "en échec" in h and "Sauvegardes à vérifier" in h, "carte « Sauvegardes et surveillance » et point à traiter")

srv.shutdown()
print(f"\n{ok} contrôles réussis{' (PostgreSQL)' if PG else ''}.")
