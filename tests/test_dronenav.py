import math
import unittest

from dronenav.geo import (CRUISE_ALT_M, haversine_km, load_pharmacies,
                          nearest_pharmacy, plan_route, route_distance_km)
from dronenav.sim import DroneSim


class GeoTests(unittest.TestCase):
    def test_haversine_known_pair(self):
        # san francisco to los angeles is ~559 km
        d = haversine_km((37.7749, -122.4194), (34.0522, -118.2437))
        self.assertAlmostEqual(d, 559, delta=8)

    def test_haversine_zero(self):
        self.assertEqual(haversine_km((44.5, -72.3), (44.5, -72.3)), 0.0)

    def test_nearest_pharmacy(self):
        pharmacies = load_pharmacies()
        p, d = nearest_pharmacy(pharmacies, (44.512, -72.381))
        self.assertEqual(p.id, "rx01")
        self.assertAlmostEqual(d, 0.0, places=3)

    def test_nearest_respects_stock_filter(self):
        pharmacies = load_pharmacies()
        p, _ = nearest_pharmacy(pharmacies, (44.445, -72.588), need="epi pen")
        self.assertIn("epi pen", p.stock)
        self.assertNotEqual(p.id, "rx06")  # bear creek is closer but no epi

    def test_nearest_no_stock_raises(self):
        pharmacies = load_pharmacies()
        with self.assertRaises(LookupError):
            nearest_pharmacy(pharmacies, (44.5, -72.3), need="unicorn tears")


class RouteTests(unittest.TestCase):
    def test_route_starts_and_lands_on_the_ground(self):
        wps = plan_route((44.5, -72.3), (44.6, -72.4))
        self.assertEqual(wps[0]["alt_m"], 0.0)
        self.assertEqual(wps[-1]["alt_m"], 0.0)
        self.assertEqual(wps[0]["leg"], "takeoff")
        self.assertEqual(wps[-1]["leg"], "landing")

    def test_route_reaches_cruise_altitude(self):
        wps = plan_route((44.5, -72.3), (44.6, -72.4))
        self.assertTrue(any(w["alt_m"] == CRUISE_ALT_M for w in wps))

    def test_route_detours_around_no_fly(self):
        zone = {"lat": 44.55, "lon": -72.35, "radius_km": 1.0}
        straight = plan_route((44.5, -72.3), (44.6, -72.4))
        detour = plan_route((44.5, -72.3), (44.6, -72.4), no_fly_zones=[zone])
        self.assertTrue(any(w["leg"] == "detour" for w in detour))
        self.assertGreater(route_distance_km(detour), route_distance_km(straight))
        for w in detour:
            if w["leg"] == "detour":
                self.assertGreaterEqual(
                    haversine_km((w["lat"], w["lon"]), (zone["lat"], zone["lon"])),
                    zone["radius_km"])

    def test_route_distance_accounts_for_altitude(self):
        wps = plan_route((44.5, -72.3), (44.6, -72.4))
        ground = haversine_km((44.5, -72.3), (44.6, -72.4))
        self.assertGreater(route_distance_km(wps), ground)  # climb + descent add up


class SimTests(unittest.TestCase):
    def _wps(self):
        return plan_route((44.5, -72.3), (44.51, -72.31))

    def test_requires_two_waypoints(self):
        with self.assertRaises(ValueError):
            DroneSim([{"lat": 1, "lon": 1, "alt_m": 0, "leg": "takeoff"}],
                     autopilot=False)

    def test_flight_completes(self):
        sim = DroneSim(self._wps(), speed_mps=200.0, autopilot=False)
        for _ in range(2000):
            s = sim.tick(0.5)
            if s["status"] == "delivered":
                break
        self.assertEqual(s["status"], "delivered")
        self.assertEqual(s["alt_m"], 0.0)
        self.assertAlmostEqual(s["lat"], 44.51, places=4)
        self.assertLess(s["battery_pct"], 100.0)

    def test_altitude_profile(self):
        sim = DroneSim(self._wps(), speed_mps=50.0, autopilot=False)
        peak = 0.0
        for _ in range(200):
            s = sim.tick(0.5)
            peak = max(peak, s["alt_m"])
            if s["status"] != "flying":
                break
        self.assertGreater(peak, 0.9 * CRUISE_ALT_M)

    def test_progress_monotonic(self):
        sim = DroneSim(self._wps(), speed_mps=100.0, autopilot=False)
        last = -1.0
        for _ in range(500):
            s = sim.tick(0.5)
            self.assertGreaterEqual(s["progress"], last)
            last = s["progress"]
            if s["status"] == "delivered":
                break
        self.assertEqual(sim.state()["progress"], 1.0)

    def test_battery_failure_on_long_flight(self):
        # a 200 km flight on a 100% / 1.6%-per-km battery cannot finish
        wps = [{"lat": 44.0, "lon": -72.0, "alt_m": 0.0, "leg": "takeoff"},
               {"lat": 45.5, "lon": -72.0, "alt_m": 100.0, "leg": "cruise"},
               {"lat": 45.9, "lon": -72.0, "alt_m": 0.0, "leg": "landing"}]
        sim = DroneSim(wps, speed_mps=500.0, autopilot=False)
        for _ in range(4000):
            s = sim.tick(0.5)
            if s["status"] != "flying":
                break
        self.assertEqual(s["status"], "failed")
        self.assertEqual(s["battery_pct"], 0.0)


class ApiTests(unittest.TestCase):
    def setUp(self):
        from dronenav.app import create_app
        self.app = create_app().test_client()

    def test_pharmacies_endpoint(self):
        r = self.app.get("/api/pharmacies")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.get_json()["pharmacies"]), 10)

    def test_nearest_endpoint(self):
        r = self.app.get("/api/nearest?lat=44.512&lon=-72.381")
        body = r.get_json()
        self.assertEqual(body["pharmacy"]["id"], "rx01")
        self.assertAlmostEqual(body["distance_km"], 0.0, places=3)

    def test_dispatch_and_status(self):
        r = self.app.post("/api/dispatch", json={
            "pharmacy_id": "rx01", "dest_lat": 44.52, "dest_lon": -72.39,
        })
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.get_json()["route"]), 2)
        s = self.app.get("/api/status").get_json()
        self.assertEqual(s["status"], "flying")
        self.assertGreater(s["total_km"], 0)

    def test_dispatch_unknown_pharmacy_404(self):
        r = self.app.post("/api/dispatch", json={
            "pharmacy_id": "nope", "dest_lat": 44.5, "dest_lon": -72.3,
        })
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
