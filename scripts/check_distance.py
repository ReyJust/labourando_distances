#!/usr/bin/env python3
"""Simple helper: read suburbs CSV at import and provide a single function

Function:
    within_threshold(my_suburb: str, work_suburb: str, distance_threshold: int = 15) -> bool

CSV reading is done at module import (outside the function) as requested.
"""
from pathlib import Path
import csv
import math
import re

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


# Read CSV at import time and build a lookup of normalized suburb -> (lat, lon)
_suburb_coords = {}
try:
    if CSV_PATH.exists():
        with CSV_PATH.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get('suburb') or '').strip()
                lat = row.get('lat', '').strip()
                lon = row.get('lon', '').strip()
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
    # keep empty map on failure
    _suburb_coords = {}


def _haversine_km(lat1, lon1, lat2, lon2):
    # returns distance in kilometers
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


def within_threshold(my_suburb: str, work_suburb: str, distance_threshold: int = 15) -> bool:
    """Return True if distance between `my_suburb` and `work_suburb` is <= `distance_threshold` km.

    Reading of the CSV happens outside this function (module import). If either suburb
    is not found or lacks coordinates, the function returns False.
    """
    if not my_suburb or not work_suburb:
        return False
    a = _suburb_coords.get(_normalize(my_suburb))
    b = _suburb_coords.get(_normalize(work_suburb))
    if not a or not b:
        return False
    lat1, lon1 = a
    lat2, lon2 = b
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return False
    try:
        dist = _haversine_km(lat1, lon1, lat2, lon2)
    except Exception:
        return False
    return dist <= float(distance_threshold)


if __name__ == '__main__':
    # quick manual test when run directly
    import sys
    if len(sys.argv) < 3:
        print('Usage: check_distance.py "My Suburb" "Work Suburb" [threshold_km]')
        raise SystemExit(2)
    m = sys.argv[1]
    w = sys.argv[2]
    t = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    ok = within_threshold(m, w, t)
    print(ok)
