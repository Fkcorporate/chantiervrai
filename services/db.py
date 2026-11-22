"""Acces a la base de donnees : SQLite (par defaut) ou PostgreSQL.

- Sans DATABASE_URL : SQLite, fichier instance/chantiervrai.db. Ideal pour demarrer.
- Avec DATABASE_URL=postgresql://utilisateur:motdepasse@hote:5432/chantiervrai :
  PostgreSQL via psycopg 3 (pip install "psycopg[binary]").

Le code de l'application ecrit du SQL commun aux deux (parametres « ? »). Ce module
traduit pour PostgreSQL : parametres %s, identifiant de la ligne inseree (RETURNING id),
types du schema, et lignes accessibles par nom ou par position comme sqlite3.Row.
"""
import decimal
import os
import re
import sqlite3

_driver = None          # module compatible psycopg (remplacable pour les tests)


def database_url():
    return os.environ.get("DATABASE_URL", "").strip()


def is_pg():
    return database_url().startswith(("postgres://", "postgresql://"))


def set_driver(module):
    global _driver
    _driver = module


def driver():
    global _driver
    if _driver is None:
        try:
            import psycopg
        except ImportError as e:   # pragma: no cover
            raise RuntimeError("PostgreSQL demande le module psycopg : pip install \"psycopg[binary]\"") from e
        _driver = psycopg
    return _driver


# Tables sans colonne id (cle primaire composee ou texte)
NO_ID = {"reset_tokens", "project_members", "capture_tokens", "attestation_nonces", "settings", "offsite_files", "chat_reads"}


class Row:
    """Ligne lisible par nom (row["nom"]) ou par position (row[0]), comme sqlite3.Row."""
    __slots__ = ("_names", "_values", "_index")

    def __init__(self, names, values):
        self._names = names
        self._values = tuple(_clean(v) for v in values)
        self._index = {n: i for i, n in enumerate(names)}

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._values[self._index[key]]

    def keys(self):
        return list(self._names)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return f"Row({dict(zip(self._names, self._values))})"


def _clean(v):
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


_QUOTED = re.compile(r"'(?:[^']|'')*'")


def translate(sql):
    """Parametres « ? » -> %s, et « % » litteral -> %% (hors chaines entre apostrophes)."""
    out, last = [], 0
    for m in _QUOTED.finditer(sql):
        out.append(sql[last:m.start()].replace("%", "%%").replace("?", "%s"))
        out.append(m.group(0).replace("%", "%%"))
        last = m.end()
    out.append(sql[last:].replace("%", "%%").replace("?", "%s"))
    return "".join(out)


_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.I)


class PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid
        self.rowcount = cur.rowcount

    def _names(self):
        return [d[0] for d in self._cur.description] if self._cur.description else []

    def fetchone(self):
        if self._cur.description is None:
            return None
        r = self._cur.fetchone()
        return None if r is None else Row(self._names(), r)

    def fetchall(self):
        if self._cur.description is None:
            return []
        names = self._names()
        return [Row(names, r) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class PgConnection:
    """Connexion PostgreSQL avec la meme interface que sqlite3 (execute, commit, rollback)."""

    def __init__(self, url):
        self._conn = driver().connect(url)

    def execute(self, sql, params=()):
        q = translate(sql)
        m = _INSERT.match(sql)
        returning = bool(m) and m.group(1).lower() not in NO_ID and "returning" not in sql.lower()
        if returning:
            q = q.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.cursor()
        try:
            cur.execute(q, tuple(params))
        except Exception:
            self._conn.rollback()            # PostgreSQL annule la transaction apres une erreur
            raise
        lastrowid = None
        if returning:
            r = cur.fetchone()
            lastrowid = r[0] if r else None
        return PgCursor(cur, lastrowid)

    def executescript(self, script):
        for stmt in [s.strip() for s in script.split(";")]:
            if stmt:
                self.execute(stmt)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def integrity_errors():
    errs = [sqlite3.IntegrityError]
    if is_pg():
        errs.append(driver().IntegrityError)
    return tuple(errs)


def connect(sqlite_path, timeout=15):
    if is_pg():
        return PgConnection(database_url())
    db = sqlite3.connect(sqlite_path, timeout=timeout)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def pg_schema(sqlite_schema):
    """Adapte le schema SQLite a PostgreSQL."""
    s = sqlite_schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
    return re.sub(r"\bREAL\b", "DOUBLE PRECISION", s)


def pg_column_type(decl):
    return re.sub(r"\bREAL\b", "DOUBLE PRECISION", decl)
