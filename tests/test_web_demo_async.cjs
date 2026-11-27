const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      isConnected: true, style: {}, classList: {add() {}, remove() {}},
      textContent: '', innerHTML: '', addEventListener() {},
    });
    return elements.get(id);
  }
  const requests = [];
  const layer = () => ({layers: [], addTo() {return this;}, remove() {},
    clearLayers() {this.layers = [];}, addLayer(item) {this.layers.push(item);}, on() {}, getBounds() {return [];}});
  const map = {...layer(), fitBounds() {}};
  const context = vm.createContext({
    console: {...console, error(...args) {throw new Error(args.join(' '));}},
    setInterval() {return 1;}, clearInterval() {},
    document: {getElementById: element, addEventListener() {}, createElement: () => element(Symbol())},
    L: {map: () => map, tileLayer: layer, layerGroup: layer,
        control: {layers: layer}, polyline: coordinates => ({...layer(), coordinates}),
        divIcon: x => x, marker: () => ({...layer(), bindPopup() {}})},
    fetch(url) {return new Promise((resolve, reject) => requests.push({url, resolve, reject}));},
  });
  const source = fs.readFileSync(path.join(__dirname, '../modules/eta/web_demo/static/app.js'), 'utf8');
  // Expose closure state only inside this VM; production has no testing exports.
  vm.runInContext(source.replace(/\}\)\(\);\s*$/, `
    globalThis.api = {pollVehicles, clearRouteLayers, fetchRouteShape, fetchRouteStations,
      updateStationFocusCard, loadStationPopupEta, refreshOpenPopupEta, unpinStation,
      setRoute(id, direction=0) {currentRouteId=id; currentDirection=direction;},
      setPinned(value) {pinnedStation=value;},
      state() {return {latestLiveVehicles, routePolyline, latestPinnedEtaData,
        latestPopupEtaData, latestPopupStationRef, isPolling, activePollIntervalMs, stationsLayerGroup};}};
  })();`), context);
  function reply(index, data, ok=true) {
    requests[index].resolve({ok, status: ok ? 200 : 500, json: async () => data});
  }
  return {api: context.api, requests, reply, element};
}

test('route changes start a new poll and discard late data, including A -> B -> A', async () => {
  const h = harness();
  h.api.setRoute(1);
  const old = h.api.pollVehicles();
  h.api.clearRouteLayers(); h.api.setRoute(2);
  const next = h.api.pollVehicles();
  assert.equal(h.requests.length, 2);
  h.reply(0, {vehicles: [], timbus_supported: true, poll_interval_sec: 5});
  await old;
  assert.equal(h.api.state().isPolling, true);
  assert.equal(h.api.state().activePollIntervalMs, 15000);
  h.reply(1, {vehicles: [], poll_interval_sec: 15}); await next;
  assert.equal(h.api.state().isPolling, false);
  const delayedB = h.api.pollVehicles();
  h.api.clearRouteLayers(); h.api.setRoute(1);
  const finalA = h.api.pollVehicles();
  h.reply(3, {vehicles: [], poll_interval_sec: 15}); await finalA;
  h.reply(2, {vehicles: [{id: 'stale'}], timbus_supported: true}); await delayedB;
  assert.equal(h.api.state().latestLiveVehicles.length, 0);
  assert.equal(h.api.state().activePollIntervalMs, 15000);
});

test('late route shape cannot replace the current route, even when returning to A', async () => {
  const h = harness(); h.api.setRoute(1);
  const old = h.api.fetchRouteShape(1, 0);
  h.api.clearRouteLayers(); h.api.setRoute(2);
  h.api.clearRouteLayers(); h.api.setRoute(1);
  const next = h.api.fetchRouteShape(1, 0);
  h.reply(1, {coordinates: [[1, 2], [3, 4]]}); await next;
  h.reply(0, {coordinates: [[5, 6], [7, 8]]}); await old;
  assert.equal(h.api.state().routePolyline.coordinates[0][0], 1);
});

test('late pinned ETA cannot replace a newly pinned station or restore an unpinned card', async () => {
  const h = harness(); h.api.setRoute(1);
  h.api.setPinned({routeId: 1, direction: 0, stationOrder: 1});
  const old = h.api.updateStationFocusCard();
  h.api.setPinned({routeId: 1, direction: 0, stationOrder: 2});
  const next = h.api.updateStationFocusCard();
  const latest = {buses: [], target_station: {station_name: 'new station'}};
  h.reply(1, latest); await next;
  h.reply(0, {buses: [], target_station: {station_name: 'old station'}}); await old;
  assert.equal(h.api.state().latestPinnedEtaData, latest);
  const pending = h.api.updateStationFocusCard(); h.api.unpinStation();
  h.reply(2, latest); await pending;
  assert.equal(h.api.state().latestPinnedEtaData, null);
});

test('responses for earlier requests to the same pinned station are discarded', async () => {
  const h = harness(); h.api.setRoute(1);
  h.api.setPinned({routeId: 1, direction: 0, stationOrder: 1});
  const old = h.api.updateStationFocusCard(); const next = h.api.updateStationFocusCard();
  const latest = {buses: [], target_station: {station_name: 'latest'}};
  h.reply(1, latest); await next;
  h.reply(0, {buses: [], target_station: {station_name: 'stale'}}); await old;
  assert.equal(h.api.state().latestPinnedEtaData, latest);
});

test('opening another popup invalidates both its initial and refresh requests', async () => {
  const h = harness(); h.api.setRoute(1);
  const old = h.api.loadStationPopupEta({station_order: 1}, 1, 3, 0);
  const refresh = h.api.refreshOpenPopupEta();
  const next = h.api.loadStationPopupEta({station_order: 2}, 2, 3, 0);
  const latest = {buses: [], message: 'current'};
  h.reply(2, latest); await next;
  h.reply(1, {buses: [], message: 'stale refresh'}); await refresh;
  h.reply(0, {buses: [], message: 'stale initial'}); await old;
  assert.equal(h.api.state().latestPopupEtaData, latest);
  assert.equal(h.api.state().latestPopupStationRef.stationOrder, 2);
});

test('a disconnected popup cannot change polling or the cached ETA', async () => {
  const h = harness(); h.api.setRoute(1);
  const pending = h.api.loadStationPopupEta({station_order: 1}, 1, 2, 0);
  h.element('popupEtaSection_1').isConnected = false;
  h.reply(0, {buses: [], timbus_supported: true}); await pending;
  assert.equal(h.api.state().latestPopupEtaData, null);
  assert.equal(h.api.state().activePollIntervalMs, 15000);
});

test('late stations from the previous direction cannot overwrite the current layer', async () => {
  const h = harness(); h.api.setRoute(1);
  const old = h.api.fetchRouteStations(1, 0);
  h.api.clearRouteLayers(); h.api.setRoute(1, 1);
  const next = h.api.fetchRouteStations(1, 1);
  h.reply(1, {stations: [{lat: 1, lon: 2, station_order: 0, station_name: 'new'}]}); await next;
  const current = h.api.state().stationsLayerGroup.layers[0];
  h.reply(0, {stations: [{lat: 3, lon: 4, station_order: 0, station_name: 'old'}]}); await old;
  assert.equal(h.api.state().stationsLayerGroup.layers[0], current);
});
