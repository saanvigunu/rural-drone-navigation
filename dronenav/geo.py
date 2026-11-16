"""Geography: distances, nearest-pharmacy search, and 3D route planning.

Pure stdlib - no dependencies. Coordinates are (lat, lon) in degrees,
altitudes in meters.
"""

import csv
import math
import os

EARTH_RADIUS_KM = 6371.0

CRUISE_ALT_M = 120.0        # typical small-drone cruise ceiling (m)
CLIMB_STEP_KM = 0.4         # horizontal distance spent climbing/descending
NO_FLY_BUFFER_KM = 0.15     # extra clearance kept around no-fly zones


def haversine_km(a, b):
    """Great-circle distance in km between (lat, lon) points a and b."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


class Pharmacy:
    def __init__(self, pid, name, town, lat, lon, stock):
        self.id = pid
        self.name = name
        self.town = town
        self.lat = float(lat)
        self.lon = float(lon)
        self.stock = stock

    @property
    def point(self):
        return (self.lat, self.lon)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "town": self.town,
                "lat": self.lat, "lon": self.lon, "stock": self.stock}


def load_pharmacies(path=None):
    """Load the bundled pharmacy dataset (or a CSV you pass in)."""
    path = path or os.path.join(os.path.dirname(__file__), "..", "data", "pharmacies.csv")
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(Pharmacy(row["id"], row["name"], row["town"],
                                row["lat"], row["lon"], row["stock"]))
    if not out:
        raise ValueError(f"no pharmacies loaded from {path}")
    return out


def nearest_pharmacy(pharmacies, point, need=None):
    """Closest pharmacy to (lat, lon); if `need` is given, only pharmacies
    listing that item in stock are considered. Returns (pharmacy, km)."""
    best, best_km = None, None
    for p in pharmacies:
        if need and need.lower() not in p.stock.lower():
            continue
        d = haversine_km(p.point, point)
        if best_km is None or d < best_km:
            best, best_km = p, d
    if best is None:
        raise LookupError(f"no pharmacy stocks {need!r}" if need else "no pharmacies")
    return best, best_km


def _crosses_no_fly(a, b, zone):
    """Rough check: does segment a->b pass within the zone's radius?"""
    zx, zy = zone["lat"], zone["lon"]
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return haversine_km(a, (zx, zy)) < zone["radius_km"]
    t = max(0.0, min(1.0, ((zx - ax) * dx + (zy - ay) * dy) / (dx * dx + dy * dy)))
    closest = (ax + t * dx, ay + t * dy)
    return haversine_km(closest, (zx, zy)) < zone["radius_km"] + NO_FLY_BUFFER_KM


def plan_route(origin, dest, no_fly_zones=(), cruise_alt_m=CRUISE_ALT_M):
    """3D flight path from origin to dest as a list of waypoints.

    Each waypoint: {"lat", "lon", "alt_m", "leg"} where leg is one of
    takeoff / climb / cruise / detour / descent / landing. The drone
    climbs to cruise altitude, detours around no-fly zones if the
    straight line crosses one, then descends to the doorstep.
    """
    wps = [{"lat": origin[0], "lon": origin[1], "alt_m": 0.0, "leg": "takeoff"}]

    mids = []
    for zone in no_fly_zones:
        if _crosses_no_fly(origin, dest, zone):
            # sidestep perpendicular to the flight line at the zone center
            dx, dy = dest[0] - origin[0], dest[1] - origin[1]
            px, py = -dy, dx  # perpendicular
            norm = math.hypot(px, py) or 1.0
            # ~1 degree lat ~ 111 km; push out by radius + buffer
            off = (zone["radius_km"] + 2 * NO_FLY_BUFFER_KM) / 111.0
            mids.append((zone["lat"] + px / norm * off * 111.0 / 111.0 * 1.0,
                         zone["lon"] + py / norm * off))
    path = [origin] + mids + [dest]

    # climb
    wps.append({"lat": origin[0], "lon": origin[1], "alt_m": cruise_alt_m, "leg": "climb"})
    # cruise / detour waypoints at altitude
    for m in mids:
        wps.append({"lat": m[0], "lon": m[1], "alt_m": cruise_alt_m,
                    "leg": "detour"})
    wps.append({"lat": dest[0], "lon": dest[1], "alt_m": cruise_alt_m,
                "leg": "cruise" if not mids else "cruise"})
    # descend + land
    wps.append({"lat": dest[0], "lon": dest[1], "alt_m": 0.0, "leg": "landing"})
    return wps


def route_distance_km(waypoints):
    """3D distance along the whole path, accounting for altitude."""
    total = 0.0
    for w1, w2 in zip(waypoints, waypoints[1:]):
        ground = haversine_km((w1["lat"], w1["lon"]), (w2["lat"], w2["lon"]))
        vert = abs(w2["alt_m"] - w1["alt_m"]) / 1000.0
        total += math.hypot(ground, vert)
    return total
