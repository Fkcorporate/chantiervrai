"""Test du controle visuel de la qualite : photos guidees, mesures et regles, analyse par l'IA (simulee),
avis du proprietaire et du professionnel, questions au chef, contre-visite, photo annotee, quota, droits d'acces.
Lancement : python3 test_qualite.py
"""
import io, json, os, re, sys, tempfile
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_qualite_")
os.environ.pop("ANTHROPIC_API_KEY", None)
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
from PIL import Image, ImageFilter

import app as A
from services import quality as Q

A.app.config["TESTING"] = True
PW = "Bingerville-2026"
SITE = (5.3521, -3.8892)
s = A.connect()
ok = 0


def check(cond, label):
    global ok
    assert cond, label
    ok += 1
    print("  ok ", label)


def tok(c, url="/"):
    m = re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True))
    assert m, url
    return m.group(1)


def post(c, url, data, page="/", follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def html(r):
    return r.get_data(as_text=True).replace("&#39;", "'")


def one(q, *a):
    return s.execute(q, a).fetchone()


def register(email, role="proprio", **extra):
    c = A.app.test_client()
    assert post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW,
                                        **extra), "/inscription", follow=False).status_code == 302, email
    return c


def notes(email, title):
    return one("SELECT COUNT(*) FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.email = ? AND n.title LIKE ? "
               "AND n.channel = 'app'", email, f"%{title}%")[0]


def jpg(lat, lng, seed=1, size=(640, 480), blur=0, dark=False):
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    if dark:
        arr = (arr * 0.1).astype(np.uint8)
    im = Image.fromarray(arr)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    ex = Image.Exif()

    def dms(x):
        x = abs(x); d = int(x); m = int((x - d) * 60)
        return (float(d), float(m), round(((x - d) * 60 - m) * 60, 4))
    ex[0x8825] = {1: "N", 2: dms(lat), 3: "W", 4: dms(lng)}
    ex.get_ifd(0x8769)[0x9003] = datetime.now(timezone.utc).strftime("%Y:%m:%d %H:%M:%S")
    b = io.BytesIO(); im.save(b, "JPEG", exif=ex.tobytes()); return b.getvalue()


def shoot(c, rid, shot, img):
    return html(post(c, f"/qualite/{rid}/photo", dict(tz_offset="0", shot=shot, photo=(io.BytesIO(img), "p.jpg")),
                     f"/qualite/{rid}", files=True))


def points(rid):
    return {r["point"]: r for r in s.execute("SELECT * FROM quality_points WHERE review_id = ?", (rid,))}


print("Règles fixes")
esc = Q.BY_SLUG["escalier"]
m_h = next(m for m in esc["measures"] if m["id"] == "hauteurs")
check(Q.parse_numbers("17 17,5; 18/x") == [17.0, 17.5, 18.0], "lecture des nombres (virgule, séparateurs)")
check(Q.check_measure(m_h, "17 17.2 17.1 17")[0] == "ok", "marches régulières : correct")
check(Q.check_measure(m_h, "17 17.8 17")[0] == "a_verifier", "écart de 8 mm : à vérifier")
check(Q.check_measure(m_h, "17 18.5 17")[0] == "probleme", "écart de 15 mm : problème probable")
st, txt = Q.check_measure(m_h, "17 18.5 17")
check("n° 2" in txt, "la marche fautive est désignée")
check(Q.derived_checks("escalier", {"hauteurs": "17 17", "girons": "28 28"})["confort"][0] == "ok", "règle de Blondel : 62 cm, confortable")
dch = next(m for m in Q.BY_SLUG["douche"]["measures"] if m["id"] == "pente")
check(Q.check_measure(dch, "0.3")[0] == "probleme" and Q.check_measure(dch, "1,5")[0] == "ok", "pente de douche")
fnd = next(m for m in Q.BY_SLUG["fondations"]["measures"] if m["id"] == "profondeur")
check(Q.check_measure(fnd, "70", ref_value="80")[0] == "probleme" and Q.check_measure(fnd, "82", ref_value="80")[0] == "ok",
      "profondeur comparée au plan")
sc, n = Q.score([{"status": "ok", "severity": "critique"}, {"status": "probleme", "severity": "mineur"},
                 {"status": "a_controler", "severity": "majeur"}])
check(sc == 75 and n == 2, "note pondérée par la gravité, points non jugés exclus")
check(len(Q.OUVRAGES) == 14 and all(o["shots"] and o["points"] for o in Q.OUVRAGES), "14 ouvrages avec prises de vue et points")
for o in Q.OUVRAGES:
    ids = {p["id"] for p in o["points"]}
    assert all(m["point"] in ids for m in o["measures"]), o["slug"]
    for x in [o["name"], o["moment"]] + [p["label"] for p in o["points"]] + [p["look"] for p in o["points"]] + \
             [s_["label"] for s_ in o["shots"]] + [s_["hint"] for s_ in o["shots"]] + [m["label"] for m in o["measures"]]:
        assert x["fr"] and x["en"] and x["fr"] != x["en"], x
check(True, "chaque mesure vise un point existant ; tout est traduit")
check("escalier" in Q.suggest("Escalier et garde-corps") and "douche" in Q.suggest("Salle d'eau et faïence"), "ouvrage proposé d'après l'étape")
check(Q.photo_quality(Image.open(io.BytesIO(jpg(*SITE, blur=6))))["issues"] == ["floue"], "photo floue repérée")
check("sombre" in Q.photo_quality(Image.open(io.BytesIO(jpg(*SITE, dark=True))))["issues"], "photo sombre repérée")
order = re.findall(r'"(\w+)"', re.search(r"MIGRATION_ORDER = \[(.*?)\]", open(os.path.join(BASE, "app.py")).read(), re.S).group(1))
tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", open(os.path.join(BASE, "app.py")).read())
check(set(tables) <= set(order), "toutes les tables sont copiées par la migration vers PostgreSQL")

print("Chantier")
own = register("a@x.ci"); chef = register("k@x.ci", "chef", phone="0700000000")
eng = register("ing@x.ci", "pro", profession="ingenieur"); compta = register("cpt@x.ci", "pro", profession="comptable")
other = register("z@x.ci"); boss = register("boss@cv.ci")
A.app.test_cli_runner().invoke(args=["creer-admin", "boss@cv.ci"])
data = dict(name="Villa", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="suivi",
            start_date=datetime.now().date().isoformat())
for i, (nm, a) in enumerate([("Fondations", 1000000), ("Escalier et garde-corps", 800000), ("Carrelage", 600000)]):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = nm, str(a), "10"
pid = int(post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
post(chef, "/rejoindre", dict(code=one("SELECT invite_code FROM projects WHERE id=?", pid)[0]))
steps = [r[0] for r in s.execute("SELECT id FROM steps WHERE project_id=? ORDER BY position", (pid,))]
s.execute("UPDATE steps SET status = CASE WHEN id = ? THEN 'paye' WHEN id = ? THEN 'en_cours' ELSE status END", (steps[0], steps[1]))
s.commit()
s.execute("UPDATE users SET verified = 1 WHERE email = 'ing@x.ci'"); s.commit()
for c, role in ((eng, "ingenieur"), (compta, "comptable")):
    email = "ing@x.ci" if role == "ingenieur" else "cpt@x.ci"
    post(own, f"/chantiers/{pid}/membres", dict(action="add", email=email, role=role), f"/chantiers/{pid}?onglet=dossier")
check(one("SELECT COUNT(*) FROM project_members WHERE project_id=?", pid)[0] == 2, "ingénieur et comptable ajoutés au chantier")

print("Ouverture et photos guidées")
h = html(own.get(f"/chantiers/{pid}/qualite"))
check("Escalier" in h and "Conseillé pour l'étape en cours" in h, "liste des ouvrages, escalier conseillé pour l'étape en cours")
r = post(own, f"/chantiers/{pid}/qualite", dict(ouvrage="escalier", step_id=str(steps[1]), label="R+1"), f"/chantiers/{pid}/qualite", follow=False)
rid = int(r.headers["Location"].rstrip("/").split("/")[-1])
check(notes("k@x.ci", "Photos de contrôle demandées") == 1, "chef prévenu des photos à prendre")
h = html(chef.get(f"/qualite/{rid}"))
check("Escalier de profil" in h and "Prendre une photo guidée" in h and "instrument dans le cadre" in h, "chef : prises de vue guidées et formulaire")
check("Prendre une photo guidée" not in html(own.get(f"/qualite/{rid}")), "propriétaire : pas de formulaire de prise de vue")
check("vérifiée et ajoutée" in shoot(chef, rid, "profil", jpg(*SITE, seed=1)), "photo guidée vérifiée et rattachée")
shoot(chef, rid, "face", jpg(*SITE, seed=2)); shoot(chef, rid, "hauteur", jpg(*SITE, seed=3))
check("refusée" in shoot(chef, rid, "garde_corps", jpg(5.40, -3.80, seed=4)), "photo prise hors du terrain refusée")
check("inutilisable" in shoot(chef, rid, "nez", jpg(*SITE, seed=5, blur=6)), "photo floue signalée au chef")
check(one("SELECT COUNT(*) FROM quality_photos WHERE review_id=?", rid)[0] == 5
      and one("SELECT COUNT(*) FROM proofs WHERE step_id=? AND ok=1", steps[1])[0] == 4, "5 photos rattachées, 4 vérifiées, comptées comme preuves")
check(one("SELECT note FROM proofs ORDER BY id LIMIT 1")[0].startswith("Contrôle qualité : "), "la preuve porte le nom de la prise de vue")

print("Mesures et contrôle sans IA")
post(chef, f"/qualite/{rid}/mesures", dict(hauteurs="17 17,2 17 18,5 17", girons="28 28 28,5 28", garde_corps="90", echappee="210"), f"/qualite/{rid}")
check(json.loads(one("SELECT measures FROM quality_reviews WHERE id=?", rid)[0])["hauteurs"] == "17 17,2 17 18,5 17", "mesures enregistrées")
check(post(compta, f"/qualite/{rid}/mesures", dict(hauteurs="1"), f"/qualite/{rid}", follow=False).status_code == 403, "le comptable ne saisit pas de mesure")
post(chef, f"/qualite/{rid}/analyser", {}, f"/qualite/{rid}")
rv = one("SELECT * FROM quality_reviews WHERE id=?", rid)
pts = points(rid)
check(rv["status"] == "pret" and rv["mode"] == "regles", "analyse sans clé d'IA : règles seules")
check(pts["hauteurs"]["status"] == "probleme" and "n° 4" in pts["hauteurs"]["explanation"], "marche n° 4 trop haute : problème probable")
check(pts["girons"]["status"] == "ok" and pts["confort"]["status"] == "ok", "profondeurs régulières, confort correct")
check(pts["garde_corps"]["status"] == "a_verifier" and pts["echappee"]["status"] == "ok", "garde-corps de 90 cm à vérifier")
check(pts["nez"]["status"] == "a_controler", "point sans mesure : à contrôler par le propriétaire")
check(rv["inspect"] == 1, "problème critique : inspection conseillée")
check(notes("a@x.ci", "Contrôle qualité prêt") == 1 and notes("k@x.ci", "points à reprendre") == 1, "propriétaire et chef prévenus")
h = html(own.get(f"/qualite/{rid}"))
check("Problème probable" in h and "Comment le vérifier" in h and "Inspection conseillée" in h, "fiche du propriétaire")
h = html(own.get(f"/chantiers/{pid}?onglet=etapes"))
check("1 problème probable" in h and "Contrôles qualité en cours" in h, "carte de l'étape : problème signalé")
h = html(own.get(f"/chantiers/{pid}/etapes/{steps[1]}"))
check("Problème probable non résolu : Marches de même hauteur" in h, "vérification avant paiement : problème qualité listé")

print("Avis, questions, accord")
q = {k: v["id"] for k, v in pts.items()}
post(own, f"/qualite/{rid}/points/{q['nez']}", dict(action="owner_check", status="ok"), f"/qualite/{rid}")
check(one("SELECT owner_status FROM quality_points WHERE id=?", q["nez"])[0] == "ok", "le propriétaire contrôle un point lui-même")
post(own, f"/qualite/{rid}/points/{q['garde_corps']}", dict(action="accept", note="garde-corps provisoire"), f"/qualite/{rid}")
post(own, f"/qualite/{rid}/points/{q['hauteurs']}", dict(action="ask", note="Pouvez-vous mesurer à nouveau la 4e marche ?"), f"/qualite/{rid}")
check(notes("k@x.ci", "Question sur le contrôle qualité") == 1, "question envoyée au chef")
post(chef, f"/qualite/{rid}/messages", dict(body="Elle fait bien 18,5 cm, je la reprends demain.", point_id=str(q["hauteurs"])), f"/qualite/{rid}")
check(notes("a@x.ci", "nouveau message") == 1 and "je la reprends demain" in html(own.get(f"/qualite/{rid}")), "réponse du chef visible")
check(post(chef, f"/qualite/{rid}/points/{q['nez']}", dict(action="accept"), f"/qualite/{rid}", follow=False).status_code == 403,
      "le chef ne peut pas accepter à la place du propriétaire")
post(eng, f"/qualite/{rid}/points/{q['nez']}", dict(action="expert", status="probleme", note="Nez de la 3e marche épaufré"), f"/qualite/{rid}")
check(A.q_effective(one("SELECT * FROM quality_points WHERE id=?", q["nez"])) == "probleme" and notes("a@x.ci", "Avis d'un professionnel") == 1,
      "l'avis de l'ingénieur prime sur celui du propriétaire")
check(post(compta, f"/qualite/{rid}/points/{q['nez']}", dict(action="expert", status="ok"), f"/qualite/{rid}", follow=False).status_code == 403,
      "le comptable ne donne pas d'avis technique")
check(other.get(f"/qualite/{rid}").status_code == 403 and compta.get(f"/qualite/{rid}").status_code == 200, "accès : étranger refusé, intervenant en lecture")
proof = one("SELECT proof_id FROM quality_photos qp JOIN proofs pr ON pr.id = qp.proof_id WHERE review_id=? AND pr.ok=1 LIMIT 1", rid)[0]
img = own.get(f"/qualite/{rid}/photos/{proof}/annotee")
check(img.status_code == 200 and img.mimetype == "image/jpeg", "photo annotée servie")

print("Analyse par l'IA (simulée)")
calls = []


def fake_ai(o, images, photos, values, rules, previous, step_name, lang):
    calls.append({"n": len(images), "prev": [p["point"] for p in previous], "prompt": Q.build_prompt(o, photos, values, rules, previous, step_name, lang)})
    if previous:
        return {"meme_lieu": True, "points": [{"id": "hauteurs", "statut": "ok", "confiance": 0.9, "photo": 0, "constat": "Marches régulières."}],
                "corrige": [{"point": "hauteurs", "statut": "corrige"}], "resume": "La marche a été reprise."}
    return {"meme_lieu": True,
            "points": [{"id": "hauteurs", "statut": "ok", "confiance": 0.9, "photo": 0, "zone": {"x": 0.2, "y": 0.3, "w": 0.3, "h": 0.2},
                        "constat": "Les marches paraissent régulières.", "conseil": ""},
                       {"id": "girons", "statut": "probleme", "confiance": 0.8, "photo": 1, "zone": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
                        "constat": "La dernière marche semble plus courte.", "conseil": "Mesurer la dernière marche."},
                       {"id": "echappee", "statut": "non_visible", "confiance": 0.3, "photo": None},
                       {"id": "nez", "statut": "probleme", "confiance": 0.4, "photo": 2, "zone": {"x": 0.5, "y": 0.5, "w": 0.9, "h": 0.9},
                        "constat": "Éclat possible au nez de marche."},
                       {"id": "inconnu", "statut": "ok"}],
            "autres_constats": [{"constat": "Fer apparent sous la paillasse.", "gravite": "critique", "photo": 1,
                                 "zone": {"x": 0.6, "y": 0.6, "w": 0.2, "h": 0.2}, "conseil": "Faire reprendre l'enrobage."}],
            "mesures_lues": [{"mesure": "hauteurs", "valeur_lue": "19 cm", "coherent": False, "commentaire": "Le mètre indique 19 cm."}],
            "photos_inutilisables": [{"photo": 2, "raison": "trop sombre"}],
            "photos_a_ajouter": ["Le garde-corps avec un mètre"], "resume": "Escalier globalement correct, deux points à reprendre.",
            "inspection_conseillee": False}


Q.call_ai = fake_ai
os.environ["ANTHROPIC_API_KEY"] = "test"
post(own, f"/qualite/{rid}/analyser", {}, f"/qualite/{rid}")
rv = one("SELECT * FROM quality_reviews WHERE id=?", rid); pts = points(rid)
check(rv["mode"] == "ia" and calls[-1]["n"] == 4, "IA appelée avec les 4 photos vérifiées")
check("Marches de même hauteur" in calls[-1]["prompt"] and "17 17,2 17 18,5 17" in calls[-1]["prompt"], "les points et les mesures sont transmis à l'IA")
check(pts["hauteurs"]["status"] == "probleme" and pts["hauteurs"]["source"] == "mesure", "la mesure l'emporte quand l'IA est moins sévère")
check(pts["girons"]["status"] == "a_verifier", "l'IA voit un problème que la mesure ne montre pas : à vérifier")
check(pts["nez"]["status"] == "a_verifier", "IA peu sûre d'elle : à vérifier plutôt que problème")
check(pts["echappee"]["status"] == "ok" and pts["echappee"]["source"] == "mesure", "point non visible mais mesuré : la mesure compte")
check("autre" in pts and pts["autre"]["severity"] == "critique" and json.loads(pts["autre"]["zone"])[0] == 0.6, "constat supplémentaire de l'IA, localisé")
check(json.loads(pts["nez"]["zone"]) == [0.5, 0.5, 0.5, 0.5], "rectangle ramené dans la photo")
ex = json.loads(rv["extras"])
check(ex["readings"][0]["coherent"] is False and rv["inspect"] == 1, "mesure contredite par la photo de l'instrument : inspection conseillée")
check(ex["unusable"] and ex["more"] == ["Le garde-corps avec un mètre"], "photos inutilisables et photos à ajouter")
check(rv["summary"].startswith("Escalier globalement correct"), "résumé de l'IA")
h = html(own.get(f"/qualite/{rid}"))
check("Ne correspond pas" in h and "Fer apparent" in h and "Analyse des photos par l'IA" in h, "fiche : lecture d'instrument, constat, source")
img = Image.open(io.BytesIO(own.get(f"/qualite/{rid}/photos/{one('SELECT proof_id FROM quality_points WHERE id=(SELECT id FROM quality_points WHERE review_id=? AND point=?)', rid, 'girons')[0]}/annotee").data))
px = np.asarray(img.convert("RGB"))
check(((px[..., 0] > 180) & (px[..., 1] < 80)).sum() > 200, "rectangles dessinés sur la photo annotée")

print("Contre-visite")
r = post(own, f"/qualite/{rid}/contre-visite", {}, f"/qualite/{rid}", follow=False)
rid2 = int(r.headers["Location"].rstrip("/").split("/")[-1])
check(one("SELECT previous_id FROM quality_reviews WHERE id=?", rid2)[0] == rid and notes("k@x.ci", "Contre-visite demandée") == 1,
      "contre-visite ouverte, chef prévenu")
check("Une contre-visite a été ouverte" in html(own.get(f"/qualite/{rid}")), "le premier contrôle renvoie vers la contre-visite")
check(not A.q_open_issues(s, step_id=steps[1]), "les problèmes du premier contrôle ne comptent plus")
shoot(chef, rid2, "profil", jpg(*SITE, seed=11))
post(chef, f"/qualite/{rid2}/mesures", dict(hauteurs="17 17,1 17 17,2 17", girons="28 28 28 28", garde_corps="100", echappee="210"), f"/qualite/{rid2}")
post(chef, f"/qualite/{rid2}/analyser", {}, f"/qualite/{rid2}")
pts2 = points(rid2)
check("hauteurs" in calls[-1]["prev"] and pts2["hauteurs"]["status"] == "ok" and pts2["hauteurs"]["fixed"] == "corrige", "marche reprise : corrigé")
check("Corrigé depuis le contrôle précédent" in html(own.get(f"/qualite/{rid2}")), "fiche de contre-visite")

print("Quota et réglage")
A.app.config["BILLING_ENFORCED"] = True
lim, used = A.q_quota(s, one("SELECT * FROM projects WHERE id=?", pid))
check(lim == 3 and used == 2, "essai : 3 analyses par mois, 2 utilisées")
r3 = int(post(own, f"/chantiers/{pid}/qualite", dict(ouvrage="carrelage", step_id=str(steps[1])), f"/chantiers/{pid}/qualite",
              follow=False).headers["Location"].split("/")[-1])
shoot(chef, r3, "ensemble", jpg(*SITE, seed=21))
post(chef, f"/qualite/{r3}/analyser", {}, f"/qualite/{r3}")
check(one("SELECT mode FROM quality_reviews WHERE id=?", r3)[0] == "ia", "3e analyse comprise")
r4 = int(post(own, f"/chantiers/{pid}/qualite", dict(ouvrage="douche", step_id=str(steps[1])), f"/chantiers/{pid}/qualite",
              follow=False).headers["Location"].split("/")[-1])
shoot(chef, r4, "siphon", jpg(*SITE, seed=31))
h = html(post(chef, f"/qualite/{r4}/analyser", {}, f"/qualite/{r4}"))
check(one("SELECT mode FROM quality_reviews WHERE id=?", r4)[0] == "regles" and "épuisées" in h, "quota atteint : règles seules, message clair")
A.app.config["BILLING_ENFORCED"] = False
post(boss, "/admin/action", dict(action="quality_ai"), "/admin")
check(A.get_setting("quality_ai", "1", s) == "0", "le super-admin coupe l'analyse par l'IA")
post(own, f"/qualite/{r3}/analyser", {}, f"/qualite/{r3}")
check(one("SELECT mode FROM quality_reviews WHERE id=?", r3)[0] == "regles", "IA coupée : règles seules")
post(boss, "/admin/action", dict(action="quality_ai", on="1"), "/admin")

print("Erreur de l'IA, anglais, clôture")


def broken(*a, **k):
    raise RuntimeError("délai dépassé")


Q.call_ai = broken
post(own, f"/qualite/{r3}/analyser", {}, f"/qualite/{r3}")
rv3 = one("SELECT * FROM quality_reviews WHERE id=?", r3)
check(rv3["status"] == "pret" and rv3["mode"] == "regles" and "délai" in rv3["error"], "IA en panne : le contrôle aboutit quand même")
own.get("/?lang=en")
h = html(own.get(f"/qualite/{rid}"))
check("Likely problem" in h and "Steps of equal height" in h and "Guided photos" in h, "fiche en anglais")
own.get("/?lang=fr")
post(own, f"/qualite/{r4}/clore", {}, f"/qualite/{r4}")
check(one("SELECT status FROM quality_reviews WHERE id=?", r4)[0] == "clos"
      and post(chef, f"/qualite/{r4}/photo", dict(shot="siphon"), f"/qualite/{r3}", follow=False).status_code == 403, "contrôle clos : plus de photo")
os.environ.pop("ANTHROPIC_API_KEY", None)
print(f"\n{ok} contrôles réussis.")
