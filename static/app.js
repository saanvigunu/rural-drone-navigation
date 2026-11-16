// ruraldrone frontend: leaflet map + three.js 3D flight view + live polling.

const CENTER = [44.55, -72.4];

// ---------- 2D map ----------
const map = L.map("map").setView(CENTER, 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

let destMarker = null;
let droneMarker = null;
let pathLine = null;

fetch("/api/pharmacies").then(r => r.json()).then(data => {
    for (const p of data.pharmacies) {
        L.circleMarker([p.lat, p.lon], {
            radius: 7, color: "#e8722a", fillColor: "#e8722a", fillOpacity: 0.85,
        }).addTo(map).bindPopup(`<b>${p.name}</b><br>${p.town}<br><small>${p.stock}</small>`);
    }
});

map.on("click", async (e) => {
    const need = document.getElementById("need").value;
    const q = `lat=${e.latlng.lat}&lon=${e.latlng.lng}` + (need ? `&need=${encodeURIComponent(need)}` : "");
    const near = await (await fetch(`/api/nearest?${q}`)).json();
    if (near.error) { alert(near.error); return; }

    if (destMarker) map.removeLayer(destMarker);
    destMarker = L.marker(e.latlng).addTo(map)
        .bindPopup("drop point").openPopup();

    const res = await (await fetch("/api/dispatch", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            pharmacy_id: near.pharmacy.id,
            dest_lat: e.latlng.lat,
            dest_lon: e.latlng.lng,
        }),
    })).json();

    if (pathLine) map.removeLayer(pathLine);
    pathLine = L.polyline(res.route.map(w => [w.lat, w.lon]),
        {color: "#e8722a", weight: 3, dashArray: "6 6"}).addTo(map);
    build3d(res.route);
});

// ---------- 3D flight view ----------
let scene, camera, renderer, drone3d, routePts;

function build3d(route) {
    const el = document.getElementById("view3d");
    el.innerHTML = "";
    const W = el.clientWidth, H = el.clientHeight;
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x15151f);
    camera = new THREE.PerspectiveCamera(55, W / H, 0.1, 5000);
    renderer = new THREE.WebGLRenderer({antialias: true});
    renderer.setSize(W, H);
    el.appendChild(renderer.domElement);

    // ground grid
    const grid = new THREE.GridHelper(40, 40, 0x2c2c3a, 0x22222e);
    scene.add(grid);

    // scale: ~111km per degree lat -> spread the route across the grid
    const lats = route.map(w => w.lat), lons = route.map(w => w.lon);
    const clat = (Math.min(...lats) + Math.max(...lats)) / 2;
    const clon = (Math.min(...lons) + Math.max(...lons)) / 2;
    const scale = 14 / Math.max(0.01,
        Math.max(Math.max(...lats) - Math.min(...lats),
                 Math.max(...lons) - Math.min(...lons)));
    window._proj = (lat, lon, alt) => new THREE.Vector3(
        (lon - clon) * scale, alt / 30, (clat - lat) * scale);

    routePts = route.map(w => window._proj(w.lat, w.lon, w.alt_m));
    const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(routePts),
        new THREE.LineBasicMaterial({color: 0xe8722a}));
    scene.add(line);

    // drone marker
    drone3d = new THREE.Mesh(
        new THREE.SphereGeometry(0.35, 16, 16),
        new THREE.MeshBasicMaterial({color: 0xffffff}));
    drone3d.position.copy(routePts[0]);
    scene.add(drone3d);

    camera.position.set(10, 9, 14);
    camera.lookAt(0, 2, 0);
    renderer.render(scene, camera);
}

function update3d(lat, lon, alt) {
    if (!renderer || !window._proj) return;
    drone3d.position.copy(window._proj(lat, lon, alt));
    renderer.render(scene, camera);
}

// ---------- live tracking ----------
const $ = id => document.getElementById(id);

setInterval(async () => {
    const s = await (await fetch("/api/status")).json();
    if (s.status === "idle") return;
    $("st-status").textContent = s.status;
    $("st-leg").textContent = s.leg || "-";
    $("st-alt").textContent = `${s.alt_m} m`;
    $("st-batt").textContent = `${s.battery_pct}%`;
    $("st-dist").textContent = `${s.flown_km} / ${s.total_km} km`;
    $("st-eta").textContent = s.status === "flying" ? `${Math.round(s.eta_s)}s` : "-";
    $("st-bar").style.width = `${(s.progress || 0) * 100}%`;

    if (s.status === "flying" || s.status === "delivered") {
        if (!droneMarker) {
            droneMarker = L.circleMarker([s.lat, s.lon], {
                radius: 6, color: "#fff", fillColor: "#fff", fillOpacity: 1,
            }).addTo(map);
        } else {
            droneMarker.setLatLng([s.lat, s.lon]);
        }
        update3d(s.lat, s.lon, s.alt_m);
    }
}, 600);
