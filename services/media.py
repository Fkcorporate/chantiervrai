"""Videos : lecture de la date et de la position dans le fichier, vignette.

Utilise ffprobe et ffmpeg s'ils sont installes (recommande : apt install ffmpeg).
Sinon, lit directement l'en-tete MP4/MOV (date de creation, duree, position).
"""
import json
import re
import shutil
import struct
import subprocess
from datetime import datetime, timedelta, timezone

VIDEO_EXT = {"mp4", "mov", "m4v", "webm", "3gp"}
MAX_SECONDS = 90
_EPOCH_1904 = datetime(1904, 1, 1, tzinfo=timezone.utc)
_ISO6709 = re.compile(rb"([+-]\d{1,2}\.\d{3,})([+-]\d{1,3}\.\d{3,})(?:[+-][\d.]+)?/")


def _boxes(data, start, end):
    i = start
    while i + 8 <= end:
        size, typ = struct.unpack(">I4s", data[i:i + 8])
        hdr = 8
        if size == 1 and i + 16 <= end:
            size = struct.unpack(">Q", data[i + 8:i + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - i
        if size < hdr:
            return
        yield typ, i + hdr, min(i + size, end)
        i += size


def _parse_mp4(path):
    out = {}
    with open(path, "rb") as f:
        data = f.read()
    for typ, s, e in _boxes(data, 0, len(data)):
        if typ != b"moov":
            continue
        moov = data[s:e]
        for t2, s2, _e2 in _boxes(moov, 0, len(moov)):
            if t2 == b"mvhd":
                v = moov[s2]
                if v == 1:
                    created, _m, scale, dur = struct.unpack(">QQIQ", moov[s2 + 4:s2 + 32])
                else:
                    created, _m, scale, dur = struct.unpack(">IIII", moov[s2 + 4:s2 + 20])
                if created:
                    out["created"] = _EPOCH_1904 + timedelta(seconds=created)
                if scale:
                    out["duration"] = dur / scale
        m = _ISO6709.search(moov)              # Android (©xyz) et iPhone (ISO 6709)
        if m:
            out["lat"], out["lng"] = float(m.group(1)), float(m.group(2))
        else:
            loc = _loci(moov)                  # boite 3GPP « loci » (coordonnees binaires)
            if loc:
                out["lat"], out["lng"] = loc
    return out


def _loci(moov):
    i = moov.find(b"loci")
    if i < 0:
        return None
    j = i + 4 + 4 + 2                        # type, version/drapeaux, langue
    end = moov.find(b"\x00", j)
    if end < 0 or end + 13 > len(moov):
        return None
    j = end + 1 + 1                          # fin du nom, role
    lng, lat = struct.unpack(">ii", moov[j:j + 8])
    lat, lng = lat / 65536, lng / 65536
    if -90 <= lat <= 90 and -180 <= lng <= 180 and (lat or lng):
        return lat, lng
    return None


def _ffprobe(path):
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
                           capture_output=True, timeout=30, check=False)
        fmt = json.loads(r.stdout or b"{}").get("format", {})
    except (subprocess.SubprocessError, ValueError):
        return None
    out = {}
    if fmt.get("duration"):
        out["duration"] = float(fmt["duration"])
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    ct = tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate")
    if ct:
        try:
            d = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            out["created"] = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    loc = next((v for k, v in tags.items() if k.startswith("location") or k.endswith("location.iso6709")), None)
    if loc:
        m = _ISO6709.search((loc if loc.endswith("/") else loc + "/").encode())
        if m:
            out["lat"], out["lng"] = float(m.group(1)), float(m.group(2))
    return out


def probe(path):
    """Retourne dict(created=datetime UTC|None, duration=float|None, lat, lng)."""
    info = _ffprobe(path) or {}
    if not info.get("created") or info.get("lat") is None:
        try:
            raw = _parse_mp4(path)
        except (OSError, struct.error, IndexError):
            raw = {}
        for k, v in raw.items():
            info.setdefault(k, v)
    if info.get("created") and info["created"].year < 2000:   # date absente (valeur 0)
        info.pop("created")
    return info


def thumbnail(path, out_path):
    """Extrait une image de la video. Retourne True si reussi."""
    if not shutil.which("ffmpeg"):
        return False
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-ss", "0.5", "-i", path, "-frames:v", "1",
                        "-vf", "scale='min(1280,iw)':-2", out_path], timeout=60, check=False)
    except subprocess.SubprocessError:
        return False
    import os
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0
