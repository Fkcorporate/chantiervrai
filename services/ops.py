"""Exploitation : vérification des sauvegardes, copie hors du serveur, restauration.

- La base est sauvegardée chaque nuit (copie SQLite cohérente, ou pg_dump compressé) puis vérifiée.
- Si un stockage distant est configuré (services/offsite.py), la sauvegarde de la base y est copiée,
  et les photos et documents y sont envoyés au fil de l'eau : seuls les fichiers nouveaux ou modifiés
  partent (inventaire dans la table offsite_files).
- La restauration reprend la dernière sauvegarde, locale ou distante, et redescend les fichiers manquants.
"""
import gzip
import os
import shutil
import sqlite3
import subprocess

from services import offsite as OFF

DUMP_END = b"PostgreSQL database dump complete"


# ---------------------------------------------------------------------------
# Vérification d'une sauvegarde
# ---------------------------------------------------------------------------
def verify_dump(path):
    """(ok, détail). SQLite : contrôle d'intégrité et tables présentes. PostgreSQL : archive lisible et complète."""
    try:
        if path.endswith(".db"):
            c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                res = c.execute("PRAGMA integrity_check").fetchone()[0]
                n = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
                users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            finally:
                c.close()
            if res != "ok":
                return False, f"intégrité : {res}"
            return True, f"{n} tables, {users} comptes"
        if path.endswith(".sql.gz"):
            with gzip.open(path, "rb") as fh:
                data = fh.read()
            if DUMP_END not in data[-4096:]:
                return False, "export PostgreSQL incomplet"
            return True, f"{data.count(b'CREATE TABLE')} tables, {len(data) // 1024} Ko"
        return False, "format inconnu"
    except Exception as e:  # fichier illisible
        return False, str(e)[:200]


# ---------------------------------------------------------------------------
# Copie distante
# ---------------------------------------------------------------------------
def push_dump(store, path, keep=30):
    """Envoie la sauvegarde de la base dans base/ et ne garde que les `keep` dernières à distance."""
    key = OFF.prefix() + "base/" + os.path.basename(path)
    store.put_file(key, path)
    remote = sorted(k for k, _s in store.list(OFF.prefix() + "base/"))
    for old in remote[:-keep]:
        store.delete(old)
    return key


def sync_files(store, db, upload_dir, limit=None, now=None):
    """Envoie les fichiers nouveaux ou modifiés de `upload_dir`. Renvoie (envoyés, déjà à jour, erreurs)."""
    known = {r["path"]: (r["size"], r["mtime"]) for r in db.execute("SELECT path, size, mtime FROM offsite_files")}
    sent = same = 0
    errors = []
    for root, _dirs, files in os.walk(upload_dir):
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, upload_dir).replace(os.sep, "/")
            if rel.startswith("wa_attente/") or name.startswith("."):
                continue                          # fichiers temporaires
            st = os.stat(full)
            sig = (st.st_size, int(st.st_mtime))
            if known.get(rel) == sig:
                same += 1
                continue
            try:
                store.put_file(OFF.prefix() + "fichiers/" + rel, full)
            except Exception as e:  # réseau, droits
                errors.append(f"{rel} : {str(e)[:120]}")
                if len(errors) >= 5:
                    return sent, same, errors
                continue
            if rel in known:
                db.execute("UPDATE offsite_files SET size = ?, mtime = ?, sent_at = ? WHERE path = ?", (*sig, now, rel))
            else:
                db.execute("INSERT INTO offsite_files (path, size, mtime, sent_at) VALUES (?,?,?,?)", (rel, *sig, now))
            db.commit()
            sent += 1
            if limit and sent >= limit:
                return sent, same, errors
    return sent, same, errors


# ---------------------------------------------------------------------------
# Restauration
# ---------------------------------------------------------------------------
def latest_remote_dump(store):
    keys = sorted(k for k, _s in store.list(OFF.prefix() + "base/"))
    return keys[-1] if keys else None


def fetch_remote_dump(store, folder, key=None):
    key = key or latest_remote_dump(store)
    if not key:
        raise IOError("aucune sauvegarde distante")
    data = store.get(key)
    if data is None:
        raise IOError(f"sauvegarde distante introuvable : {key}")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, os.path.basename(key))
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def restore_files(store, upload_dir):
    """Redescend les fichiers distants absents ou de taille différente. Renvoie le nombre de fichiers écrits."""
    base = OFF.prefix() + "fichiers/"
    n = 0
    for key, size in store.list(base):
        rel = key[len(base):]
        if not rel or ".." in rel.split("/"):
            continue
        dest = os.path.join(upload_dir, *rel.split("/"))
        if os.path.exists(dest) and os.path.getsize(dest) == size:
            continue
        data = store.get(key)
        if data is None:
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        n += 1
    return n


def restore_sqlite(dump, db_path):
    """Remplace la base SQLite ; l'ancienne est gardée à côté (.avant-restauration)."""
    ok, detail = verify_dump(dump)
    if not ok:
        raise IOError(f"sauvegarde invalide : {detail}")
    if os.path.exists(db_path):
        shutil.copy2(db_path, db_path + ".avant-restauration")
    for ext in ("-wal", "-shm"):
        if os.path.exists(db_path + ext):
            os.remove(db_path + ext)
    src, dst = sqlite3.connect(dump), sqlite3.connect(db_path)
    src.backup(dst)
    dst.close()
    src.close()
    return detail


def restore_pg(dump, url):
    """Recharge un export pg_dump dans la base PostgreSQL (schéma public vidé d'abord)."""
    ok, detail = verify_dump(dump)
    if not ok:
        raise IOError(f"sauvegarde invalide : {detail}")
    with gzip.open(dump, "rb") as fh:
        sql = fh.read()
    pre = b"DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;\n"
    r = subprocess.run(["psql", "--quiet", "--set", "ON_ERROR_STOP=1", "--dbname", url], input=pre + sql,
                       capture_output=True)
    if r.returncode != 0:
        raise IOError("psql : " + r.stderr.decode(errors="replace")[-400:])
    return detail
