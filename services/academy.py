"""Academie du BTP : cours, quiz et assistant de recherche dans les cours verifies.

L'assistant ne genere pas de texte : il retrouve les passages des cours qui repondent le mieux a la
question et renvoie vers le cours. Il ne donne donc jamais une information qui n'a pas ete relue.
"""
import re
import unicodedata

from .academy_content import COURSES

BY_SLUG = {c["slug"]: c for c in COURSES}
STOP = set("""le la les un une des de du d l a au aux et ou en pour par sur dans avec sans que qui quoi quel quelle quels
quelles comment combien est sont faut il elle on je j me mon ma mes ce cet cette ces se sa son ses ne pas plus moins tres
the a an of to in on for with how what which is are do does should can i my it be at by from that this""".split())
STRUCTURAL = ("dimension", "portee", "calcul de structure", "section du poteau", "section de poutre", "combien de fer",
              "quel diametre", "size the", "beam size", "column size", "how much steel", "span")


def plain(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def words(s):
    out = []
    for w in re.findall(r"[a-z0-9]+", plain(s)):
        if w in STOP or len(w) < 3:
            continue
        out.append(w[:-1] if len(w) > 4 and w.endswith("s") else w)
    return out


def t(field, lang):
    return field.get(lang) or field.get("fr")


def course(slug, lang):
    c = BY_SLUG.get(slug)
    if c is None:
        return None
    return {
        "slug": c["slug"], "minutes": c["minutes"], "calc": c["calc"], "diagram": c["diagram"],
        "title": t(c["title"], lang), "audience": t(c["audience"], lang),
        "sections": [(t(h, lang), t(p, lang)) for h, p in c["sections"]],
        "checklist": [t(x, lang) for x in c["checklist"]],
        "quiz": [{"q": t(q, lang), "options": [t(o, lang) for o in opts], "answer": ans, "why": t(why, lang)}
                 for q, opts, ans, why in c["quiz"]],
    }


def catalog(lang):
    return [course(c["slug"], lang) for c in COURSES]


def grade(slug, answers, lang):
    """answers : {index de question: index de reponse}. Retourne (score, total, details)."""
    c = course(slug, lang)
    details, score = [], 0
    for i, q in enumerate(c["quiz"]):
        a = answers.get(i)
        ok = a == q["answer"]
        score += ok
        details.append({"q": q["q"], "chosen": q["options"][a] if a is not None and 0 <= a < len(q["options"]) else None,
                        "right": q["options"][q["answer"]], "ok": ok, "why": q["why"]})
    return score, len(c["quiz"]), details


def ask(question, lang, limit=3):
    """Passages des cours les plus proches de la question : [(score, cours, titre de section, texte)]."""
    q = words(question)
    if not q:
        return [], False
    qs = set(q)
    hits = []
    for c in COURSES:
        title_w = set(words(t(c["title"], lang)))
        for h, p in c["sections"]:
            text_w = words(t(h, lang) + " " + t(p, lang))
            tw = set(text_w)
            common = qs & tw
            if not common:
                continue
            score = sum(1 + min(text_w.count(w), 3) * 0.3 for w in common) + 0.8 * len(qs & title_w)
            hits.append((round(score, 2), c["slug"], t(c["title"], lang), t(h, lang), t(p, lang)))
    hits.sort(key=lambda x: -x[0])
    structural = any(k in plain(question) for k in STRUCTURAL)
    return hits[:limit], structural
