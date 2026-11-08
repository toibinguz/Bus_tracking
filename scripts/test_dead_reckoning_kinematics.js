/**
 * Unit & Integration Test Suite: Dead Reckoning Kinematics & Continuous Error Reconciliation.
 * Strictly verifies client-side prediction along 1D Frenet centerline and continuous reconciliation.
 *
 * Ground Truth Invariants:
 * 1. CorridorTrajectory: Monotonic s accumulation and exact O(log N) point/bearing lookup.
 * 2. Dead Reckoning: In-transit vehicle advances into the near future at v_eff * dt without waiting for packets.
 * 3. Anti Back-Jump on Stale/Duplicate Packet: When packet has s_meas <= lastMeasS, NEVER jump backwards.
 *    Continue forward from virtual currentS with damped deceleration.
 * 4. Forward Interception on Discrepancy: When packet has discrepancy (s_meas != currentS), NEVER teleport.
 *    Intersects future lead position (s_meas + v_meas * tau) from current virtual position.
 * 5. Standstill Lock: Stationary bus (speed=0) locks smoothly at stop, drift = 0.
 * 6. Shortest Arc Bearing (map/f.i): Rotation across North meridian (355 -> 5 deg) rotates +10 deg, never -350 deg.
 */

const fs = require('fs');
const path = require('path');

console.log("\n" + "=".repeat(80));
console.log("KIỂM ĐỊNH TOÁN HỌC: DEAD RECKONING 1D FRENET & HÒA GIẢI SAI SỐ LIÊN TỤC 60 FPS");
console.log("=".repeat(80));

// 1. Mock minimal Leaflet & Browser environment
let virtualNow = 0;
const pendingRafCallbacks = new Map();
let rafIdCounter = 0;

class MockMarker {
    constructor(latLng, options) {
        this._latLng = Array.isArray(latLng) ? { lat: latLng[0], lng: latLng[1] } : { lat: latLng.lat, lng: latLng.lng };
        this._icon = options && options.icon;
        this._events = {};
        this._domElement = {
            querySelector: (sel) => ({
                style: {},
                textContent: '',
                className: ''
            })
        };
    }
    getLatLng() { return this._latLng; }
    setLatLng(latLng) {
        if (Array.isArray(latLng)) {
            this._latLng = { lat: latLng[0], lng: latLng[1] };
        } else {
            this._latLng = { lat: latLng.lat, lng: latLng.lng };
        }
        return this;
    }
    getElement() { return this._domElement; }
    on(event, fn) { this._events[event] = fn; return this; }
    addTo(map) { return this; }
}

class MockMap {
    constructor() { this._layers = new Set(); }
    addLayer(l) { this._layers.add(l); }
    removeLayer(l) { this._layers.delete(l); }
    fitBounds() {}
    getBounds() { return { pad: () => {} }; }
}

const L = {
    marker: (pos, opts) => new MockMarker(pos, opts),
    circleMarker: () => ({ addTo: () => ({}), bindTooltip: () => ({}), on: () => ({}) }),
    polyline: () => {
        const p = {
            addTo: () => p,
            getBounds: () => ({ pad: () => ({}) })
        };
        return p;
    },
    layerGroup: () => ({ addTo: () => ({}), clearLayers: () => ({}), addLayer: () => ({}) }),
    map: () => new MockMap(),
    divIcon: (opts) => opts,
    tileLayer: () => ({ addTo: () => ({}), on: () => ({}) }),
    control: { layers: () => ({ addTo: () => ({}) }), zoom: () => ({ addTo: () => ({}) }) }
};

global.L = L;
global.window = {
    performance: { now: () => virtualNow },
    requestAnimationFrame: (cb) => {
        const id = ++rafIdCounter;
        pendingRafCallbacks.set(id, cb);
        return id;
    },
    cancelAnimationFrame: (id) => {
        pendingRafCallbacks.delete(id);
    }
};
global.document = {
    addEventListener: () => {},
    getElementById: () => null
};

function advanceVirtualTime(ms) {
    const stepMs = 16.666; // 60 FPS tick
    let elapsed = 0;
    while (elapsed < ms) {
        const delta = Math.min(stepMs, ms - elapsed);
        virtualNow += delta;
        elapsed += delta;
        const cbs = Array.from(pendingRafCallbacks.values());
        pendingRafCallbacks.clear();
        for (const cb of cbs) {
            cb(virtualNow);
        }
    }
}

// 2. Load map_manager.js
const mapManagerPath = path.join(__dirname, '..', 'module_3_bus_eta_prediction', 'step_3_5_web_demo', 'static', 'js', 'map_manager.js');
const mapManagerCode = fs.readFileSync(mapManagerPath, 'utf8');
new Function(mapManagerCode + "\nglobal.MapManager = MapManager;\nglobal.CorridorTrajectory = typeof CorridorTrajectory !== 'undefined' ? CorridorTrajectory : null;\nglobal.BusKinematics = typeof BusKinematics !== 'undefined' ? BusKinematics : null;\nglobal.computeSphericalHeading = computeSphericalHeading;\nglobal.shortestArcDelta = shortestArcDelta;")();

// Test Execution
let passedCount = 0;
let totalTests = 0;

function assert(condition, message) {
    totalTests++;
    if (!condition) {
        console.error(`❌ [FAIL] ${message}`);
        process.exit(1);
    }
    console.log(`  ✓ [PASS] ${message}`);
    passedCount++;
}

console.log("\n--- TEST GROUP 1: Spherical Heading & Shortest Arc Rotation (TimBus map/f.i & map/f.K) ---");
const hNorth = global.computeSphericalHeading(21.0000, 105.8000, 21.0100, 105.8000);
assert(Math.abs(hNorth - 0.0) < 1.0, `Heading North must be ~0 deg (got ${hNorth.toFixed(1)})`);

const hEast = global.computeSphericalHeading(21.0000, 105.8000, 21.0000, 105.8100);
assert(Math.abs(hEast - 90.0) < 1.0, `Heading East must be ~90 deg (got ${hEast.toFixed(1)})`);

const arc1 = global.shortestArcDelta(355.0, 5.0);
assert(Math.abs(arc1 - 10.0) < 1e-4, `Crossing North meridian 355 -> 5 deg must be +10 deg (got ${arc1})`);

const arc2 = global.shortestArcDelta(10.0, 350.0);
assert(Math.abs(arc2 - (-20.0)) < 1e-4, `Crossing North meridian 10 -> 350 deg must be -20 deg (got ${arc2})`);

console.log("\n--- TEST GROUP 2: Corridor Trajectory & 1D Frenet Projection ---");
const sampleCoords = [
    [105.8500, 21.0100], // S = 0m
    [105.8500, 21.0150], // ~552m North
    [105.8500, 21.0200], // ~1105m North
    [105.8550, 21.0200], // ~520m East
];

const mockGeometry = {
    shape_geojson: { coordinates: sampleCoords },
    stations: [
        { station_order: 0, station_name: "Bến xuất phát", lat: 21.0100, lon: 105.8500, cum_distance_m: 0.0 },
        { station_order: 1, station_name: "Bến kết thúc", lat: 21.0200, lon: 105.8550, cum_distance_m: 1625.0 }
    ]
};

const mapManager = new global.MapManager('map');
mapManager.renderRoute(mockGeometry);

assert(mapManager.corridorTrajectory !== null, "corridorTrajectory must be successfully instantiated on renderRoute");
const totalLen = mapManager.corridorTrajectory.totalLength;
assert(totalLen > 1500 && totalLen < 1800, `Corridor total length must be ~1625m (got ${totalLen.toFixed(1)}m)`);

const ptStart = mapManager.corridorTrajectory.getPointAtS(0.0);
assert(Math.abs(ptStart.lat - 21.0100) < 1e-4 && Math.abs(ptStart.lng - 105.8500) < 1e-4, "Point at s=0 must match start coordinate");

const ptEnd = mapManager.corridorTrajectory.getPointAtS(totalLen);
assert(Math.abs(ptEnd.lat - 21.0200) < 1e-4 && Math.abs(ptEnd.lng - 105.8550) < 1e-4, "Point at s=L must match terminal coordinate");

console.log("\n--- TEST GROUP 3: Dead Reckoning (Client-side Continuous Forward Prediction) ---");
virtualNow = 1000;
mapManager.updateBuses([
    {
        vehicle_id: "BUS_TEST_01",
        plate: "29B-999.01",
        status: "ACTIVE_IN_TRANSIT",
        current_s_bus_m: 200.0,
        speed_kmh: 36.0, // 10 m/s
        lat: 21.0118,
        lon: 105.8500,
        telemetry_source: "timbus_5s"
    }
]);

const busKin = mapManager.busKinematicsMap ? mapManager.busKinematicsMap.get("BUS_TEST_01") : null;
assert(busKin !== null, "BusKinematics instance must exist for BUS_TEST_01");
assert(Math.abs(busKin.currentS - 200.0) < 1.0, `Initial S must be 200m (got ${busKin.currentS})`);
assert(Math.abs(busKin.effectiveSpeedMps - 10.0) < 0.1, `Initial effective speed must be 10 m/s (got ${busKin.effectiveSpeedMps})`);

// Advance virtual time by 5.0s without receiving any packets
advanceVirtualTime(5000);
// Vehicle MUST advance forward to s ≈ 200 + 10 * 5 = 250m!
assert(busKin.currentS >= 248.0 && busKin.currentS <= 252.0, `Vehicle must advance to ~250m at t=+5s (got ${busKin.currentS.toFixed(2)}m)`);

console.log("\n--- TEST GROUP 4: ZERO BACK-JUMP ON DUPLICATE/STALE PACKET (Bảo toàn Vị trí ảo, Giảm chậm tốc độ) ---");
// Vehicle is currently at s ≈ 250m.
// A duplicate packet arrives from server (stale GPS cache from 5s ago): s_meas = 200m!
const sBeforeDup = busKin.currentS;
mapManager.updateBuses([
    {
        vehicle_id: "BUS_TEST_01",
        plate: "29B-999.01",
        status: "ACTIVE_IN_TRANSIT",
        current_s_bus_m: 200.0, // Stale packet!
        speed_kmh: 36.0,
        lat: 21.0118,
        lon: 105.8500,
        telemetry_source: "timbus_5s"
    }
]);

// CRITICAL ANTI-BACKJUMP INVARIANT:
// Vehicle MUST NOT jump backwards to 200m! currentS must remain >= sBeforeDup (~250m)!
assert(busKin.currentS >= sBeforeDup - 0.01, `Zero Back-Jump Invariant: currentS (${busKin.currentS.toFixed(2)}m) must NEVER jump backwards to 200m!`);

// Speed must be damped for deceleration (momentum damping)
assert(busKin.targetSpeedMps < 10.0, `Momentum Damping: Target speed on duplicate packet must be decelerated (got ${busKin.targetSpeedMps.toFixed(2)} m/s)`);

// Advance time by 2.0s: vehicle continues forward with damped speed, NEVER reversing
advanceVirtualTime(2000);
assert(busKin.currentS > sBeforeDup, `Vehicle must continue progressing forward from virtual position (now ${busKin.currentS.toFixed(2)}m)`);

console.log("\n--- TEST GROUP 5: VECTOR INTERCEPTION (Đón đầu vị trí nội suy từ vị trí ảo hiện tại) ---");
// Current virtual position is now s ≈ 262m.
// A fresh packet arrives with s_meas = 280m, speed = 10 m/s (36 km/h).
// Future lead position in tau = 4.5s: s_lead = 280 + 10 * 4.5 = 325m.
// Distance needed from current virtual position (262m): deltaS = 325 - 262 = 63m.
// Required interception velocity: v_req = 63 / 4.5 = 14.0 m/s!
const sVirtualBeforeFresh = busKin.currentS;
mapManager.updateBuses([
    {
        vehicle_id: "BUS_TEST_01",
        plate: "29B-999.01",
        status: "ACTIVE_IN_TRANSIT",
        current_s_bus_m: 280.0,
        speed_kmh: 36.0,
        lat: 21.0125,
        lon: 105.8500,
        telemetry_source: "timbus_5s"
    }
]);

// Anti-teleport check: immediately after updateBuses, currentS must NOT snap to 280m!
assert(Math.abs(busKin.currentS - 280.0) > 5.0, `Anti-Teleport Invariant: vehicle must NOT snap to 280m! (remains at ${busKin.currentS.toFixed(2)}m)`);
assert(busKin.targetSpeedMps >= 12.0 && busKin.targetSpeedMps <= 16.0, `Interception Velocity: v_target must be ~14 m/s to intercept lead position (got ${busKin.targetSpeedMps.toFixed(2)} m/s)`);

// Advance time by 4.5s: vehicle smoothly accelerates, intercepts the lead position and converges!
advanceVirtualTime(4500);
// Ground truth lead: 280 + 10 * 4.5 = 325m.
assert(Math.abs(busKin.currentS - 325.0) < 5.0, `Interception Convergence: After 4.5s, vehicle must intercept lead position ~325m (got ${busKin.currentS.toFixed(2)}m)`);

console.log("\n--- TEST GROUP 6: OVERSHOOT INTERCEPTION (Xe ảo chạy nhanh hơn xe thật -> Giảm tốc chờ, không giật lùi) ---");
// Vehicle is now at s ≈ 323m.
// A packet arrives indicating actual vehicle stopped at red light at s_meas = 310m, speed = 0 km/h!
// The virtual vehicle has overshot by ~13m.
// Invariant: virtual vehicle MUST NOT snap backwards to 310m!
// It must decelerate to 0 at its current position and wait smoothly.
const sBeforeOvershoot = busKin.currentS;
mapManager.updateBuses([
    {
        vehicle_id: "BUS_TEST_01",
        plate: "29B-999.01",
        status: "ACTIVE_IN_TRANSIT",
        current_s_bus_m: 310.0,
        speed_kmh: 0.0,
        lat: 21.0128,
        lon: 105.8500,
        telemetry_source: "timbus_5s"
    }
]);

assert(busKin.currentS >= sBeforeOvershoot - 0.01, `Zero Reverse on Overshoot: Vehicle must not snap backwards to 310m! (remains at ${busKin.currentS.toFixed(2)}m)`);
assert(busKin.currentS > 310.0 + 5.0, `Vehicle position must stay at forward virtual point > 310m (current: ${busKin.currentS.toFixed(2)}m)`);
assert(busKin.targetSpeedMps === 0.0, `Damped Stop: targetSpeedMps must be 0 to smoothly decelerate`);

advanceVirtualTime(2000);
assert(busKin.effectiveSpeedMps < 0.1, `Vehicle must come to a smooth standstill without any jitter (got ${busKin.effectiveSpeedMps.toFixed(3)} m/s)`);

console.log("\n" + "=".repeat(80));
console.log(`🎉 [HOÀN TOÀN THÀNH CÔNG] ĐÃ VƯỢT QUA ${passedCount}/${totalTests} TIÊU CHÍ KIỂM ĐỊNH ĐỘNG HỌC!`);
console.log("=".repeat(80));
