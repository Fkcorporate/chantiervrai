"""Vérification dans un vrai navigateur des gestes ajoutés : mots expliqués, bandeau hors ligne,
guide des autorisations, envoi d'une photo par réseau faible (mise en file), message qui se ferme."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outils import Serveur
from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sortie", "ui_")
PW = "Demo-Chantier-2026"
srv = Serveur().start()
srv.flask("demo")
c = srv.db()
pid = c.execute("SELECT id FROM projects WHERE name LIKE 'Villa%'").fetchone()[0]
c.execute("UPDATE steps SET status = 'en_cours', declared_at = NULL WHERE project_id = ? AND status = 'declare'", (pid,))
c.commit()
res = []


def ok(cond, label):
    res.append((bool(cond), label))
    print(("  ok  " if cond else "  KO  ") + label)


def login(page, email):
    page.goto(srv.url + "/connexion")
    page.fill("input[name=email]", email); page.fill("input[name=password]", PW)
    page.click("form button[type=submit]"); page.wait_for_load_state("networkidle")


with sync_playwright() as pw:
    br = pw.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
    mob = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)

    # --- Propriétaire : mots expliqués, message qui se ferme, hors ligne
    ctx = br.new_context(**mob); p = ctx.new_page(); errs = []
    p.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    login(p, "aminata@demo.chantiervrai.ci")
    ok(p.locator(".flash").count() == 0 or p.locator(".flash .flash-close").count() > 0, "messages : bouton de fermeture")
    p.goto(srv.url + "/"); p.wait_for_load_state("networkidle")
    ok(p.locator(".bottombar").is_visible() and p.locator(".appbar").is_visible() and not p.locator("header nav.top").is_visible(),
       "téléphone : onglets en bas et barre du haut, plus de menu en haut de page")
    p.click(".bottombar .bb-more"); p.wait_for_timeout(450)
    ok(p.locator("#nav-sheet").is_visible() and p.locator("#nav-sheet >> text=Déconnexion").is_visible(), "« Plus » ouvre le panneau du menu")
    p.mouse.click(195, 40); p.wait_for_timeout(400)
    ok(not p.locator("#nav-sheet").is_visible(), "toucher le fond referme le panneau")
    p.goto(srv.url + f"/chantiers/{pid}/financement"); p.wait_for_load_state("networkidle")
    terms = p.locator(".term")
    ok(terms.count() >= 2, f"financement : {terms.count()} mot(s) technique(s) expliqué(s)")
    t = p.locator(".term", has_text="trésorerie").first if p.locator(".term", has_text="trésorerie").count() else terms.first
    t.scroll_into_view_if_needed(); t.click()
    p.wait_for_timeout(250)
    ok(p.locator(".gloss-bubble").is_visible() and len(p.locator(".gloss-bubble span").inner_text()) > 20, "toucher un mot affiche son explication")
    p.screenshot(path=OUT + "glossaire.png")
    p.mouse.click(5, 5); p.wait_for_timeout(100)
    ok(p.locator(".gloss-bubble").count() == 0, "la bulle se ferme en touchant ailleurs")
    p.goto(srv.url + f"/chantiers/{pid}?onglet=etapes"); p.wait_for_load_state("networkidle")
    ok(p.locator(".term").count() >= 1, f"onglet Étapes : {p.locator('.term').count()} mot(s) expliqué(s)")
    ctx.set_offline(True); p.evaluate("window.dispatchEvent(new Event('offline'))"); p.wait_for_timeout(200)
    ok(p.locator(".netbar").is_visible(), "bandeau « hors ligne » affiché")
    p.screenshot(path=OUT + "horsligne.png")
    ctx.set_offline(False); p.evaluate("window.dispatchEvent(new Event('online'))"); p.wait_for_timeout(200)
    ok("rétablie" in p.locator(".netbar").inner_text(), "bandeau « connexion rétablie »")
    ok(not [e for e in errs if "favicon" not in e and "tile" not in e and "ERR_INTERNET_DISCONNECTED" not in e], f"aucune erreur JavaScript côté propriétaire {errs[:2]}")
    ctx.close()

    # --- Chef : guide des autorisations, puis photo envoyée par réseau faible
    ctx = br.new_context(**mob, geolocation={"latitude": 5.3521, "longitude": -3.8892}); p = ctx.new_page(); errs = []
    p.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    login(p, "koffi@demo.chantiervrai.ci")
    p.goto(srv.url + f"/chantiers/{pid}"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(400)
    ok(p.locator("#perm-guide").is_visible(), "premier envoi : guide des autorisations affiché")
    p.locator("#proof-form").scroll_into_view_if_needed()
    p.screenshot(path=OUT + "autorisations.png")
    ctx.grant_permissions(["geolocation", "camera"])
    p.reload(); p.wait_for_load_state("networkidle"); p.wait_for_timeout(1200)
    geo = p.locator("#perm-geo .tag").inner_text()
    ok("autorisée" in geo.lower(), f"position autorisée reconnue ({geo})")
    p.click("#shoot"); p.wait_for_timeout(1200)
    ok(p.locator("#camera").is_visible(), "caméra de l'application ouverte")
    p.click("#cam-snap")
    try:   # l'encodage de l'image est asynchrone : on attend le résultat plutôt qu'un délai fixe
        p.wait_for_function("!document.getElementById('send').disabled", timeout=4000)
    except Exception:
        pass
    ok(not p.locator("#send").is_disabled(), "photo prise : bouton d'envoi actif")
    p.route("**/preuves**", lambda r: r.abort("timedout") if r.request.method == "POST" else r.continue_())
    p.route("**/upload**", lambda r: r.abort("timedout") if r.request.method == "POST" else r.continue_())
    action = p.locator("#proof-form").get_attribute("action")
    p.route("**" + action, lambda r: r.abort("timedout") if r.request.method == "POST" else r.continue_())
    n0 = srv.db().execute("SELECT COUNT(*) FROM proofs WHERE project_id = ? AND capture = 'app'", (pid,)).fetchone()[0]
    p.click("#send"); p.wait_for_timeout(1500)
    st = p.locator("#gps-status").inner_text()
    ok("gardée" in st, f"réseau qui lâche : photo gardée sur le téléphone ({st[:60]}…)")
    ok(p.locator("#queue-status").is_visible(), "file d'attente affichée")
    p.screenshot(path=OUT + "reseau_faible.png")
    p.unroute("**" + action); p.unroute("**/preuves**"); p.unroute("**/upload**")
    p.evaluate("window.dispatchEvent(new Event('online'))"); p.wait_for_timeout(2500)
    n = srv.db().execute("SELECT COUNT(*) FROM proofs WHERE project_id = ? AND capture = 'app'", (pid,)).fetchone()[0]
    ok(n == n0 + 1, "réseau revenu : la photo gardée est arrivée au serveur")
    p.goto(srv.url + f"/chantiers/{pid}"); p.wait_for_load_state("networkidle"); p.wait_for_timeout(800)
    ok(not p.locator("#perm-guide").is_visible(), "après un premier envoi réussi, le guide ne s'affiche plus")
    p.click("#shoot"); p.wait_for_timeout(1200); p.click("#cam-snap"); p.wait_for_timeout(400)
    with p.expect_navigation():
        p.click("#send")
    p.wait_for_load_state("networkidle")
    ok(p.locator(".flash").count() >= 1, "bon réseau : envoi puis message de résultat sur la page du chantier (" + (p.locator(".flash").first.inner_text()[:50] if p.locator(".flash").count() else "") + ")")
    p.screenshot(path=OUT + "envoi_ok.png")
    ok(not [e for e in errs if "Failed to load resource" not in e], f"aucune erreur JavaScript côté chef {errs[:2]}")
    ctx.close()
    br.close()

print(f"\n{sum(1 for r in res if r[0])}/{len(res)} vérifications réussies")
print("journal serveur :", srv.errors_in_log() or "aucune erreur")
srv.stop()
