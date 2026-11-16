# RuralDrone

A Flask app that finds the nearest pharmacy stocking what you need and
simulates the drone delivery to your door - 3D flight paths and live
tracking included.

Rural America has pharmacy deserts: the nearest stocked pharmacy can be an
hour's drive away. This is a navigation platform for the version of that
problem where the last mile is flown.

## simulation only

This is an educational software demo, not a drone control or medical delivery
system. The 12 pharmacies, their stock, battery model, and delivery status are
fictional. No real aircraft, pharmacy inventory, terrain, weather, or airspace
service is connected. The simple no-fly sidestep heuristic is not a collision
or regulatory safety guarantee. Do not use its routes for real flights or
medical decisions. No physical delivery or flight testing is claimed.

## how it works

```
click a drop point on the map
      |
/api/nearest  -> geo.py: haversine search over the pharmacy dataset,
                 filtered by what you need in stock
      |
/api/dispatch -> geo.py: plan a 3D route - climb to cruise altitude,
                 detour around no-fly zones, descend to the doorstep
      |
/api/status   -> sim.py: a drone simulator flies the route in a
                 background thread - position, altitude, battery, ETA
      |
the frontend polls status and draws the flight twice: a dashed path on a
Leaflet map, and a three.js 3D view with the drone riding its path.
```

## quick start

```bash
pip3 install -r requirements.txt
python3 -m dronenav.app
# open http://localhost:5000
```

Click anywhere on the map to set the drop point. Pick a medication in the
dropdown to restrict the search to pharmacies that stock it. Watch the
panel for altitude, battery, distance and ETA while the drone flies.

## the pieces

- **dronenav/geo.py** - pure-stdlib geography: great-circle distances,
  nearest-pharmacy search with stock filtering, and 3D route planning.
  Routes climb to a 120 m cruise altitude, detour around no-fly zones
  with a perpendicular sidestep, and land at the doorstep.
- **dronenav/sim.py** - the flight simulator: advances the drone along
  its route in real time, with a battery model (long flights can fail),
  monotonic progress, and thread-safe state for the web layer.
- **dronenav/app.py** - the Flask API: `/api/pharmacies`, `/api/nearest`,
  `/api/dispatch`, `/api/status`.
- **static/** - Leaflet 2D map + three.js 3D flight view, no build step.
- **data/pharmacies.csv** - a sample rural pharmacy dataset (12 fictional
  pharmacies in one region) so the demo works out of the box. A replacement CSV can support further simulation; it does not make the app flight-ready.

## tests

```bash
python3 -m unittest discover -s tests -v
```

18 tests: distance math against a known city pair, nearest-pharmacy search
and stock filtering, route shape (ground start/finish, cruise altitude,
no-fly detours), the simulator (completion, altitude profile, monotonic
progress, battery failure on impossible flights), and the API endpoints
through Flask's test client.

## project structure

```
dronenav/
  __init__.py
  geo.py     # distances, nearest search, 3D route planning
  sim.py     # real-time flight simulator
  app.py     # Flask API + static serving
data/
  pharmacies.csv
static/
  index.html, app.js, style.css
tests/
  test_dronenav.py
```
