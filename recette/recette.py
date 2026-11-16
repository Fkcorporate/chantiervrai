"""Recette de ChantierVrai en conditions reelles, puis mesure d'efficacite.

  python3 recette/recette.py            # resultats dans recette/sortie/ (resultats.json + captures)

1. Scenario reel : un chantier de la diaspora suivi sur plusieurs semaines (temps simule), avec tous les acteurs,
   sur un vrai serveur HTTP en configuration de production, un vrai navigateur et l'API de l'application mobile.
2. Efficacite : batterie de vraies et de fausses photos, charge avec un volume realiste, temps des parcours.
"""
import json, os, re, statistics, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from outils import (Api, PW, SITE, Serveur, Web, ago, jpeg, offset, recrop, reshoot, scene, screen_photo)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sortie")
os.makedirs(OUT, exist_ok=True)
R = {"debut": datetime.now().isoformat(timespec="seconds"), "controles": [], "fraude": [], "charge": [], "parcours": [],
     "anomalies": []}


def check(section, name, ok, detail=""):
    R["controles"].append({"section": section, "controle": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(("  OK   " if ok else "  ECHEC") + f" [{section}] {name}" + (f" : {detail}" if detail and not ok else ""))
    return ok


def notes(srv, email, title):
    r = srv.one("SELECT COUNT(*) AS n FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.email = ? AND "
                "n.title LIKE ? AND n.channel = 'app'", email, f"%{title}%")
    return r["n"]


def totp_login(web, srv, email):
    """Active la double authentification d'un membre de l'equipe, comme il le ferait dans son navigateur."""
    from services import security as SEC
    web.form("/compte/securite", dict(action="totp_start"), "/compte/securite")
    page = web.get("/compte/securite").text
    secret = re.search(r'class="code"[^>]*>([A-Z2-7 ]+)<', page).group(1).replace(" ", "")
    web.form("/compte/securite", dict(action="totp_confirm", code=SEC.totp_now(secret)), "/compte/securite")
    return secret


# ==========================================================================
# 1. SCENARIO REEL
# ==========================================================================
def scenario(srv):
    S = "Scénario réel"
    base = srv.url
    from playwright.sync_api import sync_playwright

    # --- Equipe ChantierVrai ---
    boss = Web(base).register("fondateur@chantiervrai.ci", name="Fondateur")
    srv.flask("creer-admin", "fondateur@chantiervrai.ci")
    check(S, "Admin : la 2FA est exigée avant l'administration",
          boss.get("/admin", allow_redirects=False).headers.get("Location", "").endswith("/compte/securite"))
    totp_login(boss, srv, "fondateur@chantiervrai.ci")
    check(S, "Admin : accès après activation de la 2FA", boss.get("/admin").status_code == 200)
    boss.form("/admin/abonnements", dict(action="prices", price_essentiel="15000", price_pro="45000", vat_rate="18",
                                         inspection_price="50000", inspection_payout="35000",
                                         seller="ChantierVrai SAS\nAbidjan, Cocody\nRCCM CI-ABJ-2026-B-0001",
                                         bank="Banque X - IBAN CI00 0000"), "/admin")
    team = {}
    for role in ("verification", "support", "finance"):
        w = Web(base).register(f"{role}@chantiervrai.ci", name=role.title())
        boss.form("/admin/equipe", dict(action="add", email=f"{role}@chantiervrai.ci", role=role), "/admin/equipe")
        totp_login(w, srv, f"{role}@chantiervrai.ci")
        team[role] = w
    check(S, "Équipe : 3 membres avec rôle et 2FA", srv.one("SELECT COUNT(*) n FROM users WHERE is_admin=1 AND totp_on=1")["n"] == 4)

    # --- Propriétaire de la diaspora : inscription et chantier dans un vrai navigateur ---
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        page = b.new_page(viewport={"width": 1280, "height": 900}, locale="fr-FR")
        t0 = time.time(); clicks = 0
        page.goto(base + "/inscription")
        page.check("input[name=role][value=proprio]"); clicks += 1
        page.fill("input[name=name]", "Aminata Koné"); page.fill("input[name=email]", "aminata@exemple.fr")
        page.fill("input[name=phone]", "+33 6 12 34 56 78"); page.fill("input[name=password]", PW)
        page.check("input[name=terms]"); clicks += 1
        page.click("button[type=submit]"); clicks += 1
        page.wait_for_load_state()
        check(S, "Propriétaire : inscription dans le navigateur", "Bien démarrer" in page.content())
        page.screenshot(path=os.path.join(OUT, "01_bien_demarrer.png"), full_page=True)
        page.click("text=Créer votre premier chantier"); clicks += 1
        page.wait_for_load_state()
        page.fill("input[name=name]", "Villa familiale Bingerville")
        page.fill("input[name=address]", "Bingerville, quartier Akandjé")
        page.fill("input[name=lat]", str(SITE[0])); page.fill("input[name=lng]", str(SITE[1]))
        page.fill("#budget", "18000000"); page.click("#split"); clicks += 2
        page.check("input[name=require_inspection]"); clicks += 1
        page.screenshot(path=os.path.join(OUT, "02_creation.png"), full_page=True)
        page.click("text=Créer le chantier"); clicks += 1
        page.wait_for_load_state()
        onboarding_s = round(time.time() - t0, 1)
        pid = int(re.search(r"/chantiers/(\d+)", page.url).group(1))
        R["parcours"].append({"parcours": "Inscription du propriétaire et création du chantier (navigateur)",
                              "secondes": onboarding_s, "clics": clicks, "champs_saisis": 7})
        amounts = [r["amount"] for r in srv.sql("SELECT amount FROM steps WHERE project_id=? ORDER BY position", pid)]
        check(S, "Création : budget de 18 000 000 FCFA réparti sur les étapes", sum(amounts) == 18_000_000, sum(amounts))
        check(S, "Création : inspection obligatoire cochée, paiement suivi par défaut",
              srv.one("SELECT require_inspection, pay_mode FROM projects WHERE id=?", pid)[:] == (1, "suivi"))
        code = srv.one("SELECT invite_code FROM projects WHERE id=?", pid)["invite_code"]
        page.goto(base + "/")
        wa = page.get_attribute("a[href^='https://wa.me']", "href")
        check(S, "Invitation : message WhatsApp prêt avec le code", wa and code in wa)
        cookies = page.context.cookies()
        b.close()
    own = Web(base)
    for ck in cookies:
        own.cookies.set(ck["name"], ck["value"], domain=ck["domain"], path=ck["path"])

    # --- Chef de chantier : inscription web, puis tout depuis l'application (API) ---
    Web(base).register("koffi@chef.ci", "chef", name="Koffi Yao", phone="0707070707")
    chef = Api(base).login("koffi@chef.ci")
    j = chef.call("POST", "/api/v1/rejoindre", json={"code": code}).json()
    check(S, "Chef : rejoint le chantier depuis l'application", j.get("ok"), j)
    steps = [dict(r) for r in srv.sql("SELECT id, name, amount FROM steps WHERE project_id=? ORDER BY position", pid)]

    # Fondations : 6 photos sur 2 semaines (heure du serveur), toutes sur le terrain
    t0 = time.time()
    ok = 0
    for k in range(6):
        lat, lng = offset(*SITE, (k * 9) % 40 - 20, (k * 13) % 50 - 25)
        r = chef.proof(pid, jpeg(scene(100 + k), lat, lng), lat, lng)
        ok += r.status_code == 201 and r.json()["ok"]
    check(S, "Preuves : 6 photos du terrain acceptées", ok == 6, f"{ok}/6")
    R["parcours"].append({"parcours": "Envoi d'une photo par le chef (application, moyenne)",
                          "secondes": round((time.time() - t0) / 6, 2), "clics": 2, "champs_saisis": 0})
    st1 = steps[0]
    j = chef.call("POST", f"/api/v1/chantiers/{pid}/etapes/{st1['id']}/declarer", json={}).json()
    check(S, "Chef : déclare « Fondations » terminée", j.get("ok"), j)
    check(S, "Propriétaire : alerté de l'inspection à commander (étape critique)", notes(srv, "aminata@exemple.fr", "Inspection à commander") == 1)

    # Validation impossible sans inspection
    h = own.form(f"/chantiers/{pid}/etapes/{st1['id']}/valider", dict(override="1"), f"/chantiers/{pid}/etapes/{st1['id']}").text
    flashes = re.findall(r'class="flash[^"]*"[^>]*>\s*(.*?)\s*<', h, re.S)
    check(S, "Validation bloquée sans inspection conforme",
          srv.one("SELECT status FROM steps WHERE id=?", st1["id"])["status"] == "declare"
          and any("inspection" in x for x in flashes), flashes)

    # Inspection : commande, paiement, attribution, visite, rapport, versement
    Web(base).register("awa@inspection.ci", "inspecteur", name="Awa Traoré", zone="Bingerville", phone="0505050505")
    insp_uid = srv.one("SELECT id FROM users WHERE email='awa@inspection.ci'")["id"]
    team["verification"].form("/admin/action", dict(action="verify", id=insp_uid), "/admin")
    r = own.form(f"/chantiers/{pid}/inspections", dict(step_id=st1["id"], message="Ferraillage des semelles"),
                 f"/chantiers/{pid}?onglet=dossier", follow=False)
    inv = int(r.headers["Location"].split("/")[-1])
    own.form(f"/compte/factures/{inv}", {}, f"/compte/factures/{inv}")
    rid = srv.one("SELECT id, status FROM inspection_requests")
    check(S, "Inspection : payée à ChantierVrai, en attente d'attribution", rid["status"] == "a_attribuer")
    team["verification"].form("/admin/inspections", dict(action="assign", id=rid["id"], inspector_id=insp_uid), "/admin")
    iid = srv.one("SELECT id FROM inspections")["id"]
    insp = Api(base).login("awa@inspection.ci")
    insp_web = Web(base)
    insp_web.form("/connexion", dict(email="awa@inspection.ci", password=PW), "/connexion")
    insp_web.form(f"/inspections/{iid}/reponse", dict(decision="accepter"))
    r = insp.proof(pid, jpeg(scene(300), *SITE), *SITE, extra={"inspection_id": str(iid)})
    check(S, "Inspectrice : photo vérifiée envoyée depuis l'application", r.status_code == 201 and r.json()["ok"], r.text[:200])
    insp_web.form(f"/inspections/{iid}/rapport", dict(verdict="conforme", report="Semelles conformes au plan, enrobage 4 cm, "
                                                                                     "ferraillage HA12 vérifié."), f"/chantiers/{pid}")
    check(S, "Inspection : rapport conforme déposé", srv.one("SELECT verdict FROM inspections WHERE id=?", iid)["verdict"] == "conforme")
    team["finance"].form("/admin/inspections", dict(action="payout", id=iid, reference="WAVE-INSP-001"), "/admin")
    check(S, "Finance : inspectrice payée par ChantierVrai", srv.one("SELECT paid FROM inspections WHERE id=?", iid)["paid"] == 1)

    # Contrôles de l'étape faits, validation, bon à payer, paiement déclaré, confirmé par le chef
    srv.sql("UPDATE step_checks SET status='conforme', checked_at=? WHERE step_id=? AND required=1", ago(0), st1["id"])
    t0 = time.time()
    r = own.form(f"/chantiers/{pid}/etapes/{st1['id']}/valider", {}, f"/chantiers/{pid}/etapes/{st1['id']}", follow=False)
    check(S, "Propriétaire : validation → bon à payer", r.headers.get("Location", "").endswith(f"/paiements/etape/{st1['id']}"))
    own.form(f"/paiements/etape/{st1['id']}", dict(amount=str(st1["amount"]), method="mobile_money", reference="WAVE-TX-77120"),
             f"/paiements/etape/{st1['id']}")
    R["parcours"].append({"parcours": "Valider une étape et déclarer son paiement (propriétaire)",
                          "secondes": round(time.time() - t0, 2), "clics": 3, "champs_saisis": 2})
    pay = chef.call("GET", "/api/v1/paiements").json()["a_confirmer"]
    check(S, "Chef : voit le paiement à confirmer dans l'application", len(pay) == 1 and pay[0]["reference"] == "WAVE-TX-77120")
    chef.call("POST", f"/api/v1/paiements/recus/{pay[0]['id']}", json={"action": "confirm"})
    check(S, "Étape payée après confirmation du chef", srv.one("SELECT status FROM steps WHERE id=?", st1["id"])["status"] == "paye")

    # --- Étape 2 sans réponse du propriétaire : relances, chef invité au litige, médiation ---
    st2 = steps[1]
    for k in range(3):
        lat, lng = offset(*SITE, 10 * k, -8 * k)
        chef.proof(pid, jpeg(scene(200 + k), lat, lng), lat, lng)
    chef.call("POST", f"/api/v1/chantiers/{pid}/etapes/{st2['id']}/declarer", json={})
    srv.sql("UPDATE steps SET declared_at=? WHERE id=?", ago(2), st2["id"])
    srv.flask("quotidien")
    check(S, "Relance J+2 du propriétaire, message explicite", notes(srv, "aminata@exemple.fr", "Étape à valider") >= 2)
    srv.sql("UPDATE steps SET declared_at=? WHERE id=?", ago(8), st2["id"])
    srv.flask("quotidien")
    check(S, "Sans réponse à J+7 : pas de validation automatique (désactivée par défaut)",
          srv.one("SELECT status FROM steps WHERE id=?", st2["id"])["status"] == "declare")
    check(S, "Chef invité à ouvrir un litige", notes(srv, "koffi@chef.ci", "Sans réponse du propriétaire") == 1)
    chef_web = Web(base)
    chef_web.form("/connexion", dict(email="koffi@chef.ci", password=PW), "/connexion")
    check(S, "Chef : voit les règles de son chantier (inspection exigée)",
          "Inspection indépendante obligatoire" in chef_web.get(f"/chantiers/{pid}").text)
    chef_web.form(f"/chantiers/{pid}/litiges", dict(step_id=st2["id"], subject="Soubassement non validé",
                                                    text="Étape terminée depuis 8 jours, preuves envoyées, aucune réponse."),
                  f"/chantiers/{pid}")
    did = srv.one("SELECT id FROM disputes")["id"]
    chef_web.form(f"/litiges/{did}", dict(action="mediation"), f"/litiges/{did}")
    team["support"].form(f"/litiges/{did}", dict(action="resolve", outcome="chef", amount=str(st2["amount"]),
                                                 text="Les 3 photos vérifiées montrent le soubassement terminé. L'étape est due."),
                         f"/litiges/{did}")
    d = srv.one("SELECT status, outcome FROM disputes WHERE id=?", did)
    check(S, "Litige : médiation demandée, décision motivée en faveur du chef", (d["status"], d["outcome"]) == ("resolu", "chef"))

    # --- Matériaux : fournisseur, commande, réception comptée, paiement direct, commission ---
    sup = Web(base).register("depot@quincaillerie.ci", "fournisseur", name="Quincaillerie du Carrefour",
                             phone="0102030405", zone="Bingerville", supplier_terms="1")
    sup_uid = srv.one("SELECT id FROM users WHERE email='depot@quincaillerie.ci'")["id"]
    team["verification"].form("/admin/action", dict(action="verify", id=sup_uid), "/admin")
    sup.form("/fournisseur/catalogue", dict(action="add", name="Ciment CPJ 42,5 (sac 50 kg)", unit="sac", price="5500"),
             "/fournisseur/catalogue")
    prod = srv.one("SELECT id FROM products WHERE supplier_id=?", sup_uid)
    check(S, "Fournisseur : inscrit, conditions acceptées, vérifié, catalogue", prod is not None)
    R["anomalies"] += [] if prod else ["Ajout de produit au catalogue introuvable par la recette (voir journal)"]

    # --- Abonnement : fin d'essai, choix Pro, paiement ---
    srv.sql("UPDATE subscriptions SET trial_end=? WHERE user_id=(SELECT id FROM users WHERE email='aminata@exemple.fr')", ago(1))
    check(S, "Fin d'essai : bandeau et création bloquée", "essai gratuit est terminé" in own.get("/").text)
    r = own.form("/compte/abonnement", dict(action="choose", plan="pro", cycle="mois"), "/compte/abonnement", follow=False)
    inv = int(r.headers["Location"].split("/")[-1])
    own.form(f"/compte/factures/{inv}", {}, f"/compte/factures/{inv}")
    s = srv.one("SELECT status, plan FROM subscriptions WHERE user_id=(SELECT id FROM users WHERE email='aminata@exemple.fr')")
    check(S, "Abonnement Pro payé et actif", (s["status"], s["plan"]) == ("actif", "pro"))
    fac = srv.one("SELECT amount, amount_ht, vat FROM billing_invoices WHERE id=?", inv)
    check(S, "Facture TTC 45 000 = HT + TVA 18 %", (fac["amount"], fac["amount_ht"] + fac["vat"]) == (45000, 45000))

    # --- Contrôles transverses ---
    reg = own.get(f"/chantiers/{pid}/paiements?format=csv").text
    check(S, "Registre des paiements exporté (CSV) avec la référence", "WAVE-TX-77120" in reg)
    check(S, "Export comptable disponible", own.get(f"/chantiers/{pid}/export-comptable.csv").status_code == 200)
    check(S, "Aucune erreur serveur pendant le scénario", not srv.errors_in_log(), srv.errors_in_log()[:3])
    return pid, chef


# ==========================================================================
# 2. EFFICACITE : FRAUDE PHOTO
# ==========================================================================
def fraude(srv):
    S = "Fraude photo"
    base = srv.url
    own = Web(base).register("test.fraude@exemple.fr", name="Test Fraude")
    data = dict(name="Chantier de mesure", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100",
                start_date=datetime.now().date().isoformat(), pay_mode="suivi", require_app_capture="1",
                step_name_0="Élévation des murs", step_amount_0="5000000", step_days_0="60")
    r = own.form("/chantiers/nouveau", data, "/chantiers/nouveau", follow=False)
    pid = int(r.headers["Location"].split("/")[-1])
    code = srv.one("SELECT invite_code FROM projects WHERE id=?", pid)["invite_code"]
    Web(base).register("chef.fraude@chef.ci", "chef", name="Chef Fraude", phone="0700000001")
    chef = Api(base).login("chef.fraude@chef.ci")
    chef.call("POST", "/api/v1/rejoindre", json={"code": code})
    tok = chef.call("GET", f"/api/v1/chantiers/{pid}").json()["project"]["capture_token"]

    def send(img_bytes, **kw):
        kw.setdefault("token", tok)
        r = chef.proof(pid, img_bytes, **kw)
        if r.status_code != 201:
            return None, r.text[:200]
        j = r.json()
        return ("signalee" if j["ok"] and j.get("a_verifier") else j["ok"]), "; ".join(j["reasons"]) or (
            "acceptée, signalée au propriétaire" if j.get("a_verifier") else "")

    def lot(nom, attendu, n, make):
        res = []
        for i in range(n):
            ok, why = send(**make(i))
            res.append((ok, why))
        detectees = sum(1 for ok, _w in res if ok is False)
        signalees = sum(1 for ok, _w in res if ok == "signalee")
        acceptees = sum(1 for ok, _w in res if ok is True)
        motif = next((w for ok, w in res if w and ok is False), "") or next((w for _ok, w in res if w), "")
        taux = (detectees + signalees) / n if attendu == "refus" else acceptees / n
        R["fraude"].append({"cas": nom, "attendu": attendu, "envois": n, "refusees": detectees, "signalees": signalees,
                            "acceptees": acceptees, "taux_bon": round(taux * 100), "motif_exemple": motif[:160]})
        print(f"    {nom} : {acceptees} acceptées, {signalees} signalées, {detectees} refusées sur {n}")
        return res

    def site(i, spread=60):
        return offset(*SITE, (i * 37) % (2 * spread) - spread, (i * 53) % (2 * spread) - spread)

    originals = []

    def legit(i):
        lat, lng = site(i)
        im = scene(1000 + i); originals.append(im)
        return dict(img_bytes=jpeg(im, lat, lng), lat=lat, lng=lng)
    lot("Vraies photos, scènes différentes", "acceptation", 40, legit)

    def same_place(i):
        lat, lng = site(i)
        return dict(img_bytes=jpeg(reshoot(originals[i], 50 + i), lat, lng), lat=lat, lng=lng)
    lot("Vraies photos du même endroit, autre jour (cadrage et lumière différents)", "acceptation", 20, same_place)

    def far(i):
        lat, lng = offset(*SITE, 2000 + 2000 * i, 1500)
        return dict(img_bytes=jpeg(scene(2000 + i), lat, lng), lat=lat, lng=lng)
    lot("Photo prise ailleurs (2 à 20 km)", "refus", 10, far)

    def near_edge(i):
        lat, lng = offset(*SITE, 150 + 30 * i, 0)
        return dict(img_bytes=jpeg(scene(2100 + i), lat, lng), lat=lat, lng=lng)
    lot("Photo prise juste hors du terrain (150 à 420 m)", "refus", 10, near_edge)

    lot("Aucune position GPS", "refus", 10, lambda i: dict(img_bytes=jpeg(scene(2200 + i))))
    lot("Faux GPS signalé par le téléphone", "refus", 10,
        lambda i: dict(img_bytes=jpeg(scene(2300 + i), *SITE), lat=SITE[0], lng=SITE[1], mocked=True))

    def incoherent(i):
        plat, plng = offset(*SITE, 5000, 0)          # GPS du fichier ailleurs, telephone sur le terrain
        return dict(img_bytes=jpeg(scene(2400 + i), plat, plng), lat=SITE[0], lng=SITE[1])
    lot("Fichier pris ailleurs, téléphone sur le terrain", "refus", 10, incoherent)

    def old(i):
        return dict(img_bytes=jpeg(scene(2500 + i), *SITE), lat=SITE[0], lng=SITE[1],
                    captured_at=(time.time() - 3600 * (2 + i)) * 1000)
    lot("Photo ancienne (2 à 11 h) envoyée comme prise maintenant", "refus", 10, old)

    def gallery(i):
        when = datetime.now(timezone.utc) - timedelta(days=3 + i)
        return dict(img_bytes=jpeg(scene(2600 + i), SITE[0], SITE[1], when.replace(tzinfo=None)), lat=SITE[0], lng=SITE[1],
                    capture="fichier", token="")
    lot("Photo importée de la galerie (chantier qui exige la caméra)", "refus", 10, gallery)

    def bad_token(i):
        return dict(img_bytes=jpeg(scene(2700 + i), *SITE), lat=SITE[0], lng=SITE[1], token="jeton-invente")
    lot("Jeton de capture inventé (application modifiée)", "refus", 10, bad_token)

    def before_token(i):
        return dict(img_bytes=jpeg(scene(2800 + i), *SITE), lat=SITE[0], lng=SITE[1],
                    captured_at=(time.time() - 3600 * 24) * 1000)
    lot("Photo antérieure à l'ouverture de l'application", "refus", 10, before_token)

    first = jpeg(originals[0], *SITE)
    send(first)  # deja envoye une fois (identique au premier lot ? on renvoie le meme fichier)
    lot("Même fichier renvoyé", "refus", 10, lambda i: dict(img_bytes=first, lat=SITE[0], lng=SITE[1]))

    lot("Recadrage léger d'une preuve déjà envoyée", "refus", 20,
        lambda i: dict(img_bytes=jpeg(recrop(originals[i], 70 + i), *SITE), lat=SITE[0], lng=SITE[1]))
    lot("Photo d'écran plein cadre d'une preuve", "refus", 20,
        lambda i: dict(img_bytes=jpeg(screen_photo(originals[20 + i], 90 + i), *SITE), lat=SITE[0], lng=SITE[1]))
    lot("Photo d'écran avec le bord de l'écran visible", "refus", 10,
        lambda i: dict(img_bytes=jpeg(screen_photo(originals[i], 110 + i, bezel=True), *SITE), lat=SITE[0], lng=SITE[1]))
    lot("Photo d'un autre chantier prise sur le terrain (sans IA)", "refus", 10,
        lambda i: dict(img_bytes=jpeg(scene(9000 + i), *SITE), lat=SITE[0], lng=SITE[1]))


# ==========================================================================
# 3. EFFICACITE : CHARGE AVEC UN VOLUME REALISTE
# ==========================================================================
def charge(srv, pid, chef):
    S = "Charge"
    base = srv.url
    # Volume : 60 proprietaires, 120 chantiers, 6 etapes chacun, 25 preuves par chantier, 4 paiements
    c = srv.db()
    now = datetime.now(timezone.utc).isoformat()
    owner_ids = []
    from werkzeug.security import generate_password_hash
    pwh = generate_password_hash(PW)
    for i in range(60):
        cur = c.execute("INSERT INTO users (name, email, phone, password_hash, role, created_at, terms_at) VALUES (?,?,?,?,?,?,?)",
                        (f"Proprio {i}", f"p{i}@charge.ci", "0", pwh, "proprio", now, now))
        owner_ids.append(cur.lastrowid)
    for i in range(120):
        o = owner_ids[i % 60]
        cur = c.execute("INSERT INTO projects (owner_id, name, address, lat, lng, radius, invite_code, created_at, pay_mode) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (o, f"Chantier {i}", "Abidjan", SITE[0], SITE[1], 100, f"CH{i:05d}", now, "suivi"))
        p = cur.lastrowid
        for k in range(6):
            st = c.execute("INSERT INTO steps (project_id, position, name, amount, status, planned_days, started_at) "
                           "VALUES (?,?,?,?,?,?,?)", (p, k, f"Étape {k}", 2_000_000, "paye" if k < 2 else ("en_cours" if k == 2 else "attente"),
                                                    20, now)).lastrowid
            if k < 3:
                for n in range(8):
                    c.execute("INSERT INTO proofs (project_id, step_id, user_id, filename, sha256, created_at, ok, reasons, kind, source) "
                              "VALUES (?,?,?,?,?,?,?,?,?,?)", (p, st, o, "x.jpg", f"{p}-{st}-{n}", now, 1, "[]", "photo", "chef"))
    c.commit(); c.close()
    total = srv.one("SELECT (SELECT COUNT(*) FROM projects) p, (SELECT COUNT(*) FROM proofs) pr, (SELECT COUNT(*) FROM steps) s")
    R["volume"] = dict(chantiers=total["p"], preuves=total["pr"], etapes=total["s"])

    owners = []
    for i in range(20):
        w = Web(base); w.form("/connexion", dict(email=f"p{i}@charge.ci", password=PW), "/connexion"); owners.append(w)
    own_proj = {i: [r["id"] for r in srv.sql("SELECT id FROM projects WHERE owner_id=(SELECT id FROM users WHERE email=?)",
                                               f"p{i}@charge.ci")] for i in range(20)}
    pages = [("Accueil du propriétaire", lambda i: owners[i].get("/")),
             ("Page du chantier (étapes)", lambda i: owners[i].get(f"/chantiers/{own_proj[i][0]}?onglet=etapes")),
             ("Page du chantier (preuves)", lambda i: owners[i].get(f"/chantiers/{own_proj[i][0]}?onglet=preuves")),
             ("Registre des paiements", lambda i: owners[i].get(f"/chantiers/{own_proj[i][0]}/paiements")),
             ("API : chantier du chef (application)", lambda i: chef.call("GET", f"/api/v1/chantiers/{pid}"))]
    for users in (5, 20):
        for name, fn in pages:
            times, errors = [], 0
            lock = threading.Lock()

            def hit(i):
                nonlocal errors
                t = time.time(); r = fn(i % 20); d = (time.time() - t) * 1000
                with lock:
                    times.append(d)
                    if r.status_code >= 400:
                        errors += 1
            with ThreadPoolExecutor(users) as ex:
                list(ex.map(hit, range(users * 6)))
            times.sort()
            row = {"page": name, "utilisateurs_simultanes": users, "requetes": len(times),
                   "mediane_ms": round(statistics.median(times)), "p95_ms": round(times[int(len(times) * 0.95) - 1]),
                   "erreurs": errors}
            R["charge"].append(row)
            print(f"    {name} x{users} : médiane {row['mediane_ms']} ms, p95 {row['p95_ms']} ms, erreurs {errors}")
    t = time.time(); out = srv.flask("quotidien"); d = time.time() - t
    R["charge"].append({"page": "Tâche quotidienne (120 chantiers)", "utilisateurs_simultanes": 1, "requetes": 1,
                        "mediane_ms": round(d * 1000), "p95_ms": round(d * 1000), "erreurs": int("Traceback" in out)})
    check(S, "Aucune erreur sous charge", all(r["erreurs"] == 0 for r in R["charge"]))
    check(S, "Pages sous 1 s au 95e centile avec 20 utilisateurs simultanés",
          all(r["p95_ms"] < 1000 for r in R["charge"] if r["utilisateurs_simultanes"] == 20))


def main():
    srv = Serveur().start()
    try:
        print("1. Scénario réel")
        pid, chef = scenario(srv)
        print("2. Fraude photo")
        fraude(srv)
        print("3. Charge")
        charge(srv, pid, chef)
        R["erreurs_serveur"] = srv.errors_in_log()[:20]
    finally:
        srv.stop()
    R["fin"] = datetime.now().isoformat(timespec="seconds")
    json.dump(R, open(os.path.join(OUT, "resultats.json"), "w"), ensure_ascii=False, indent=1)
    n_ok = sum(c["ok"] for c in R["controles"])
    print(f"\n{n_ok}/{len(R['controles'])} contrôles réussis. Résultats : recette/sortie/resultats.json")


if __name__ == "__main__":
    main()
