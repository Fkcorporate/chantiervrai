"""Pilote PostgreSQL minimal, en Python pur, POUR LES TESTS UNIQUEMENT.

Il imite la petite partie de l'interface de psycopg utilisee par services/db.py
(connect, cursor, execute, fetchone, fetchall, commit, rollback). Il parle le protocole
PostgreSQL « simple query » et n'accepte que l'authentification « trust » (serveur local).
En production, utilisez psycopg : pip install "psycopg[binary]".
"""
import datetime
import decimal
import socket
import struct
import urllib.parse


class Error(Exception):
    pass


class DatabaseError(Error):
    def __init__(self, msg, sqlstate=""):
        super().__init__(msg)
        self.sqlstate = sqlstate


class IntegrityError(DatabaseError):
    pass


def _literal(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v) if v == v else "'NaN'::float8"
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        return "'\\x" + bytes(v).hex() + "'::bytea"
    if isinstance(v, (datetime.date, datetime.datetime)):
        v = v.isoformat()
    return "'" + str(v).replace("'", "''") + "'"


def _interpolate(q, params):
    out, i, n = [], 0, 0
    while i < len(q):
        c = q[i]
        if c == "%" and i + 1 < len(q):
            nxt = q[i + 1]
            if nxt == "%":
                out.append("%"); i += 2; continue
            if nxt == "s":
                out.append(_literal(params[n])); n += 1; i += 2; continue
        out.append(c); i += 1
    if n != len(params):
        raise DatabaseError(f"{len(params)} paramètres pour {n} emplacements")
    return "".join(out)


def _convert(oid, raw):
    if raw is None:
        return None
    s = raw.decode()
    if oid == 16:
        return s == "t"
    if oid in (20, 21, 23, 26):
        return int(s)
    if oid in (700, 701):
        return float(s)
    if oid == 1700:
        return decimal.Decimal(s)
    return s


class Connection:
    def __init__(self, url):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname or "127.0.0.1", u.port or 5432))
        user = u.username or "postgres"
        dbname = (u.path or "/postgres").lstrip("/") or "postgres"
        body = struct.pack("!i", 196608)
        for k, v in (("user", user), ("database", dbname), ("client_encoding", "UTF8")):
            body += k.encode() + b"\0" + v.encode() + b"\0"
        body += b"\0"
        self.sock.sendall(struct.pack("!i", len(body) + 4) + body)
        self.in_tx = False
        while True:
            t, payload = self._read()
            if t == b"R" and struct.unpack("!i", payload[:4])[0] != 0:
                raise DatabaseError("Seule l'authentification « trust » est gérée par ce pilote de test")
            if t == b"E":
                raise DatabaseError(self._err(payload)[1])
            if t == b"Z":
                break

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise DatabaseError("Connexion fermée")
            buf += chunk
        return buf

    def _read(self):
        t = self._recv(1)
        ln = struct.unpack("!i", self._recv(4))[0]
        return t, self._recv(ln - 4)

    @staticmethod
    def _err(payload):
        fields, i = {}, 0
        while i < len(payload) and payload[i] != 0:
            code = chr(payload[i]); j = payload.index(b"\0", i + 1)
            fields[code] = payload[i + 1:j].decode(errors="replace"); i = j + 1
        return fields.get("C", ""), fields.get("M", "erreur")

    def _query(self, sql):
        data = sql.encode() + b"\0"
        self.sock.sendall(b"Q" + struct.pack("!i", len(data) + 4) + data)
        cols, rows, tag, error = None, [], "", None
        while True:
            t, p = self._read()
            if t == b"T":
                n = struct.unpack("!h", p[:2])[0]; i = 2; cols = []
                for _ in range(n):
                    j = p.index(b"\0", i); name = p[i:j].decode(); i = j + 1
                    _tbl, _att, oid, _len, _mod, _fmt = struct.unpack("!ihihih", p[i:i + 18]); i += 18
                    cols.append((name, oid))
            elif t == b"D":
                n = struct.unpack("!h", p[:2])[0]; i = 2; vals = []
                for k in range(n):
                    ln = struct.unpack("!i", p[i:i + 4])[0]; i += 4
                    raw = None if ln < 0 else p[i:i + ln]; i += max(ln, 0)
                    vals.append(_convert(cols[k][1], raw))
                rows.append(tuple(vals))
            elif t == b"C":
                tag = p.rstrip(b"\0").decode()
            elif t == b"E":
                error = self._err(p)
            elif t == b"Z":
                break
        if error:
            cls = IntegrityError if error[0].startswith("23") else DatabaseError
            raise cls(error[1], error[0])
        return cols, rows, tag

    def cursor(self):
        return Cursor(self)

    def commit(self):
        if self.in_tx:
            self._query("COMMIT"); self.in_tx = False

    def rollback(self):
        if self.in_tx:
            self._query("ROLLBACK"); self.in_tx = False

    def close(self):
        try:
            self.rollback()
            self.sock.sendall(b"X" + struct.pack("!i", 4))
        finally:
            self.sock.close()


class Cursor:
    def __init__(self, conn):
        self.conn, self.description, self.rowcount, self._rows = conn, None, -1, []

    def execute(self, q, params=()):
        sql = _interpolate(q, tuple(params))
        if not self.conn.in_tx:
            self.conn._query("BEGIN"); self.conn.in_tx = True
        cols, rows, tag = self.conn._query(sql)
        self.description = [(c[0], c[1]) for c in cols] if cols is not None else None
        self._rows = rows
        last = tag.split()[-1] if tag else ""
        self.rowcount = int(last) if last.isdigit() else -1

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        r, self._rows = self._rows, []
        return r


def connect(url):
    return Connection(url)
