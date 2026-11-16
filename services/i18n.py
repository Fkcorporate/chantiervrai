"""Traductions : francais (langue source) et anglais.

- Dans le code : _("Texte en français %(x)s", x=valeur) traduit tout de suite dans la langue
  de l'utilisateur courant.
- L("…") cree un texte « paresseux », traduit plus tard dans la langue de chaque destinataire
  (notifications, journal du chantier, raisons de refus enregistrees en base).
- Le catalogue anglais est translations/en.json : { "texte français": "English text" }.
  Un texte absent du catalogue s'affiche en francais.
"""
import json
import os
import re

LANGS = {"fr": "Français", "en": "English"}
DEFAULT = "fr"
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_catalogs = {}
_MARK = "§"           # prefixe d'un texte paresseux enregistre en base


def catalog(lang):
    if lang not in _catalogs:
        path = os.path.join(_HERE, "translations", f"{lang}.json")
        try:
            with open(path, encoding="utf-8") as fh:
                _catalogs[lang] = json.load(fh)
        except FileNotFoundError:
            _catalogs[lang] = {}
    return _catalogs[lang]


def current_lang():
    try:
        from flask import g, has_request_context
        if has_request_context() or hasattr(g, "lang"):
            return getattr(g, "lang", DEFAULT)
    except RuntimeError:
        pass
    return DEFAULT


_PLURAL = re.compile(r"\((s|x|es)\)")


def pluralize(text, n, lang):
    """« 1 preuve(s) refusée(s) » -> « 1 preuve refusée », « 3 preuves refusées ».
    Français : singulier pour 0 et 1 ; anglais : singulier pour 1 seulement."""
    one = (abs(n) < 2) if lang == "fr" else (n == 1)
    return _PLURAL.sub("" if one else (lambda m: m.group(1)), text)


_PARAM = re.compile(r"%\((\w+)\)s")


def pluralize_params(text, params, lang):
    """Chaque « (s) » s'accorde avec le dernier nombre qui le précède dans la phrase
    (ou, à défaut, avec le premier nombre qui suit) :
    « %(a)s non-conformité(s) sur %(b)s contrôle(s) »."""
    nums = {k: v for k, v in params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if not nums or not _PLURAL.search(text):
        return text
    marks = [(m.start(), nums[m.group(1)]) for m in _PARAM.finditer(text) if m.group(1) in nums]
    if not marks:
        return text if len(nums) != 1 else pluralize(text, next(iter(nums.values())), lang)
    out, pos = [], 0
    bounds = [0] + [p for p, _n in marks[1:]] + [len(text)]
    for i in range(len(marks)):
        start, end = (0 if i == 0 else marks[i][0]), bounds[i + 1]
        out.append(pluralize(text[start:end], marks[i][1], lang))
    return "".join(out)


def translate(msg, lang=None, **params):
    lang = lang or current_lang()
    text = msg if lang == "fr" else catalog(lang).get(msg) or msg
    if params:
        if "(" in text:
            text = pluralize_params(text, params, lang)
        try:
            return text % {k: render(v, lang) for k, v in params.items()}
        except (KeyError, ValueError, TypeError):
            return msg % {k: render(v, "fr") for k, v in params.items()}
    return text


def _(msg, **params):
    return translate(msg, None, **params)


def pl(n, msg, **params):
    """Texte précédé d'un nombre affiché à part : {{ n }} {{ pl(n, "photo(s)") }}."""
    lang = current_lang()
    text = translate(msg, lang, **params)
    try:
        return pluralize(text, float(n), lang)
    except (TypeError, ValueError):
        return text


class L:
    """Texte traduit au moment de l'affichage, dans la langue du lecteur."""
    __slots__ = ("msg", "params")

    def __init__(self, msg, **params):
        self.msg, self.params = msg, params

    def render(self, lang=None):
        return translate(self.msg, lang, **self.params)

    def __str__(self):
        return self.render()

    def __add__(self, other):
        return Concat(self, other)

    def __radd__(self, other):
        return Concat(other, self)

    def __mod__(self, other):
        raise TypeError("Utilisez L(msg, nom=valeur) plutôt que %")

    def replace(self, old, new):
        return Post(self, old, new)

    def lower(self):
        return Post(self, None, None, "lower")

    def to_json(self):
        return {"m": self.msg, "p": {k: _jsonable(v) for k, v in self.params.items()}}


class Concat(L):
    __slots__ = ("parts",)

    def __init__(self, *parts):
        self.parts = []
        for p in parts:
            self.parts.extend(p.parts if isinstance(p, Concat) else [p])
        self.msg, self.params = "", {}

    def render(self, lang=None):
        return "".join(render(p, lang) for p in self.parts)

    def to_json(self):
        return {"c": [_jsonable(p) for p in self.parts]}


class Post(L):
    """Texte paresseux transforme apres traduction (replace, lower)."""
    __slots__ = ("base", "old", "new", "op")

    def __init__(self, base, old, new, op="replace"):
        self.base, self.old, self.new, self.op = base, old, new, op
        self.msg, self.params = "", {}

    def render(self, lang=None):
        t = render(self.base, lang)
        return t.lower() if self.op == "lower" else t.replace(self.old, self.new)

    def to_json(self):
        return {"x": _jsonable(self.base), "o": self.old, "n": self.new, "op": self.op}


def join(sep, items):
    """Equivalent paresseux de sep.join(items)."""
    out = []
    for i, it in enumerate(items):
        if i:
            out.append(sep)
        out.append(it)
    return Concat(*out) if out else ""


def store_list(items):
    """Liste de textes (paresseux ou non) a enregistrer en base."""
    return _MARK + json.dumps({"l": [_jsonable(i) for i in items]}, ensure_ascii=False) if items else ""


def render_list(value, lang=None):
    """Liste enregistree par store_list, ou ancienne forme « a | b »."""
    if not value:
        return []
    if isinstance(value, str) and value.startswith(_MARK):
        try:
            d = json.loads(value[1:])
            if isinstance(d, dict) and "l" in d:
                return [render(_from_json(x), lang) for x in d["l"]]
        except ValueError:
            pass
    return [x for x in str(value).split(" | ") if x]


def _jsonable(v):
    if isinstance(v, L):
        return v.to_json()
    if isinstance(v, (int, float, str)) or v is None:
        return v
    return str(v)


def _from_json(d):
    if isinstance(d, dict) and "x" in d:
        return Post(_from_json(d["x"]), d.get("o"), d.get("n"), d.get("op", "replace"))
    if isinstance(d, dict) and "c" in d:
        return Concat(*[_from_json(x) for x in d["c"]])
    if isinstance(d, dict) and "m" in d:
        return L(d["m"], **{k: _from_json(v) for k, v in d.get("p", {}).items()})
    return d


def render(value, lang=None):
    """Rend un texte (simple, paresseux, ou enregistre en base) dans la langue demandee."""
    if isinstance(value, L):
        return value.render(lang)
    if isinstance(value, str) and value.startswith(_MARK):
        try:
            return render(_from_json(json.loads(value[1:])), lang)
        except ValueError:
            return value[1:]
    if isinstance(value, (list, tuple)):
        return type(value)(render(v, lang) for v in value)
    return value if isinstance(value, str) else ("" if value is None else str(value))


def store(value):
    """Valeur a enregistrer en base : les textes paresseux gardent leur forme traduisible."""
    if isinstance(value, L):
        return _MARK + json.dumps(value.to_json(), ensure_ascii=False)
    return value


def best_match(accept_language):
    """Langue preferee d'apres l'en-tete Accept-Language du navigateur."""
    best, best_q = DEFAULT, -1.0
    for part in (accept_language or "").split(","):
        bits = part.strip().split(";")
        code = bits[0].strip().lower()[:2]
        q = 1.0
        for b in bits[1:]:
            if b.strip().startswith("q="):
                try:
                    q = float(b.strip()[2:])
                except ValueError:
                    q = 0
        if code in LANGS and q > best_q:
            best, best_q = code, q
    return best
