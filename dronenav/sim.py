"""Drone flight simulator: advances a drone along its route over time."""

import math
import threading
import time

from .geo import haversine_km, route_distance_km

CRUISE_SPEED_MPS = 14.0        # ~50 km/h delivery drone
BATTERY_PER_KM = 1.6           # % of battery per 3D km flown
TICK_SECONDS = 0.5


def _segment_len_km(w1, w2):
    ground = haversine_km((w1["lat"], w1["lon"]), (w2["lat"], w2["lon"]))
    vert = abs(w2["alt_m"] - w1["alt_m"]) / 1000.0
    return math.hypot(ground, vert)


class DroneSim:
    """Simulates one delivery flight. Thread-safe: the web layer reads
    state() while a background thread flies the route."""

    def __init__(self, waypoints, speed_mps=CRUISE_SPEED_MPS, autopilot=True):
        if len(waypoints) < 2:
            raise ValueError("a flight needs at least two waypoints")
        self.waypoints = waypoints
        self.speed = speed_mps
        self.total_km = route_distance_km(waypoints)
        self.flown_km = 0.0
        self.segment = 0
        self._seg_progress_m = 0.0
        self.battery = 100.0
        self.status = "flying"   # flying | delivered | failed
        self._lock = threading.RLock()
        self._pos = {
            "lat": waypoints[0]["lat"],
            "lon": waypoints[0]["lon"],
            "alt_m": waypoints[0]["alt_m"],
        }
        self._thread = None
        if autopilot:
            self.start()

    # -- flight dynamics -------------------------------------------------

    def tick(self, dt=TICK_SECONDS):
        """Advance the flight by dt seconds. Returns current state."""
        with self._lock:
            budget_m = self.speed * dt if self.status == "flying" else 0.0
            while budget_m > 1e-9 and self.status == "flying":
                w1, w2 = self.waypoints[self.segment], self.waypoints[self.segment + 1]
                seg_m = _segment_len_km(w1, w2) * 1000.0
                if seg_m < 1e-9:
                    # degenerate waypoint pair: skip to the next segment
                    self.segment += 1
                    self._seg_progress_m = 0.0
                    if self.segment >= len(self.waypoints) - 1:
                        self.status = "delivered"
                    continue
                step_m = min(budget_m, seg_m - self._seg_progress_m)
                self._seg_progress_m += step_m
                budget_m -= step_m
                self.flown_km += step_m / 1000.0
                t = min(1.0, self._seg_progress_m / seg_m)
                self._pos = {
                    "lat": w1["lat"] + (w2["lat"] - w1["lat"]) * t,
                    "lon": w1["lon"] + (w2["lon"] - w1["lon"]) * t,
                    "alt_m": w1["alt_m"] + (w2["alt_m"] - w1["alt_m"]) * t,
                }
                if self._seg_progress_m >= seg_m - 1e-9:
                    self.segment += 1
                    self._seg_progress_m = 0.0
                    if self.segment >= len(self.waypoints) - 1:
                        self._pos = {"lat": w2["lat"], "lon": w2["lon"],
                                     "alt_m": w2["alt_m"]}
                        self.status = "delivered"
            self.battery = max(0.0, 100.0 - self.flown_km * BATTERY_PER_KM)
            if self.battery <= 0 and self.status == "flying":
                self.status = "failed"
            return self.state()

    # -- state ------------------------------------------------------------

    def state(self):
        with self._lock:
            remaining = max(0.0, self.total_km - self.flown_km)
            eta_s = remaining * 1000 / self.speed if self.status == "flying" else 0.0
            leg_idx = min(self.segment, len(self.waypoints) - 1)
            return {
                "status": self.status,
                "lat": round(self._pos["lat"], 6),
                "lon": round(self._pos["lon"], 6),
                "alt_m": round(self._pos["alt_m"], 1),
                "speed_mps": self.speed if self.status == "flying" else 0,
                "battery_pct": round(self.battery, 1),
                "flown_km": round(self.flown_km, 3),
                "total_km": round(self.total_km, 3),
                "progress": round(self.flown_km / self.total_km, 4) if self.total_km else 1.0,
                "eta_s": round(eta_s, 1),
                "leg": self.waypoints[leg_idx]["leg"],
            }

    # -- background flight -------------------------------------------------

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._fly, daemon=True)
            self._thread.start()

    def _fly(self):
        while True:
            s = self.tick(TICK_SECONDS)
            if s["status"] != "flying":
                return
            time.sleep(TICK_SECONDS)
