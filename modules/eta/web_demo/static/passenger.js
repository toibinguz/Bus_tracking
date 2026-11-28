(function () {
  'use strict';

  const C = window.BusCore;
  const DEFAULT_POLL_MS = 15000;
  const TIMBUS_POLL_MS = 5000;

  const appShell = document.getElementById('appShell');
  const panelEl = document.getElementById('passengerPanel');
  const btnCollapsePanel = document.getElementById('btnCollapsePanel');
  const btnExpandPanel = document.getElementById('btnExpandPanel');
  const btnSheetCycle = document.getElementById('btnSheetCycle');

  const routeSearchInput = document.getElementById('routeSearchInput');
  const btnClearRouteSearch = document.getElementById('btnClearRouteSearch');
  const routeDropdown = document.getElementById('routeDropdown');
  const routeSummaryText = document.getElementById('routeSummaryText');
  const dirGoBtn = document.getElementById('dirGoBtn');
  const dirBackBtn = document.getElementById('dirBackBtn');

  const liveStatusPill = document.getElementById('liveStatusPill');
  const vehicleCountEl = document.getElementById('vehicleCount');
  const countdownEl = document.getElementById('countdown');
  const btnManualRefresh = document.getElementById('btnManualRefresh');
  const upstreamAlert = document.getElementById('upstreamAlert');

  const pinnedCard = document.getElementById('pinnedCard');
  const etaIdleHint = document.getElementById('etaIdleHint');
  const stationSearchInput = document.getElementById('stationSearchInput');
  const btnClearStationSearch = document.getElementById('btnClearStationSearch');
  const stationDropdown = document.getElementById('stationDropdown');
  const panelResizer = document.getElementById('panelResizer');

  const map = L.map('map', { zoomControl: true }).setView([21.0285, 105.8542], 13);
  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { maxZoom: 19, attribution: 'Tiles &copy; Esri' }
  ).addTo(map);

  const routeShapeLayer = L.layerGroup().addTo(map);
  const stationLayer = L.layerGroup().addTo(map);
  const busLayer = L.layerGroup().addTo(map);

  let routesCatalog = [];
  let currentRouteId = null;
  let currentRouteMeta = null;
  let currentDirection = 0;
  let currentStations = [];
  let latestVehicles = [];
  let pinnedStation = null;
  let leadingBusInfo = null; // { vehicleId, label }

  let generation = 0;
  let activePollMs = DEFAULT_POLL_MS;
  let countdownSec = 15;
  let pollTimer = null;
  let countdownTimer = null;
  let isPolling = false;
  let busMarkers = new Map();
  let stationMarkers = new Map();
  let sheetStateIdx = 0;
  const SHEET_STATES = ['', 'sheet-full', 'sheet-peek'];

  function showAlert(msg, isDanger) {
    if (!msg) {
      upstreamAlert.hidden = true;
      upstreamAlert.textContent = '';
      upstreamAlert.classList.remove('is-danger');
      return;
    }
    upstreamAlert.textContent = msg;
    upstreamAlert.classList.toggle('is-danger', Boolean(isDanger));
    upstreamAlert.hidden = false;
  }

  function renderRouteDropdown(filterText) {
    const q = C.normalizeText(filterText);
    const filtered = q
      ? routesCatalog.filter((r) => C.normalizeText(`${r.route_no} ${r.name}`).includes(q))
      : routesCatalog;

    if (filtered.length === 0) {
      routeDropdown.innerHTML = '<div class="station-empty">Không tìm thấy tuyến phù hợp.</div>';
      routeDropdown.hidden = false;
      return;
    }

    routeDropdown.innerHTML = filtered
      .slice(0, 80)
      .map((r) => {
        const selected = r.route_id === currentRouteId ? 'true' : 'false';
        return `
          <button type="button" class="route-option" role="option" aria-selected="${selected}" data-route-id="${r.route_id}">
            <span class="route-code-tag">${C.escapeHtml(r.route_no)}</span>
            <span class="route-name-text">${C.escapeHtml(r.name)}</span>
          </button>
        `;
      })
      .join('');
    routeDropdown.hidden = false;
  }

  function setActiveRouteLabel(meta) {
    if (!meta) return;
    routeSearchInput.value = `${meta.route_no} — ${meta.name}`;
    btnClearRouteSearch.hidden = false;
    routeSummaryText.textContent = `Tuyến ${meta.route_no}: ${meta.name}`;
  }

  function selectRoute(routeId) {
    const meta = routesCatalog.find((r) => r.route_id === Number(routeId));
    if (!meta) return;
    currentRouteId = meta.route_id;
    currentRouteMeta = meta;
    setActiveRouteLabel(meta);
    routeDropdown.hidden = true;
    unpinStation();
    reloadRouteContext(true);
  }

  function setDirection(dir) {
    if (dir === currentDirection) return;
    currentDirection = dir;
    dirGoBtn.classList.toggle('active', dir === 0);
    dirBackBtn.classList.toggle('active', dir === 1);
    unpinStation();
    reloadRouteContext(true);
  }

  function renderStationDropdown(filterText) {
    const q = C.normalizeText(filterText);
    const list = q
      ? currentStations.filter((s) => C.normalizeText(`${s.station_order + 1} ${s.station_name}`).includes(q))
      : currentStations;

    if (list.length === 0) {
      stationDropdown.innerHTML = '<div class="station-empty">Không tìm thấy trạm phù hợp.</div>';
      stationDropdown.hidden = false;
      return;
    }

    stationDropdown.innerHTML = list
      .map((s) => {
        const isPinned = pinnedStation && pinnedStation.station_order === s.station_order;
        return `
          <button type="button" class="route-option" role="option" aria-selected="${isPinned ? 'true' : 'false'}" data-order="${s.station_order}">
            <span class="route-code-tag">#${s.station_order + 1}</span>
            <span class="route-name-text">${C.escapeHtml(s.station_name)}</span>
          </button>
        `;
      })
      .join('');
    stationDropdown.hidden = false;
  }

  function setActiveStationLabel(station) {
    if (!station) {
      stationSearchInput.value = '';
      btnClearStationSearch.hidden = true;
      return;
    }
    stationSearchInput.value = `#${station.station_order + 1} — ${station.station_name}`;
    btnClearStationSearch.hidden = false;
  }

  function updateStationMarkerStyles() {
    for (const [order, marker] of stationMarkers.entries()) {
      const isPinned = pinnedStation && pinnedStation.station_order === order;
      marker.setIcon(C.createStationIcon(Boolean(isPinned)));
      marker.setZIndexOffset(isPinned ? 500 : 0);
    }
  }

  function pinStation(station, panToStation) {
    if (!station) return;
    pinnedStation = {
      routeId: currentRouteId,
      direction: currentDirection,
      station_order: station.station_order,
      station_name: station.station_name,
      lat: station.lat,
      lon: station.lon,
    };
    setActiveStationLabel(station);
    stationDropdown.hidden = true;
    etaIdleHint.hidden = true;
    updateStationMarkerStyles();
    if (panToStation && station.lat && station.lon) {
      map.panTo([station.lat, station.lon], { animate: true });
    }
    refreshPinnedEta();
  }

  function unpinStation() {
    pinnedStation = null;
    leadingBusInfo = null;
    pinnedCard.hidden = true;
    pinnedCard.innerHTML = '';
    etaIdleHint.hidden = false;
    setActiveStationLabel(null);
    updateStationMarkerStyles();
    renderBusMarkers(latestVehicles);
  }

  async function refreshPinnedEta() {
    if (!pinnedStation) return;
    const ref = pinnedStation;
    const gen = generation;
    const res = await C.fetchJson(
      `/api/station-eta?route_id=${ref.routeId}&direction=${ref.direction}&station_order=${ref.station_order}`
    );
    if (gen !== generation || !pinnedStation || pinnedStation.station_order !== ref.station_order) return;

    if (!res.ok) {
      pinnedCard.hidden = false;
      const staleNotice = `<div class="alert-banner is-danger">Không cập nhật được ETA (${C.escapeHtml(res.error)}).</div>`;
      if (!pinnedCard.innerHTML) {
        pinnedCard.innerHTML = `
          <div class="pinned-head">
            <div><span class="pinned-kicker">Trạm đang theo dõi</span><h3 class="pinned-station-name">${C.escapeHtml(ref.station_name)}</h3></div>
            <button type="button" class="btn-unpin" id="btnUnpinInline">Bỏ ghim</button>
          </div>${staleNotice}`;
      } else {
        let warn = pinnedCard.querySelector('.eta-stale-inline');
        if (!warn) {
          warn = document.createElement('div');
          warn.className = 'alert-banner is-danger eta-stale-inline';
          pinnedCard.prepend(warn);
        }
        warn.textContent = `Không cập nhật được ETA (${res.error}) — dữ liệu hiển thị có thể đã cũ.`;
      }
      const btn = document.getElementById('btnUnpinInline');
      if (btn) btn.onclick = unpinStation;
      return;
    }

    const data = res.data;
    syncPollInterval(Boolean(data.timbus_supported), data.poll_interval_sec);
    const buses = data.buses || [];

    if (buses.length > 0) {
      const b0 = buses[0];
      leadingBusInfo = {
        vehicleId: b0.vehicle_id,
        label: `${b0.display_text} • ${b0.plate}`,
      };
    } else {
      leadingBusInfo = null;
    }
    renderBusMarkers(latestVehicles);
    renderPinnedCard(ref, data);
  }

  function renderPinnedCard(ref, data) {
    const buses = data.buses || [];
    let bodyHtml = '';

    if (data.upstream_status === 'upstream_error') {
      bodyHtml = `<div class="alert-banner is-danger">${C.escapeHtml(data.message || 'Lỗi kết nối dữ liệu GPS.')}</div>`;
    } else if (buses.length === 0) {
      bodyHtml = `<div class="pinned-empty">${C.escapeHtml(data.message || 'Hiện chưa có xe nào đang hướng tới trạm này.')}</div>`;
    } else {
      const b0 = buses[0];
      const sw = b0.safe_window || {};
      const p10m = sw.p10_minutes !== undefined ? sw.p10_minutes : Math.ceil((sw.p10_seconds || b0.eta_seconds) / 60);
      const p90m = sw.p90_minutes !== undefined ? sw.p90_minutes : Math.ceil((sw.p90_seconds || b0.eta_seconds) / 60);
      const traffic = C.trafficMeta(b0.traffic_status);
      const fbChip = b0.prediction_source === 'baseline_fallback'
        ? `<span class="fallback-chip">Ước tính nền (${C.escapeHtml(C.fallbackLabel(b0.fallback_reason))})</span>`
        : '';

      const nextHtml = buses.slice(1, 3).map((bx) => `
        <div class="next-bus-row">
          <div class="next-bus-left">
            <span class="next-bus-plate">${C.escapeHtml(bx.plate)}</span>
            <span class="next-bus-sub">Còn ${bx.stops_remaining} trạm &bull; ${C.formatDistance(bx.distance_to_station_m)}</span>
          </div>
          <span class="next-bus-eta">${C.escapeHtml(bx.display_text)} (${C.formatClock(bx)})</span>
        </div>
      `).join('');

      bodyHtml = `
        <div class="hero-bus">
          <div class="hero-bus-top">
            <span class="hero-tag">Xe gần trạm nhất</span>
            <span class="hero-plate">${C.escapeHtml(b0.plate)}</span>
          </div>
          <div class="hero-eta-row">
            <span class="hero-eta-min">${C.escapeHtml(b0.display_text)}</span>
            <span class="hero-eta-clock">Đến lúc ${C.escapeHtml(C.formatClock(b0))}</span>
          </div>
          <div class="hero-meta-grid">
            <div>
              <div class="meta-cell-label">Khoảng an toàn</div>
              <div class="meta-cell-val">${p10m}–${p90m} phút</div>
            </div>
            <div>
              <div class="meta-cell-label">Khoảng cách</div>
              <div class="meta-cell-val">${b0.stops_remaining} trạm &bull; ${C.formatDistance(b0.distance_to_station_m)}</div>
            </div>
            <div>
              <div class="meta-cell-label">Giao thông</div>
              <div class="meta-cell-val ${traffic.cls}">${C.escapeHtml(traffic.label)}</div>
            </div>
          </div>
          ${fbChip}
        </div>
        ${nextHtml ? `<div class="next-buses-list">${nextHtml}</div>` : ''}
      `;
    }

    pinnedCard.innerHTML = `
      <div class="pinned-head">
        <div>
          <span class="pinned-kicker">Trạm đang theo dõi (#${ref.station_order + 1})</span>
          <h3 class="pinned-station-name">${C.escapeHtml(ref.station_name)}</h3>
        </div>
        <button type="button" class="btn-unpin" id="btnUnpinStation">Bỏ ghim</button>
      </div>
      ${bodyHtml}
    `;
    pinnedCard.hidden = false;
    const unpinBtn = document.getElementById('btnUnpinStation');
    if (unpinBtn) unpinBtn.onclick = unpinStation;
  }

  function renderBusMarkers(vehicles) {
    const activeIds = new Set();
    for (const v of vehicles || []) {
      activeIds.add(v.id);
      const isLeading = Boolean(leadingBusInfo && v.id === leadingBusInfo.vehicleId);
      const icon = C.createBusIcon(v, {
        isLeading,
        leadingText: isLeading ? leadingBusInfo.label : '',
      });
      const existing = busMarkers.get(v.id);
      if (existing) {
        existing.setLatLng([v.lat, v.lng]);
        existing.setIcon(icon);
        existing.setZIndexOffset(isLeading ? 800 : 100);
      } else {
        const marker = L.marker([v.lat, v.lng], {
          icon,
          zIndexOffset: isLeading ? 800 : 100,
        }).addTo(busLayer);
        busMarkers.set(v.id, marker);
      }
    }
    for (const [id, marker] of busMarkers.entries()) {
      if (!activeIds.has(id)) {
        busLayer.removeLayer(marker);
        busMarkers.delete(id);
      }
    }
  }

  async function loadRouteGeometry(gen, fitBounds) {
    routeShapeLayer.clearLayers();
    stationLayer.clearLayers();
    stationMarkers.clear();
    currentStations = [];
    stationSearchInput.placeholder = 'Đang tải danh sách trạm...';

    const [shapeRes, stRes] = await Promise.all([
      C.fetchJson(`/api/route-shape?route_id=${currentRouteId}&direction=${currentDirection}`),
      C.fetchJson(`/api/route-stations?route_id=${currentRouteId}&direction=${currentDirection}`),
    ]);
    if (gen !== generation) return;

    if (shapeRes.ok && shapeRes.data && shapeRes.data.coordinates && shapeRes.data.coordinates.length > 1) {
      const poly = L.polyline(shapeRes.data.coordinates, {
        color: '#0284c7',
        weight: 4.5,
        opacity: 0.78,
      }).addTo(routeShapeLayer);
      if (fitBounds) {
        map.fitBounds(poly.getBounds(), { padding: [48, 48] });
      }
    }

    if (stRes.ok && stRes.data && stRes.data.stations) {
      currentStations = stRes.data.stations;
      for (const st of currentStations) {
        const marker = L.marker([st.lat, st.lon], {
          icon: C.createStationIcon(false),
          title: st.station_name,
        }).addTo(stationLayer);
        // Click trạm trên bản đồ -> TỰ GHIM LUÔN, KHÔNG hiện popup
        marker.on('click', () => pinStation(st, false));
        stationMarkers.set(st.station_order, marker);
      }
    }
    stationSearchInput.placeholder = `Chọn hoặc tìm trong ${currentStations.length} trạm...`;
  }

  async function pollVehicles(force = false) {
    if (!currentRouteId || (isPolling && !force)) return;
    isPolling = true;
    const gen = generation;
    try {
      const res = await C.fetchJson(`/api/live-vehicles?route_id=${currentRouteId}&direction=${currentDirection}`);
      if (gen !== generation) return;

      if (!res.ok) {
        liveStatusPill.classList.add('is-error');
        vehicleCountEl.textContent = 'Mất kết nối';
        showAlert(`Không thể tải vị trí xe (${res.error}).`, true);
        resetCountdown();
        return;
      }

      const data = res.data;
      syncPollInterval(Boolean(data.timbus_supported), data.poll_interval_sec);
      latestVehicles = data.vehicles || [];

      if (data.upstream_status === 'upstream_error') {
        liveStatusPill.classList.add('is-error');
        vehicleCountEl.textContent = 'Lỗi BusMap';
        showAlert(`Lỗi kết nối BusMap upstream: ${data.upstream_error || 'Tạm gián đoạn'}.`, true);
      } else {
        liveStatusPill.classList.remove('is-error');
        vehicleCountEl.textContent = `${latestVehicles.length} xe`;
        const tbWarn = (data.timbus_status === 'upstream_error' || data.timbus_status === 'partial_error')
          ? 'TimBus đang gián đoạn (tạm dùng BusMap).'
          : '';
        showAlert(tbWarn, false);
      }

      renderBusMarkers(latestVehicles);
      if (pinnedStation) {
        refreshPinnedEta();
      }
      resetCountdown();
    } finally {
      if (gen === generation) {
        isPolling = false;
      }
    }
  }

  function syncPollInterval(supportsFast, serverSec) {
    const targetMs = (supportsFast || serverSec === 5) ? TIMBUS_POLL_MS : DEFAULT_POLL_MS;
    if (targetMs !== activePollMs) {
      activePollMs = targetMs;
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = setInterval(pollVehicles, activePollMs);
      }
    }
  }

  function resetCountdown() {
    countdownSec = Math.floor(activePollMs / 1000);
    countdownEl.textContent = `${countdownSec}s`;
  }

  function startTimers() {
    if (pollTimer) clearInterval(pollTimer);
    if (countdownTimer) clearInterval(countdownTimer);
    pollTimer = setInterval(pollVehicles, activePollMs);
    countdownTimer = setInterval(() => {
      if (countdownSec > 1) {
        countdownSec -= 1;
        countdownEl.textContent = `${countdownSec}s`;
      }
    }, 1000);
  }

  async function reloadRouteContext(fitBounds) {
    generation += 1;
    const gen = generation;
    busLayer.clearLayers();
    busMarkers.clear();
    latestVehicles = [];
    leadingBusInfo = null;
    showAlert('', false);

    await loadRouteGeometry(gen, fitBounds);
    if (gen !== generation) return;
    await pollVehicles(true);
    startTimers();
  }

  // Event bindings
  btnCollapsePanel.addEventListener('click', () => {
    appShell.classList.add('panel-collapsed');
    btnExpandPanel.hidden = false;
    setTimeout(() => map.invalidateSize(), 150);
  });

  btnExpandPanel.addEventListener('click', () => {
    appShell.classList.remove('panel-collapsed');
    btnExpandPanel.hidden = true;
    setTimeout(() => map.invalidateSize(), 150);
  });

  btnSheetCycle.addEventListener('click', () => {
    sheetStateIdx = (sheetStateIdx + 1) % SHEET_STATES.length;
    panelEl.classList.remove('sheet-full', 'sheet-peek');
    if (SHEET_STATES[sheetStateIdx]) {
      panelEl.classList.add(SHEET_STATES[sheetStateIdx]);
    }
  });

  routeSearchInput.addEventListener('focus', () => {
    routeSearchInput.select();
    renderRouteDropdown('');
  });

  routeSearchInput.addEventListener('input', () => {
    btnClearRouteSearch.hidden = !routeSearchInput.value;
    renderRouteDropdown(routeSearchInput.value);
  });

  btnClearRouteSearch.addEventListener('click', () => {
    routeSearchInput.value = '';
    btnClearRouteSearch.hidden = true;
    routeSearchInput.focus();
    renderRouteDropdown('');
  });

  routeDropdown.addEventListener('click', (e) => {
    const btn = e.target.closest('.route-option');
    if (!btn) return;
    selectRoute(btn.dataset.routeId);
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('#routeCombobox')) {
      routeDropdown.hidden = true;
      if (currentRouteMeta && !routeSearchInput.value.trim()) {
        setActiveRouteLabel(currentRouteMeta);
      }
    }
    if (!e.target.closest('#stationCombobox')) {
      stationDropdown.hidden = true;
      if (pinnedStation && !stationSearchInput.value.trim()) {
        setActiveStationLabel(pinnedStation);
      }
    }
  });

  dirGoBtn.addEventListener('click', () => setDirection(0));
  dirBackBtn.addEventListener('click', () => setDirection(1));
  btnManualRefresh.addEventListener('click', () => pollVehicles());

  stationSearchInput.addEventListener('focus', () => {
    stationSearchInput.select();
    renderStationDropdown('');
  });

  stationSearchInput.addEventListener('input', () => {
    btnClearStationSearch.hidden = !stationSearchInput.value;
    renderStationDropdown(stationSearchInput.value);
  });

  btnClearStationSearch.addEventListener('click', () => {
    stationSearchInput.value = '';
    btnClearStationSearch.hidden = true;
    stationSearchInput.focus();
    renderStationDropdown('');
  });

  stationDropdown.addEventListener('click', (e) => {
    const btn = e.target.closest('.route-option');
    if (!btn) return;
    const order = Number(btn.dataset.order);
    const st = currentStations.find((s) => s.station_order === order);
    if (st) pinStation(st, true);
  });

  // Drag-resize panel width on desktop
  if (panelResizer) {
    let dragging = false;
    panelResizer.addEventListener('pointerdown', (e) => {
      dragging = true;
      panelResizer.classList.add('is-dragging');
      panelResizer.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    panelResizer.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      const maxW = Math.min(680, window.innerWidth - 32);
      const newW = Math.max(280, Math.min(maxW, Math.round(e.clientX - 16)));
      appShell.style.setProperty('--panel-w', `${newW}px`);
      panelEl.style.setProperty('--panel-w', `${newW}px`);
      map.invalidateSize();
    });
    const stopDrag = () => {
      if (!dragging) return;
      dragging = false;
      panelResizer.classList.remove('is-dragging');
      map.invalidateSize();
    };
    panelResizer.addEventListener('pointerup', stopDrag);
    panelResizer.addEventListener('pointercancel', stopDrag);
  }

  // Boot
  (async function init() {
    const res = await C.fetchJson('/api/routes');
    if (!res.ok || !Array.isArray(res.data) || res.data.length === 0) {
      showAlert(`Không tải được danh mục tuyến (${res.error || 'rỗng'}).`, true);
      return;
    }
    routesCatalog = res.data;
    const preferred = routesCatalog.find((r) => r.route_no === '32') || routesCatalog[0];
    selectRoute(preferred.route_id);
  })();
})();
