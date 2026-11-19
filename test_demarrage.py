"""Test du parcours guide : liste « Bien demarrer », invitation WhatsApp, fonctions avancees masquees.
Lancement : python3 test_demarrage.py
"""
import os, re, sys, tempfile
from datetime import datetime
from urllib.parse import unquote

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_demarrage_")
if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    from services import db as _DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        from tests_support import pgwire
        _DB.set_driver(pgwire)
    _c = _DB.connect("")
    _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public"); _c.commit(); _c.close()

import app as A

A.app.config["TESTING"] = True
A.app.config["BILLING_ENFORCED"] = True
PW = "Bingerville-2026"
s = A.connect()


def tok(c, url="/"):
    m = re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True))
    assert m, url
    return m.group(1)


def post(c, url, data, page="/", follow=True):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow)


def html(r):
    return r.get_data(as_text=True)


def checklist(c):
    h = html(c.get("/"))
    if "Bien démarrer" not in h:
        return None
    sec = h[h.index('class="checklist"'):h.index("</ol>")]
    return re.findall(r'<li class="(done|)"', sec), h


def register(email, role="proprio", **extra):
    c = A.app.test_client()
    assert post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW,
                                        **extra), "/inscription", follow=False).status_code == 302
    return c


own = register("a@x.ci"); chef = register("k@x.ci", "chef")

# --- 1. Proprietaire : 6 points, rien de fait ---
states, h = checklist(own)
assert states == [""] * 6 and "0 / 6" in h and "Créer votre premier chantier" in h and "Choisir votre offre" in h
print("liste « Bien démarrer » : 6 points pour le propriétaire")

# --- 2. Creation simplifiee : budget reparti, options avancees repliees ---
f = html(own.get("/chantiers/nouveau"))
assert "Budget total des travaux" in f and "Proposer les étapes" in f and "Options avancées</summary>" in f
data = dict(name="Villa", address="Bingerville", lat="5.3521", lng="-3.8892", radius="100",
            start_date=datetime.now().date().isoformat(), pay_mode="suivi")
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
pid = int(post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
states, h = checklist(own)
assert states[0] == "done" and "1 / 6" in h
code = s.execute("SELECT invite_code FROM projects WHERE id=?", (pid,)).fetchone()[0]
link = re.search(r'href="(https://wa\.me/\?text=[^"]+)"', h).group(1)
assert code in unquote(link) and "Chef de chantier" in unquote(link)
print("création : budget à répartir, options avancées repliées ; invitation WhatsApp avec le code")

# --- 3. Les points se cochent tout seuls ---
post(chef, "/rejoindre", dict(code=code))
post(own, "/compte", dict(name="Ama", phone="+33600000000", notify_whatsapp="1"), "/compte")
st = s.execute("SELECT id FROM steps WHERE project_id=? ORDER BY position LIMIT 1", (pid,)).fetchone()[0]
chef_id = s.execute("SELECT id FROM users WHERE email='k@x.ci'").fetchone()[0]
s.execute("INSERT INTO proofs (project_id, step_id, user_id, filename, sha256, created_at, ok, reasons, kind, source) "
          "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, st, chef_id, "x.jpg", "abc", A.now_iso(), 1, "", "photo", "chef"))
s.execute("UPDATE steps SET status='versement' WHERE id=?", (st,)); s.commit()
states, h = checklist(own)
assert states == ["done"] * 5 + [""] and "5 / 6" in h
print("progression automatique : chef invité, téléphone, photo, étape validée")

# --- 4. Chef : sa propre liste ; masquer la liste ---
states, h = checklist(chef)
assert len(states) == 4 and states[0] == "done" and states[3] == "done" and states[1] == ""     # pas encore de numero
assert "Renseigner votre numéro Mobile Money" in h
post(chef, "/bien-demarrer/masquer", {})
assert checklist(chef) is None
print("chef : liste dédiée ; « Masquer cette liste » fonctionne")

# --- 5. Fonctions avancees : masquees par defaut, visibles sur demande ou si le chantier s'en sert ---
h = html(own.get(f"/chantiers/{pid}?onglet=dossier"))
assert "Maquette numérique" not in h and "Capteurs et météo" not in h and "Fiche du projet et parcelle" in h
assert own.get(f"/chantiers/{pid}/maquette").status_code in (200, 302)          # la page existe toujours
post(own, "/compte", dict(name="Ama", phone="+33600000000", advanced="1"), "/compte")
assert "Maquette numérique" in html(own.get(f"/chantiers/{pid}?onglet=dossier"))
post(own, "/compte", dict(name="Ama", phone="+33600000000"), "/compte")
assert "Visites 360°" not in html(own.get(f"/chantiers/{pid}?onglet=dossier"))
s.execute("INSERT INTO zones (project_id, name, kind, position, created_at) VALUES (?,?,?,?,?)",
          (pid, "R+1", "etage", 1, A.now_iso())); s.commit()
assert "Visites 360°" in html(own.get(f"/chantiers/{pid}?onglet=dossier"))    # le chantier utilise deja les zones
print("fonctions avancées : masquées par défaut, affichées sur demande ou dès qu'elles servent")
print("TOUS LES TESTS DÉMARRAGE PASSENT")
