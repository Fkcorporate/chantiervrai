"""Lecture des maquettes BIM au format IFC (STEP, IFC2x3 et IFC4), sans dependance.

On en tire ce qui sert au suivi du chantier : les niveaux (nom, altitude), le nombre d'elements
porteurs et de second oeuvre par niveau, et les volumes quand la maquette les contient. La
geometrie 3D n'est pas lue : pour la vue 3D, exporter aussi la maquette en GLB.
"""
import re

ELEMENTS = {
    "IFCFOOTING": "Fondations", "IFCPILE": "Pieux", "IFCCOLUMN": "Poteaux", "IFCBEAM": "Poutres", "IFCSLAB": "Dalles",
    "IFCWALL": "Murs", "IFCWALLSTANDARDCASE": "Murs", "IFCSTAIR": "Escaliers", "IFCSTAIRFLIGHT": "Escaliers",
    "IFCRAMP": "Rampes", "IFCROOF": "Toiture", "IFCDOOR": "Portes", "IFCWINDOW": "Fenêtres", "IFCRAILING": "Garde-corps",
    "IFCCOVERING": "Revêtements", "IFCMEMBER": "Charpente", "IFCPLATE": "Plaques",
    "IFCFLOWTERMINAL": "Équipements (plomberie, électricité)", "IFCSANITARYTERMINAL": "Équipements (plomberie, électricité)",
    "IFCLIGHTFIXTURE": "Équipements (plomberie, électricité)", "IFCOUTLET": "Équipements (plomberie, électricité)",
}
VOLUME_NAMES = ("NetVolume", "GrossVolume", "Volume")
_LINE = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;\s*$", re.S)


class IFCError(ValueError):
    pass


def _decode(s):
    """Chaines IFC : '' pour l'apostrophe, \\X2\\....\\X0\\ et \\X\\.. pour les accents."""
    s = s.replace("''", "'")
    s = re.sub(r"\\X2\\([0-9A-F]+)\\X0\\",
               lambda m: "".join(chr(int(m.group(1)[i:i + 4], 16)) for i in range(0, len(m.group(1)), 4)), s)
    s = re.sub(r"\\X\\([0-9A-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("latin-1"), s)
    return s


def _args(text):
    """Decoupe la liste d'attributs d'une entite en valeurs Python (str, float, ref '#n', listes, None)."""
    out, i, n = [], 0, len(text)
    stack = [out]
    while i < n:
        c = text[i]
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'" and (j + 1 >= n or text[j + 1] != "'"):
                    break
                j += 2 if text[j] == "'" else 1
            stack[-1].append(_decode(text[i + 1:j]))
            i = j + 1
        elif c == "(":
            lst = []
            stack[-1].append(lst)
            stack.append(lst)
            i += 1
        elif c == ")":
            if len(stack) > 1:
                stack.pop()
            i += 1
        elif c in ", \r\n\t":
            i += 1
        else:
            j = i
            while j < n and text[j] not in ",()":
                j += 1
            tok = text[i:j].strip()
            if tok in ("$", "*"):
                stack[-1].append(None)
            elif tok.startswith("#"):
                stack[-1].append(tok)
            elif tok.startswith("."):
                stack[-1].append(tok.strip("."))
            else:
                try:
                    stack[-1].append(float(tok))
                except ValueError:
                    stack[-1].append(tok)
            i = j
    return out


def parse(data):
    """data : contenu du fichier .ifc (bytes ou str). Retourne un resume serialisable en JSON."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    if "ISO-10303-21" not in data[:200]:
        raise IFCError("not an IFC file")
    schema = (re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", data) or [None, "?"])[1]
    body = data.split("DATA;", 1)[-1].split("ENDSEC;", 1)[0]
    ents = {}
    for raw in re.split(r";\s*\n(?=\s*#)", body):
        raw = raw.strip()
        if not raw.startswith("#"):
            continue
        m = _LINE.match(raw if raw.endswith(";") else raw + ";")
        if m:
            ents["#" + m.group(1)] = (m.group(2).upper(), m.group(3))
    if not ents:
        raise IFCError("no entities")

    def attrs(ref):
        return _args(ents[ref][1]) if ref in ents else []

    project = next((attrs(k)[2] for k, (t, _a) in ents.items() if t == "IFCPROJECT"), None)
    building = next((attrs(k)[2] for k, (t, _a) in ents.items() if t == "IFCBUILDING"), None)
    storeys = {}
    for k, (t, _a) in ents.items():
        if t == "IFCBUILDINGSTOREY":
            a = attrs(k)
            elev = a[9] if len(a) > 9 and isinstance(a[9], float) else None
            storeys[k] = {"key": a[0] or k, "name": a[2] or a[0] or k, "elevation": elev, "counts": {}, "volume": 0.0}
    volumes = {}
    for k, (t, _a) in ents.items():
        if t == "IFCRELDEFINESBYPROPERTIES":
            a = attrs(k)
            objs, pdef = (a[4] if len(a) > 4 else []), (a[5] if len(a) > 5 else None)
            if not pdef or pdef not in ents or ents[pdef][0] != "IFCELEMENTQUANTITY":
                continue
            qa = attrs(pdef)
            vol = None
            for q in (qa[5] if len(qa) > 5 and isinstance(qa[5], list) else []):
                if q in ents and ents[q][0] == "IFCQUANTITYVOLUME":
                    qq = attrs(q)
                    if qq and qq[0] in VOLUME_NAMES and isinstance(qq[3] if len(qq) > 3 else None, float):
                        vol = qq[3]
                        if qq[0] == "NetVolume":
                            break
            if vol is not None:
                for o in objs or []:
                    volumes[o] = vol
    placed = set()
    totals = {}
    for k, (t, _a) in ents.items():
        if t == "IFCRELCONTAINEDINSPATIALSTRUCTURE":
            a = attrs(k)
            elems, where = (a[4] if len(a) > 4 else []), (a[5] if len(a) > 5 else None)
            st = storeys.get(where)
            for e in elems or []:
                et = ents.get(e, (None,))[0]
                label = ELEMENTS.get(et)
                if not label:
                    continue
                placed.add(e)
                if st is not None:
                    st["counts"][label] = st["counts"].get(label, 0) + 1
                    st["volume"] += volumes.get(e, 0.0)
    for k, (t, _a) in ents.items():
        label = ELEMENTS.get(t)
        if label:
            totals[label] = totals.get(label, 0) + 1
    ordered = sorted(storeys.values(), key=lambda s: (s["elevation"] is None, s["elevation"] or 0, s["name"]))
    for s in ordered:
        s["volume"] = round(s["volume"], 2)
    return {"schema": schema, "project": project, "building": building, "storeys": ordered, "totals": totals,
            "unplaced": sum(totals.values()) - len(placed), "volume": round(sum(volumes.values()), 2),
            "entities": len(ents)}


def diff(old, new):
    """Changements entre deux versions : niveaux ajoutes ou retires, elements en plus ou en moins par niveau."""
    o = {s["name"]: s for s in old["storeys"]}
    n = {s["name"]: s for s in new["storeys"]}
    changes = []
    for name in n:
        if name not in o:
            changes.append(("storey_added", name, None, None))
            continue
        for label in sorted(set(o[name]["counts"]) | set(n[name]["counts"])):
            a, b = o[name]["counts"].get(label, 0), n[name]["counts"].get(label, 0)
            if a != b:
                changes.append(("count", name, label, b - a))
    for name in o:
        if name not in n:
            changes.append(("storey_removed", name, None, None))
    return changes


def sample(levels=2, extra_columns=0, name="Villa R+1"):
    """Petite maquette IFC4 de demonstration et de test : fondations, poteaux, poutres, dalles et murs par niveau."""
    n = [100]
    lines = []

    def add(t, args):
        n[0] += 1
        lines.append(f"#{n[0]}={t}({args});")
        return f"#{n[0]}"

    proj = add("IFCPROJECT", f"'0proj',$,'{name}',$,$,$,$,$,$")
    bld = add("IFCBUILDING", "'0bld',$,'B\\X2\\00E2\\X0\\timent principal',$,$,$,$,$,.ELEMENT.,$,$,$")
    names = ["Fondations", "Rez-de-chauss\\X2\\00E9\\X0\\e"] + [f"\\X2\\00C9\\X0\\tage {i}" for i in range(1, levels)] + ["Toiture"]
    for i, nm in enumerate(names):
        st = add("IFCBUILDINGSTOREY", f"'0st{i}',$,'{nm}',$,$,$,$,$,.ELEMENT.,{(i - 1) * 3.0:.1f}")
        elems = []
        if i == 0:
            for k in range(12):
                e = add("IFCFOOTING", f"'0f{k}',$,'Semelle {k}',$,$,$,$,$,.PAD_FOOTING.")
                q = add("IFCQUANTITYVOLUME", "'NetVolume',$,$,0.54,$")
                eq = add("IFCELEMENTQUANTITY", f"'0q{k}f',$,'Qto',$,$,(#{q[1:]}))")
                add("IFCRELDEFINESBYPROPERTIES", f"'0r{k}f',$,$,$,({e}),{eq}")
                elems.append(e)
        elif i < len(names) - 1:
            for k in range(12 + (extra_columns if i == len(names) - 2 else 0)):
                e = add("IFCCOLUMN", f"'0c{i}{k}',$,'Poteau {k}',$,$,$,$,$,$")
                q = add("IFCQUANTITYVOLUME", "'NetVolume',$,$,0.12,$")
                eq = add("IFCELEMENTQUANTITY", f"'0q{i}{k}c',$,'Qto',$,$,({q}))")
                add("IFCRELDEFINESBYPROPERTIES", f"'0r{i}{k}c',$,$,$,({e}),{eq}")
                elems.append(e)
            elems += [add("IFCBEAM", f"'0b{i}{k}',$,'Poutre {k}',$,$,$,$,$,$") for k in range(14)]
            elems.append(add("IFCSLAB", f"'0s{i}',$,'Dalle',$,$,$,$,$,.FLOOR."))
            elems += [add("IFCWALL", f"'0w{i}{k}',$,'Mur {k}',$,$,$,$,$,$") for k in range(18)]
            elems += [add("IFCWINDOW", f"'0win{i}{k}',$,'Fen\\X2\\00EA\\X0\\tre',$,$,$,$,$,$,$,$,$,$") for k in range(6)]
        else:
            elems.append(add("IFCROOF", f"'0roof',$,'Toiture',$,$,$,$,$,$"))
        add("IFCRELCONTAINEDINSPATIALSTRUCTURE", f"'0rel{i}',$,$,$,({','.join(elems)}),{st}")
    head = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
            "FILE_NAME('villa.ifc','2026-11-14T00:00:00',(''),(''),'ChantierVrai','ChantierVrai','');\n"
            "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n")
    return head + "\n".join(lines) + "\nENDSEC;\nEND-ISO-10303-21;\n"
