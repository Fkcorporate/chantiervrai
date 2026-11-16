"""Verifie que chaque texte francais de l'application a sa traduction anglaise.
Lancement : python3 tools_check_translations.py   (a relancer apres chaque ajout de texte)"""
import ast, glob, json, os, re, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
cat = json.load(open(os.path.join(ROOT, "translations", "en.json"), encoding="utf-8"))
missing, ids = [], set()
for f in glob.glob(os.path.join(ROOT, "templates", "*.html")):
    txt = open(f, encoding="utf-8").read()
    for m in re.finditer(r'_\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')', txt):
        ids.add(ast.literal_eval(m.group(1)))
    for m in re.finditer(r'\bpl\([^,()]*(?:\([^()]*\)[^,()]*)*,\s*("(?:[^"\\]|\\.)*")', txt):   # {{ pl(n, "texte(s)") }}
        ids.add(ast.literal_eval(m.group(1)))
for f in [os.path.join(ROOT, "app.py")] + glob.glob(os.path.join(ROOT, "services", "*.py")):
    for n in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("_", "L") and n.args \
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
            ids.add(n.args[0].value)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "pl" and len(n.args) > 1 \
                and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
            ids.add(n.args[1].value)
for i in sorted(ids):
    if re.search(r"[A-Za-zÀ-ÿ]", i) and i not in cat and i not in ("FCFA",):
        missing.append(i)
print(f"{len(ids)} textes, {len(missing)} sans traduction anglaise")
for m in missing:
    print("  -", m)
sys.exit(1 if missing else 0)
