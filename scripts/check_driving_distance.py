#!/usr/bin/env python3
"""Compute driving distance between suburbs and check threshold.

This module reads `data/sydney_suburbs.csv` at import and exposes a single function:

    within_driving_threshold(my_suburb: str, work_suburb: str, distance_threshold: int = 15) -> bool

Behavior:
- Attempts to use OpenRouteService via `openrouteservice` client if `ORS_API_KEY` env var is present.
- If no ORS key or client not installed, falls back to OSRM public demo API.
- If remote routing fails, falls back to haversine (straight-line) distance.

CSV reading and coordinate lookup happen at import time (outside the function) as requested.
"""
from pathlib import Path
import csv
import math
import os
import re
import requests
from typing import Optional
import sqlite3
import time

CSV_PATH = Path(__file__).resolve().parents[1] / 'data' / 'sydney_suburbs.csv'


def _normalize(name: str) -> str:
    if not name:
        return ''
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\[.*?\]", "", name)
    name = re.sub(r",\s*(New\s+South\s+Wales|NSW|Australia)\.?$", "", name, flags=re.I)
    name = re.sub(r"\s*[\u2013\u2014-]+\s*$", "", name)
    name = re.sub(r"[,:;\.]\s*$", "", name)
    return name.strip().lower()


# Load suburb -> (lat, lon) at import
_suburb_coords = {}
try:
    if CSV_PATH.exists():
        with CSV_PATH.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get('suburb') or '').strip()
                lat = (row.get('lat') or '').strip()
                lon = (row.get('lon') or '').strip()
                if not name:
                    continue
                try:
                    lat_f = float(lat) if lat != '' else None
                    lon_f = float(lon) if lon != '' else None
                except Exception:
                    lat_f = None
                    lon_f = None
                _suburb_coords[_normalize(name)] = (lat_f, lon_f)
except Exception:
    _suburb_coords = {}


# Setup simple on-disk SQLite cache to avoid repeated API calls
DB_PATH = CSV_PATH.parent / 'driving_cache.sqlite3'
_db_conn = None
try:
    _db_conn = sqlite3.connect(str(DB_PATH), timeout=5)
    cur = _db_conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS distances (
            key TEXT PRIMARY KEY,
            lat1 REAL,
            lon1 REAL,
            lat2 REAL,
            lon2 REAL,
            dist_m REAL,
            method TEXT,
            ts INTEGER
        )
        """
    )
    _db_conn.commit()
except Exception:
    _db_conn = None


def _cache_key(lat1, lon1, lat2, lon2):
    # create symmetric key so A->B equals B->A
    a = f"{lat1:.6f},{lon1:.6f}"
    b = f"{lat2:.6f},{lon2:.6f}"
    if a <= b:
        return f"{a}|{b}"
    return f"{b}|{a}"


def _cache_get(lat1, lon1, lat2, lon2):
    if _db_conn is None:
        return None
    try:
        key = _cache_key(lat1, lon1, lat2, lon2)
        cur = _db_conn.cursor()
        cur.execute("SELECT dist_m, method FROM distances WHERE key=?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        dist_m, method = row
        return float(dist_m), method
    except Exception:
        return None


def _cache_set(lat1, lon1, lat2, lon2, dist_m, method):
    if _db_conn is None:
        return
    try:
        key = _cache_key(lat1, lon1, lat2, lon2)
        ts = int(time.time())
        cur = _db_conn.cursor()
        cur.execute(
            "REPLACE INTO distances (key, lat1, lon1, lat2, lon2, dist_m, method, ts) VALUES (?,?,?,?,?,?,?,?)",
            (key, lat1, lon1, lat2, lon2, float(dist_m), method, ts),
        )
        _db_conn.commit()
    except Exception:
        pass


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


def _ors_distance_meters(lat1, lon1, lat2, lon2) -> Optional[float]:
    """Attempt to use OpenRouteService via HTTP if ORS_API_KEY is set.
    Returns distance in meters or None on failure.
    """
    key = os.environ.get('ORS_API_KEY')
    if not key:
        print(f"Missing ORS_API_KEY: {key=}")
        return None
    url = 'https://api.openrouteservice.org/v2/directions/driving-car'
    headers = {'Authorization': key, 'Content-Type': 'application/json'}
    body = {
        'coordinates': [[lon1, lat1], [lon2, lat2]],
        'units': 'm',
        'preference': 'shortest'
    }
    try:
        r = requests.post(url, json=body, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        # data['routes'][0]['summary']['distance'] is meters
        dist = data.get('routes', [{}])[0].get('summary', {}).get('distance')
        if isinstance(dist, (int, float)):
            return float(dist)
    except Exception:
        return None
    return None


def _osrm_distance_meters(lat1, lon1, lat2, lon2) -> Optional[float]:
    """Query OSRM public demo server for driving distance in meters.
    Returns distance in meters or None on failure.
    """
    coords = f"{lon1},{lat1};{lon2},{lat2}"
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=false&alternatives=false"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        d = r.json()
        routes = d.get('routes')
        if not routes:
            return None
        dist = routes[0].get('distance')
        if isinstance(dist, (int, float)):
            return float(dist)
    except Exception:
        return None
    return None


def within_driving_threshold(my_suburb: str, work_suburb: str, distance_threshold: int = 15):
    """Return (within_threshold: bool, distance_km: float|None, method: str|None).

    - `distance_km` will be a float when coordinates are available (computed via ORS/OSRM/haversine),
      or `None` when suburbs/coordinates are missing or an error occurred.
    - `method` is one of `'ors'`, `'osrm'`, `'haversine'`, or `None` when unavailable.
    - `within_threshold` is True when `distance_km` <= `distance_threshold`.
    """
    if not my_suburb or not work_suburb:
        return False, None, None
    a = _suburb_coords.get(_normalize(my_suburb))
    b = _suburb_coords.get(_normalize(work_suburb))
    if not a or not b:
        return False, None, None
    lat1, lon1 = a
    lat2, lon2 = b
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return False, None, None

    method = None
    dist_km = None

    # Check cache first
    cached = _cache_get(lat1, lon1, lat2, lon2)
    if cached is not None:
        dist_m_cached, method_cached = cached
        method = method_cached
        dist_km = dist_m_cached / 1000.0
    else:
        # Try ORS first (requires ORS_API_KEY)
        dist_m = _ors_distance_meters(lat1, lon1, lat2, lon2)
        if dist_m is not None:
            method = 'ors'
            dist_km = dist_m / 1000.0
        else:
            # Try OSRM
            dist_m = _osrm_distance_meters(lat1, lon1, lat2, lon2)
            if dist_m is not None:
                method = 'osrm'
                dist_km = dist_m / 1000.0
            else:
                # fallback to haversine (approx)
                dist_km = _haversine_km(lat1, lon1, lat2, lon2)
                method = 'haversine'
        # store in cache (store meters)
        try:
            _cache_set(lat1, lon1, lat2, lon2, dist_km * 1000.0, method)
        except Exception:
            pass

    try:
        within = dist_km is not None and dist_km <= float(distance_threshold)
    except Exception:
        within = False
    return within, dist_km, method


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('Usage: check_driving_distance.py "My Suburb" "Work Suburb" [threshold_km]')
        raise SystemExit(2)
    m = sys.argv[1]
    w = sys.argv[2]
    t = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    ok, dist_km, method = within_driving_threshold(m, w, t)
    if dist_km is None:
        print(f"within_threshold={ok}, distance_km=None, method={method}")
    else:
        print(f"within_threshold={ok}, distance_km={dist_km:.3f}, method={method}")
