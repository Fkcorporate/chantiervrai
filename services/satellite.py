"""Images satellite mensuelles du terrain (optique Sentinel-2 et radar Sentinel-1).

Par defaut : Copernicus Data Space Ecosystem (gratuit, compte a creer sur
dataspace.copernicus.eu, puis « OAuth client » dans le tableau de bord Sentinel Hub).
    SH_CLIENT_ID, SH_CLIENT_SECRET
Pour Sentinel Hub commercial (Planet) :
    SH_BASE=https://services.sentinel-hub.com
    SH_TOKEN_URL=https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token

Resolution : 10 m par pixel. On voit le terrain se transformer (decapage,
dalle, toiture), pas le detail des murs. Le radar voit a travers les nuages,
utile pendant la saison des pluies.
"""
import calendar
import math
import time

from . import env, http_json

_token = {"value": None, "exp": 0}

OPTICAL = """//VERSION=3
function setup(){return {input:["B04","B03","B02","dataMask"],output:{bands:4}};}
function evaluatePixel(s){return [2.5*s.B04,2.5*s.B03,2.5*s.B02,s.dataMask];}"""

RADAR = """//VERSION=3
function setup(){return {input:["VV","dataMask"],output:{bands:4}};}
function evaluatePixel(s){var v=Math.max(0,Math.log(s.VV)*0.21714724095+1);return [v,v,v,s.dataMask];}"""

LAYERS = {"optique": "Optique (Sentinel-2)", "radar": "Radar (Sentinel-1, voit à travers les nuages)",
          "thr": "Très haute résolution (Pléiades Neo, SkySat, Vantor)"}


def configured():
    return bool(env("SH_CLIENT_ID") and env("SH_CLIENT_SECRET"))


def _base():
    return env("SH_BASE", "https://sh.dataspace.copernicus.eu")


def _get_token():
    if _token["value"] and _token["exp"] > time.time() + 30:
        return _token["value"]
    url = env("SH_TOKEN_URL", "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token")
    code, body = http_json(url, {"grant_type": "client_credentials", "client_id": env("SH_CLIENT_ID"),
                                 "client_secret": env("SH_CLIENT_SECRET")}, form=True)
    if code != 200 or not isinstance(body, dict):
        raise RuntimeError(f"Connexion satellite refusée ({code})")
    _token["value"], _token["exp"] = body["access_token"], time.time() + int(body.get("expires_in", 300))
    return _token["value"]


def bbox(lat, lng, half_m):
    dlat = half_m / 111320
    dlng = half_m / (111320 * max(math.cos(math.radians(lat)), 0.01))
    return [lng - dlng, lat - dlat, lng + dlng, lat + dlat]


def fetch(lat, lng, month, layer="optique", half_m=400, size=512):
    """Telecharge la meilleure image du mois (moins nuageuse) en PNG. month = 'AAAA-MM'."""
    y, m = map(int, month.split("-"))
    last = calendar.monthrange(y, m)[1]
    tr = {"from": f"{month}-01T00:00:00Z", "to": f"{month}-{last:02d}T23:59:59Z"}
    if layer == "radar":
        data = [{"type": "sentinel-1-grd", "dataFilter": {"timeRange": tr, "mosaickingOrder": "mostRecent"}}]
        script = RADAR
    else:
        data = [{"type": "sentinel-2-l2a", "dataFilter": {"timeRange": tr, "maxCloudCoverage": 40,
                                                          "mosaickingOrder": "leastCC"}}]
        script = OPTICAL
    body = {
        "input": {"bounds": {"bbox": bbox(lat, lng, half_m),
                             "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                  "data": data},
        "output": {"width": size, "height": size,
                   "responses": [{"identifier": "default", "format": {"type": "image/png"}}]},
        "evalscript": script,
    }
    code, raw = http_json(f"{_base()}/api/v1/process", body,
                          headers={"Authorization": f"Bearer {_get_token()}", "Accept": "image/png"}, timeout=90)
    if code != 200 or not isinstance(raw, (bytes, bytearray)):
        raise RuntimeError(f"Image satellite indisponible ({code}) : {str(raw)[:150]}")
    return bytes(raw)
