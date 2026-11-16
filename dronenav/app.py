"""Flask app: pharmacy lookup, dispatch, and live drone tracking."""

import threading

from flask import Flask, jsonify, request, send_from_directory

from .geo import load_pharmacies, nearest_pharmacy, plan_route
from .sim import DroneSim

# one active flight at a time - it's a demo fleet of one
_state = {"sim": None, "route": None, "pharmacy": None}
_state_lock = threading.Lock()


def create_app():
    app = Flask(__name__, static_folder="../static", static_url_path="")
    pharmacies = load_pharmacies()

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/pharmacies")
    def api_pharmacies():
        return jsonify({"pharmacies": [p.to_dict() for p in pharmacies]})

    @app.get("/api/nearest")
    def api_nearest():
        try:
            lat = float(request.args["lat"])
            lon = float(request.args["lon"])
        except (KeyError, ValueError):
            return jsonify({"error": "lat and lon query params required"}), 400
        need = request.args.get("need")
        try:
            p, km = nearest_pharmacy(pharmacies, (lat, lon), need=need)
        except LookupError as e:
            return jsonify({"error": str(e)}), 404
        return jsonify({"pharmacy": p.to_dict(), "distance_km": round(km, 3)})

    @app.post("/api/dispatch")
    def api_dispatch():
        body = request.get_json(force=True, silent=True) or {}
        pid = body.get("pharmacy_id")
        pharmacy = next((p for p in pharmacies if p.id == pid), None)
        if pharmacy is None:
            return jsonify({"error": f"unknown pharmacy {pid!r}"}), 404
        try:
            dest = (float(body["dest_lat"]), float(body["dest_lon"]))
        except (KeyError, ValueError):
            return jsonify({"error": "dest_lat and dest_lon required"}), 400

        zones = body.get("no_fly_zones", [])
        route = plan_route(pharmacy.point, dest, no_fly_zones=zones)
        sim = DroneSim(route)
        with _state_lock:
            _state["sim"] = sim
            _state["route"] = route
            _state["pharmacy"] = pharmacy.to_dict()
        return jsonify({"route": route, "pharmacy": pharmacy.to_dict(),
                        "status": sim.state()})

    @app.get("/api/status")
    def api_status():
        with _state_lock:
            sim = _state["sim"]
            route = _state["route"]
        if sim is None:
            return jsonify({"status": "idle"})
        return jsonify({**sim.state(), "route": route})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
