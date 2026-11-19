"""Beam headings and distances (great circle), and Maidenhead grid squares."""
from __future__ import annotations

import math

EARTH_KM = 6371.0


def grid_to_latlon(grid: str) -> tuple[float, float] | None:
    """Centre of a 4- or 6-character Maidenhead square ('FM29', 'FM29ki') -> (lat, lon)."""
    g = (grid or "").strip().upper()
    if len(g) not in (4, 6) or not (g[0:2].isalpha() and g[2:4].isdigit()) or \
            not ("A" <= g[0] <= "R" and "A" <= g[1] <= "R"):
        return None
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) == 6:
        if not (g[4:6].isalpha() and "A" <= g[4] <= "X" and "A" <= g[5] <= "X"):
            return None
        lon += (ord(g[4]) - 65) * (2 / 24) + 1 / 24
        lat += (ord(g[5]) - 65) * (1 / 24) + 1 / 48
    else:
        lon += 1
        lat += 0.5
    return lat, lon


def bearing(frm: tuple[float, float], to: tuple[float, float]) -> float:
    """Short-path beam heading in degrees (0 = north, 90 = east) from `frm` to `to`."""
    la1, lo1, la2, lo2 = map(math.radians, (*frm, *to))
    d = lo2 - lo1
    y = math.sin(d) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(d)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def distance_km(frm: tuple[float, float], to: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*frm, *to))
    a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def long_path(heading: float) -> float:
    return (heading + 180) % 360
