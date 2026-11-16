"""Test des entrepreneurs verifies (historique et avis), de l'assistant IA et de la lecture des plans.
Les appels a l'IA sont simules : on verifie ce qui lui est envoye et ce qui est fait de sa reponse.
Lancement : python3 test_ia.py   (PostgreSQL : DATABASE_URL=postgresql://... python3 test_ia.py)
"""
import io, json, os, re, sys, tempfile
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_ia_")
if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    from services import db as _DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        from tests_support import pgwire
        _DB.set_driver(pgwire)
    _c = _DB.connect("")
    _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public"); _c.commit(); _c.close()

import numpy as np
from PIL import Image
import app as A
from services import assistant as ASSIST, vision as VISION

A.app.config["TESTING"] = True
SITE = (5.3521, -3.8892)
PW = "Bingerville-2026"
own, own2, chef, chef2, adm = (A.app.test_client() for _ in range(5))
s = A.connect()


def tok(c, url="/"):
    m = re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True))
    assert m, url
    return m.group(1)


def post(c, url, data, page="/", follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def html(r):
    return r.get_data(as_text=True)


def one(sql, *a):
    return s.execute(sql, a).fetchone()


def jpg(seed):
    b = io.BytesIO()
    Image.fromarray(np.random.default_rng(seed).integers(0, 255, (240, 320, 3), dtype=np.uint8)).save(b, "JPEG")
    return b.getvalue()


now_ms = lambda: datetime.now(timezone.utc).timestamp() * 1000


def register(c, email, role, **extra):
    r_ = post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW, **extra),
              "/inscription", follow=False)
    assert r_.status_code == 302, email


register(own, "a@x.ci", "proprio"); register(own2, "b@x.ci", "proprio"); register(adm, "admin@x.ci", "proprio")
register(chef, "k@x.ci", "chef", phone="0700000000"); register(chef2, "z@x.ci", "chef", phone="0700000001")
A.app.test_cli_runner().invoke(args=["creer-admin", "admin@x.ci"])
chef_id = one("SELECT id FROM users WHERE email='k@x.ci'")[0]


def new_project(c, name):
    data = dict(name=name, address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="manuel",
                start_date=datetime.now().date().isoformat())
    for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
        data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
    return int(post(c, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])


# --- 1. Entrepreneurs verifies ---
assert "Profil d&#39;entrepreneur" in html(chef.get("/compte"))
assert "Indiquez le nom de votre entreprise" in html(post(chef, "/compte", dict(name="KOFFI", verify_requested="1"), "/compte"))
assert one("SELECT verify_requested FROM users WHERE id=?", chef_id)[0] == 0
post(chef, "/compte", dict(name="KOFFI", phone="0700000000", company="Bâtir Plus SARL, RCCM CI-ABJ-2019-B-4471", zone="Bingerville",
                           bio="Villas et R+2", verify_requested="1"), "/compte")
assert tuple(one("SELECT verify_requested, company FROM users WHERE id=?", chef_id)) == (1, "Bâtir Plus SARL, RCCM CI-ABJ-2019-B-4471")
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Entrepreneur à vérifier%' AND channel='app'")[0] == 1
assert "Bâtir Plus SARL" in html(adm.get("/admin"))
assert "KOFFI" not in html(own.get("/entrepreneurs"))                        # pas encore verifie
assert own.get(f"/entrepreneurs/{chef_id}").status_code == 404
post(adm, "/admin/action", dict(action="verify", id=chef_id), "/admin")
assert one("SELECT verified FROM users WHERE id=?", chef_id)[0] == 1
assert "KOFFI" in html(own.get("/entrepreneurs")) and "KOFFI" in html(own.get("/entrepreneurs?zone=binger"))
assert "KOFFI" not in html(own.get("/entrepreneurs?zone=korhogo"))
pid = new_project(own, "Villa")
h = html(own.get(f"/entrepreneurs/{chef_id}"))
assert "Historique mesuré par ChantierVrai" in h and "Inviter sur un de vos chantiers" in h
post(own, f"/entrepreneurs/{chef_id}", dict(project_id=pid), f"/entrepreneurs/{chef_id}")
code = one("SELECT invite_code FROM projects WHERE id=?", pid)[0]
assert one("SELECT body FROM notifications WHERE user_id=? AND title LIKE '%Invitation sur un chantier%' AND channel='app'", chef_id)[0].find(code) >= 0
assert post(own2, f"/entrepreneurs/{chef_id}", dict(project_id=pid), f"/entrepreneurs/{chef_id}").status_code == 403
post(chef, "/rejoindre", dict(code=code))
assert one("SELECT chef_id FROM projects WHERE id=?", pid)[0] == chef_id
# avis : seulement apres une etape payee, par le proprietaire
assert "après le paiement d&#39;une première étape" in html(post(own, f"/chantiers/{pid}/avis", dict(rating="5"), f"/chantiers/{pid}"))
tk = re.search(r'name="capture_token" value="([^"]+)"', html(chef.get(f"/chantiers/{pid}"))).group(1)
post(chef, f"/chantiers/{pid}/preuves", dict(tz_offset="0", lat=str(SITE[0]), lng=str(SITE[1]), photo=(io.BytesIO(jpg(1)), "c.jpg"),
                                             capture="app", capture_token=tk, captured_at=str(now_ms()), client_now=str(now_ms())),
     f"/chantiers/{pid}", files=True)
st1 = one("SELECT id FROM steps WHERE project_id=? ORDER BY position", pid)[0]
post(chef, f"/chantiers/{pid}/etapes/{st1}/declarer", {}, f"/chantiers/{pid}")
post(own, f"/chantiers/{pid}/etapes/{st1}/valider", dict(override="1", pay_ref="OM-1"), f"/chantiers/{pid}")
assert one("SELECT status FROM steps WHERE id=?", st1)[0] == "paye"
assert "Noter son travail" in html(own.get(f"/chantiers/{pid}"))
assert post(chef, f"/chantiers/{pid}/avis", dict(rating="5"), f"/chantiers/{pid}").status_code == 403
post(own, f"/chantiers/{pid}/avis", dict(rating="3", comment="Un peu lent"), f"/chantiers/{pid}")
post(own, f"/chantiers/{pid}/avis", dict(rating="4", comment="Sérieux, photos chaque semaine"), f"/chantiers/{pid}")
assert one("SELECT COUNT(*) FROM contractor_reviews")[0] == 1                 # un avis par chantier, modifiable
rec = A.contractor_record(s, chef_id)
assert rec["projects"] == 1 and rec["ongoing"] == 1 and rec["rating"] == 4.0 and rec["proofs"] == 1 and rec["refused_pct"] == 0
h = html(own2.get(f"/entrepreneurs/{chef_id}"))
assert "4.0/5" in h and "Sérieux, photos chaque semaine" in h and "Entreprise vérifiée" in h
chef2_id = one("SELECT id FROM users WHERE email='z@x.ci'")[0]
assert own2.get(f"/entrepreneurs/{chef2_id}").status_code == 404 and chef2.get(f"/entrepreneurs/{chef2_id}").status_code == 200
assert "Entrepreneurs" in html(own.get("/")) and "Entrepreneurs" not in html(chef.get("/")).split("<main")[0]
print("entrepreneurs vérifiés : vérification, annuaire, invitation, historique, avis ok")

# --- 2. Assistant ---
h = html(post(own, "/assistant", dict(q="combien de sacs de ciment pour un mètre cube de béton"), "/assistant"))
assert "Assistant IA non activé" in h and "Comment doser le ciment ?" in h
seen = {}


def fake_call(question, history, sources, lang):
    seen.update(question=question, history=history, sources=sources, lang=lang)
    return "Pour 1 m³ dosé à 350 kg, il faut 7 sacs [C1]. Votre chantier a une étape payée [CHANTIER]."


os.environ["ANTHROPIC_API_KEY"] = "test"
ASSIST.call = fake_call
h = html(post(own, "/assistant", dict(q="combien de sacs de ciment pour un mètre cube de béton", chantier=pid), f"/assistant?chantier={pid}"))
assert "il faut 7 sacs" in h and "[C1] Comment doser le ciment ?" in h and "données mesurées de votre chantier" in h, h[h.find("<main"):][:3000]
assert "Étape « Fondations » : validée et payée" in seen["sources"] and "[C1]" in seen["sources"] and seen["history"] == []
assert one("SELECT project_id FROM assistant_messages")[0] == pid
post(own, "/assistant", dict(q="et pour le béton de propreté ?", chantier=pid), f"/assistant?chantier={pid}")
assert len(seen["history"]) == 1 and seen["history"][0][0].startswith("combien de sacs")     # suite de la conversation
other = new_project(own2, "Autre")
post(own, "/assistant", dict(q="que se passe-t-il sur ce chantier ?", chantier=other), "/assistant")
assert "Autre" not in seen["sources"]                                         # pas de donnees d'un chantier etranger
h = html(post(own, "/assistant", dict(q="quel diamètre de fer pour ma poutre de 5 m ?"), "/assistant"))
assert "seul l&#39;ingénieur peut les donner" in h
A.ASSISTANT_DAILY = 4
assert "revenez demain" in html(post(own, "/assistant", dict(q="encore une question sur le béton"), "/assistant"))
A.ASSISTANT_DAILY = 40


def broken(*a, **k):
    raise RuntimeError("down")


ASSIST.call = broken
h = html(post(own2, "/assistant", dict(q="comment savoir si le sable est sale"), "/assistant"))
assert "ne répond pas pour l&#39;instant" in h and "Comment contrôler les matériaux ?" in h
assert "Mon chef dit que la dalle est prête" in html(chef.get("/assistant"))
print("assistant IA : sources citées, données du chantier, suite de conversation, garde-fous ok")

# --- 3. Lecture des plans ---
lp = f"/chantiers/{pid}/lecture-plan"
os.environ.pop("ANTHROPIC_API_KEY", None)
h = html(post(own, lp, dict(action="read", file=(io.BytesIO(jpg(3)), "plan.jpg")), lp, files=True))
assert "pas activée sur ce serveur" in h
os.environ["ANTHROPIC_API_KEY"] = "test"
VISION.read_plan = lambda raw, mt: {"scale": "1/100", "levels": 1, "rooms": [{"name": "Séjour", "area": 32.5}, {"name": "Chambre", "area": 14.0}],
                                    "floor_area": 84.2, "ext_walls": 38.4, "int_walls": 27.6, "height": None, "doors": 7, "windows": 8,
                                    "confidence": 0.8, "remarks": "Cotes du séjour masquées.", "source": "ia"}
assert "PDF ou en image" in html(post(own, lp, dict(action="read", file=(io.BytesIO(b"x"), "plan.dwg")), lp, files=True))
h = html(post(own, lp, dict(action="read", file=(io.BytesIO(jpg(3)), "plan.jpg")), lp, files=True))
assert "Plan lu. Vérifiez chaque valeur" in h and "lu par l&#39;IA, à vérifier" in h and "Cotes du séjour masquées" in h
assert "Quantités déduites du plan" in h and "Maçonnerie" in h and "Carrelage" in h
q = A.plan_quantities(json.loads(one("SELECT result FROM plan_readings ORDER BY id DESC")[0]))
assert q["maconnerie"]["params"]["long"] == 66.0 and q["maconnerie"]["params"]["ouv"] == 25.3
assert dict((m, v) for m, _u, v in q["carrelage"]["result"]["lines"])["Carreaux"] == 93
post(own, lp, dict(action="save", floor_area="90", ext_walls="40", int_walls="27.6", height="2.8", doors="7", windows="8",
                   update_sheet="1"), lp)
r = json.loads(one("SELECT result FROM plan_readings ORDER BY id DESC")[0])
assert r["floor_area"] == 90 and r["source"] == "corrige" and r["rooms"][0]["name"] == "Séjour"
assert one("SELECT surface_floor FROM projects WHERE id=?", pid)[0] == 90
steps = s.execute("SELECT * FROM steps WHERE project_id=? ORDER BY position", (pid,)).fetchall()
post(own, lp, {"action": "plan", "kind": ["maconnerie", "carrelage"], "step_maconnerie": steps[3]["id"], "step_carrelage": steps[5]["id"]}, lp)
plan = {(r_["step_id"], r_["material"]): r_["qty_planned"] for r_ in s.execute("SELECT * FROM materials_plan WHERE project_id=?", (pid,))}
assert plan[(steps[3]["id"], "Parpaings")] > 0 and plan[(steps[5]["id"], "Carreaux")] == 99, plan
assert (steps[3]["id"], "Peinture") not in plan                               # seulement les calculs cochés
post(own, f"/chantiers/{pid}/documents", dict(category="Plan", title="Plan RDC", file=(io.BytesIO(jpg(4)), "rdc.jpg")),
     f"/chantiers/{pid}", files=True)
doc = one("SELECT id FROM documents WHERE project_id=? AND category='Plan'", pid)[0]
assert "Plan lu" in html(post(chef, lp, dict(action="read", doc_id=doc), lp))
assert one("SELECT doc_id FROM plan_readings ORDER BY id DESC")[0] == doc
assert own2.get(lp).status_code == 403
os.environ.pop("ANTHROPIC_API_KEY", None)
print("lecture des plans : IA, correction, quantités, prévu ok")

# --- 4. Anglais ---
own.get("/?lang=en")
assert "Verified contractors" in html(own.get("/entrepreneurs")) and "Plan reading" in html(own.get(lp))
assert "Assistant" in html(own.get("/assistant"))
print("anglais ok")
print("\nTOUS LES TESTS IA ET ENTREPRENEURS PASSENT")
