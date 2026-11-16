"""Prepare une base de demonstration pour les tests du client mobile (proprietaire, chef, chantier)."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import app as A
from datetime import date
PW = "Bingerville-2026"
own, chef = A.app.test_client(), A.app.test_client()
tok = lambda c, u="/": re.search(r'name="csrf" value="([^"]+)"', c.get(u).get_data(as_text=True)).group(1)
own.post("/inscription?lang=en", data=dict(csrf=tok(own, "/inscription?lang=en"), terms="1", role="proprio", name="Ama", email="ama@x.co.uk", password=PW))
chef.post("/inscription", data=dict(csrf=tok(chef, "/inscription"), terms="1", role="chef", name="Koffi", email="k@x.ci", password=PW, phone="0700000000"))
d = dict(csrf=tok(own, "/chantiers/nouveau"), name="Villa", address="Bingerville", lat="5.3521", lng="-3.8892", radius="100",
         pay_mode="suivi", require_app_capture="1", start_date=date.today().isoformat())
for i, (n, a, j) in enumerate(A.DEFAULT_STEPS):
    d[f"step_name_{i}"], d[f"step_amount_{i}"], d[f"step_days_{i}"] = n, str(a), str(j)
pid = int(own.post("/chantiers/nouveau", data=d).headers["Location"].split("/")[-1])
code = re.search(r'class="code">(\w+)<', own.get(f"/chantiers/{pid}").get_data(as_text=True)).group(1)
print(code)
