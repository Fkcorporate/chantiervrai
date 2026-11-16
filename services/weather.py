"""Meteo du chantier par Open-Meteo (gratuit, sans cle). Desactive par defaut : METEO_AUTO=1 pour l'activer.

Donne pour la veille : pluie (mm), vent maximal (km/h), temperature maximale (degres C).
"""
from datetime import date, timedelta

from . import env, http_json


def enabled():
    return env("METEO_AUTO") == "1"


def yesterday(lat, lng):
    day = (date.today() - timedelta(days=1)).isoformat()
    code, data = http_json("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&daily=precipitation_sum,"
                           "wind_speed_10m_max,temperature_2m_max&timezone=auto&start_date=%s&end_date=%s"
                           % (lat, lng, day, day))
    if code != 200 or not isinstance(data, dict) or "daily" not in data:
        raise RuntimeError(f"open-meteo {code}")
    d = data["daily"]
    return day, {"pluie": d["precipitation_sum"][0], "vent": d["wind_speed_10m_max"][0],
                 "temperature": d["temperature_2m_max"][0]}
