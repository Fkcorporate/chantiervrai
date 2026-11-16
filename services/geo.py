"""Geometrie de la parcelle : point dans le polygone, distance au bord, surface.

Projection locale equirectangulaire autour de la parcelle : precise a quelques centimetres pour
un terrain de quelques hectares, ce qui suffit au controle GPS des photos.
"""
import json
import math

R = 6371000.0


def parse(raw):
    """Liste de [lat, lng] valide (3 points minimum) ou None."""
    try:
        pts = json.loads(raw) if isinstance(raw, str) else raw
        pts = [[float(a), float(b)] for a, b in pts]
    except (TypeError, ValueError):
        return None
    if len(pts) < 3 or len(pts) > 200:
        return None
    if any(not (-90 <= a <= 90 and -180 <= b <= 180) for a, b in pts):
        return None
    return pts


def _xy(pts, lat0, lng0):
    k = math.cos(math.radians(lat0))
    return [(math.radians(b - lng0) * R * k, math.radians(a - lat0) * R) for a, b in pts]


def centroid(pts):
    return sum(a for a, _b in pts) / len(pts), sum(b for _a, b in pts) / len(pts)


def area_m2(pts):
    lat0, lng0 = centroid(pts)
    xy = _xy(pts, lat0, lng0)
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]))) / 2


def contains(pts, lat, lng):
    lat0, lng0 = centroid(pts)
    xy = _xy(pts, lat0, lng0)
    (px, py), = _xy([[lat, lng]], lat0, lng0)
    inside = False
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def distance_m(pts, lat, lng):
    """0 a l'interieur, sinon distance au bord le plus proche, en metres."""
    if contains(pts, lat, lng):
        return 0.0
    lat0, lng0 = centroid(pts)
    xy = _xy(pts, lat0, lng0)
    (px, py), = _xy([[lat, lng]], lat0, lng0)
    best = float("inf")
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        dx, dy = x2 - x1, y2 - y1
        t = 0 if dx == dy == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)))
    return best
