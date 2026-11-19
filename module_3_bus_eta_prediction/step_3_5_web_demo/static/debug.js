(function () {
  'use strict';

  const C = window.BusCore;
  const DEFAULT_POLL_MS = 15000;
  const TIMBUS_POLL_MS = 5000;

  const routeInput = document.getElementById('dbgRouteInput');
  const routeDropdown = document.getElementById('dbgRouteDropdown');
  const dirGoBtn = document.getElementById('dbgDirGo');
  const dirBackBtn = document.getElementById('dbgDirBack');
  const pauseBtn = document.getElementById('dbgPauseBtn');
  const refreshBtn = document.getElementById('dbgRefreshBtn');
  const countdownEl = document.getElementById('dbgCountdown');
  const healthBadge = document.getElementById('dbgHealthBadge');
  const healthText = document.getElementById('dbgHealthText');

  const stationSelect = document.getElementById('dbgStationSelect');
  const etaChips = document.getElementById('dbgEtaChips');
  const etaAlert = document.getElementById('dbgEtaAlert');
  const etaTbody = document.getElementById('dbgEtaTbody');
  const cntApproaching = document.getElementById('cntApproaching');

  const liveChips = document.getElementById('dbgLiveChips');
  const liveAlert = document.getElementById('dbgLiveAlert');
  const fleetTbody = document.getElementById('dbgFleetTbody');
  const cntFleet = document.getElementById('cntFleet');
  const systemGrid = document.getElementById('dbgSystemGrid');
  const workspaceEl = document.getElementById('dbgWorkspace');
  const splitterEl = document.getElementById('dbgSplitter');

  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  const panels = Array.from(document.querySelectorAll('[role="tabpanel"]'));

  const map = L.map('dbgMap', { zoomControl: true }).setView([21.0285, 105.8542], 13);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri',
  }).addTo(map);

  const shapeLayer = L.layerGroup().addTo(map);
  const stationLayer = L.layerGroup().addTo(map);
  const busLayer = L.layerGroup().addTo(map);

  let catalog = [];
  let currentRouteId = null;
  let currentRouteMeta = null;
  let currentDirection = 0;
  let currentStations = [];
  let pinnedOrder = null;
  let latestVehicles = [];
  let leadingBusInfo = null;
  let generation = 0;

  let activePollMs = DEFAULT_POLL_MS;
  let countdownSec = 15;
  let isPaused = false;
  let isPolling = false;
  let pollTimer = null;
  let countdownTimer = null;
  let busMarkers = new Map();
  let stationMarkers = new Map();

  // Accessible Tabs
  function activateTab(tab) {
    for (const t of tabs) {
      const selected = t === tab;
      t.setAttribute('aria-selected', selected ? 'true' : 'false');
      t.tabIndex = selected ? 0 : -1;
    }
    const targetId = tab.dataset.panel;
    for (const p of panels) {
      p.hidden = p.id !== targetId;
    }
  }

  for (const tab of tabs) {
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', (e) => {
      const idx = tabs.indexOf(tab);
      let next = null;
      if (e.key === 'ArrowRight') next = tabs[(idx + 1) % tabs.length];
      else if (e.key === 'ArrowLeft') next = tabs[(idx - 1 + tabs.length) % tabs.length];
      else if (e.key === 'Home') next = tabs[0];
      else if (e.key === 'End') next = tabs[tabs.length - 1];
      if (next) {
        e.preventDefault();
        next.focus();
        activateTab(next);
      }
    });
  }

  function renderRouteDropdown(qText) {
    const q = C.normalizeText(qText);
    const list = q ? catalog.filter((r) => C.normalizeText(`${r.route_no} ${r.name}`).includes(q)) : catalog;
    if (!list.length) {
      routeDropdown.innerHTML = '<div class="empty-cell">Không tìm thấy tuyến</div>';
      routeDropdown.hidden = false;
      return;
    }
    routeDropdown.innerHTML = list.slice(0, 80).map((r) => `
      <button type="button" class="dbg-route-opt" data-route-id="${r.route_id}">
        <span class="dbg-route-code">${C.escapeHtml(r.route_no)}</span>
        <span>${C.escapeHtml(r.name)}</span>
      </button>
    `).join('');
    routeDropdown.hidden = false;
  }

  function selectRoute(routeId) {
    const meta = catalog.find((r) => r.route_id === Number(routeId));
    if (!meta) return;
    currentRouteId = meta.route_id;
    currentRouteMeta = meta;
    routeInput.value = `${meta.route_no} — ${meta.name}`;
    routeDropdown.hidden = true;
    pinnedOrder = null;
    reloadRoute(true);
  }

  function setDirection(dir) {
    if (dir === currentDirection) return;
    currentDirection = dir;
    dirGoBtn.classList.toggle('active', dir === 0);
    dirBackBtn.classList.toggle('active', dir === 1);
    pinnedOrder = null;
    reloadRoute(true);
  }

  function pinStationByOrder(order, pan) {
    const st = currentStations.find((s) => s.station_order === Number(order));
    if (!st) return;
    pinnedOrder = st.station_order;
    stationSelect.value = String(pinnedOrder);
    for (const [ord, marker] of stationMarkers.entries()) {
      const isP = ord === pinnedOrder;
      marker.setIcon(C.createStationIcon(isP));
      marker.setZIndexOffset(isP ? 500 : 0);
    }
    if (pan && st.lat && st.lon) {
      map.panTo([st.lat, st.lon], { animate: true });
    }
    refreshEta();
  }

  function renderBusMarkers(vehicles) {
    const active = new Set();
    for (const v of vehicles || []) {
      active.add(v.id);
      const isLead = Boolean(leadingBusInfo && v.id === leadingBusInfo.vehicleId);
      const icon = C.createBusIcon(v, {
        isLeading: isLead,
        leadingText: isLead ? leadingBusInfo.label : '',
      });
      const ex = busMarkers.get(v.id);
      if (ex) {
        ex.setLatLng([v.lat, v.lng]);
        ex.setIcon(icon);
        ex.setZIndexOffset(isLead ? 800 : 100);
      } else {
        const m = L.marker([v.lat, v.lng], { icon, zIndexOffset: isLead ? 800 : 100 }).addTo(busLayer);
        busMarkers.set(v.id, m);
      }
    }
    for (const [id, m] of busMarkers.entries()) {
      if (!active.has(id)) {
        busLayer.removeLayer(m);
        busMarkers.delete(id);
      }
    }
  }

  async function loadGeometry(gen, fitBounds) {
    shapeLayer.clearLayers();
    stationLayer.clearLayers();
    stationMarkers.clear();
    currentStations = [];
    stationSelect.innerHTML = '<option value="">Đang tải trạm...</option>';

    const [shRes, stRes] = await Promise.all([
      C.fetchJson(`/api/route-shape?route_id=${currentRouteId}&direction=${currentDirection}`),
      C.fetchJson(`/api/route-stations?route_id=${currentRouteId}&direction=${currentDirection}`),
    ]);
    if (gen !== generation) return;

    if (shRes.ok && shRes.data && shRes.data.coordinates && shRes.data.coordinates.length > 1) {
      const poly = L.polyline(shRes.data.coordinates, { color: '#38bdf8', weight: 4, opacity: 0.75 }).addTo(shapeLayer);
      if (fitBounds) map.fitBounds(poly.getBounds(), { padding: [36, 36] });
    }

    if (stRes.ok && stRes.data && stRes.data.stations) {
      currentStations = stRes.data.stations;
      stationSelect.innerHTML = '<option value="">-- Chọn trạm ghim --</option>' +
        currentStations.map((s) => `<option value="${s.station_order}">#${s.station_order + 1} ${C.escapeHtml(s.station_name)}</option>`).join('');
      for (const st of currentStations) {
        const marker = L.marker([st.lat, st.lon], {
          icon: C.createStationIcon(false),
          title: `#${st.station_order + 1} ${st.station_name}`,
        }).addTo(stationLayer);
        // Click trạm -> TỰ GHIM LUÔN, KHÔNG popup
        marker.on('click', () => pinStationByOrder(st.station_order, false));
        stationMarkers.set(st.station_order, marker);
      }
      if (currentStations.length > 0 && pinnedOrder === null) {
        const midIdx = Math.min(currentStations.length - 1, Math.floor(currentStations.length / 2));
        pinStationByOrder(currentStations[midIdx].station_order, false);
      }
    }
  }

  async function refreshEta() {
    if (pinnedOrder === null || !currentRouteId) return;
    const gen = generation;
    const res = await C.fetchJson(
      `/api/station-eta?route_id=${currentRouteId}&direction=${currentDirection}&station_order=${pinnedOrder}`
    );
    if (gen !== generation) return;

    if (!res.ok) {
      etaAlert.textContent = `Lỗi tải ETA: ${res.error}`;
      etaAlert.hidden = false;
      return;
    }

    const d = res.data;
    etaAlert.hidden = d.upstream_status !== 'upstream_error';
    if (d.upstream_status === 'upstream_error') {
      etaAlert.textContent = `Upstream error: ${d.upstream_error || d.message}`;
    }

    etaChips.innerHTML = [
      `<span class="chip ${d.upstream_status === 'ok' ? 'ok' : 'danger'}">BM:${C.escapeHtml(d.upstream_status)}</span>`,
      `<span class="chip ${d.timbus_status === 'ok' ? 'ok' : (d.timbus_status === 'unsupported' ? '' : 'warn')}">TB:${C.escapeHtml(d.timbus_status)}</span>`,
      `<span class="chip">${d.poll_interval_sec}s</span>`,
      d.fallback_reason ? `<span class="chip ${d.fallback_reason === 'ok' ? 'ok' : 'warn'}">FB:${C.escapeHtml(d.fallback_reason)}</span>` : '',
    ].join('');

    const buses = d.buses || [];
    cntApproaching.textContent = String(buses.length);
    if (buses.length > 0) {
      leadingBusInfo = {
        vehicleId: buses[0].vehicle_id,
        label: `${buses[0].display_text} • ${buses[0].plate}`,
      };
    } else {
      leadingBusInfo = null;
    }
    renderBusMarkers(latestVehicles);

    if (buses.length === 0) {
      etaTbody.innerHTML = `<tr><td colspan="7" class="empty-cell">${C.escapeHtml(d.message)}</td></tr>`;
      return;
    }

    function formatPacketTiming(isTimbus, primaryIso, bmIso) {
      const nowMs = Date.now();
      const fmtOne = (label, iso) => {
        if (!iso) return null;
        const ms = Date.parse(iso);
        const hms = String(iso).length >= 19 ? String(iso).substring(11, 19) : '--:--:--';
        const age = Number.isFinite(ms) ? `${Math.max(0, Math.round((nowMs - ms) / 1000))}s` : '--';
        return `${label}: <span class="mono">${C.escapeHtml(hms)}</span> (${age})`;
      };
      const parts = [];
      if (isTimbus) {
        const tb = fmtOne('TB query', primaryIso);
        if (tb) parts.push(tb);
        const bm = fmtOne('BM thiết bị', bmIso);
        if (bm) parts.push(bm);
      } else {
        const bm = fmtOne('BM thiết bị', bmIso || primaryIso);
        if (bm) parts.push(bm);
      }
      return parts.join('<br>') || '--';
    }

    etaTbody.innerHTML = buses.map((b, idx) => {
      const sw = b.safe_window || {};
      const srcTag = b.prediction_source === 'ml_calibrated'
        ? '<span class="chip ok">ml_calibrated</span>'
        : `<span class="chip warn">${C.escapeHtml(b.fallback_reason || 'baseline')}</span>`;
      const telTag = b.telemetry_source === 'timbus'
        ? '<span class="chip ok">timbus</span>'
        : '<span class="chip warn">busmap</span>';
      const timeHtml = formatPacketTiming(b.telemetry_source === 'timbus', b.ping_time, b.busmap_updated_at);
      return `
        <tr class="${idx === 0 ? 'is-leading' : ''}" data-vid="${b.vehicle_id}">
          <th scope="row" class="mono">${idx === 0 ? '★ ' : ''}${C.escapeHtml(b.plate)}</th>
          <td>${C.formatDistance(b.distance_to_station_m)} (${b.stops_remaining} trạm)</td>
          <td class="mono"><strong>${Math.round(b.eta_seconds)}s</strong> (${C.escapeHtml(C.formatClock(b))})</td>
          <td class="mono">${Math.round(sw.p10_seconds || 0)}–${Math.round(sw.p90_seconds || 0)}s</td>
          <td class="mono">B:${Math.round(sw.buffer_seconds || 0)}s / +${Math.round(sw.delay_seconds || 0)}s</td>
          <td>${srcTag}</td>
          <td>${telTag}<div style="margin-top:2px;font-size:11px;line-height:1.35">${timeHtml}</div></td>
        </tr>
      `;
    }).join('');
  }

  function renderFleetTable(data) {
    const vehicles = data.vehicles || [];
    cntFleet.textContent = String(vehicles.length);
    liveChips.innerHTML = [
      `<span class="chip ${data.upstream_status === 'ok' ? 'ok' : 'danger'}">BM:${C.escapeHtml(data.upstream_status)}</span>`,
      `<span class="chip ${data.timbus_status === 'ok' ? 'ok' : (data.timbus_status === 'unsupported' ? '' : 'warn')}">TB:${C.escapeHtml(data.timbus_status)}</span>`,
      `<span class="chip">poll:${data.poll_interval_sec}s</span>`,
    ].join('');

    if (data.upstream_status === 'upstream_error') {
      liveAlert.textContent = `BusMap upstream error: ${data.upstream_error || 'unknown'}`;
      liveAlert.hidden = false;
    } else {
      liveAlert.hidden = true;
    }

    if (vehicles.length === 0) {
      fleetTbody.innerHTML = '<tr><td colspan="7" class="empty-cell">Không có xe hoạt động trên chiều này.</td></tr>';
      return;
    }

    const nowMs = Date.now();
    const fmtStamp = (label, iso) => {
      if (!iso) return null;
      const ms = Date.parse(iso);
      const hms = String(iso).length >= 19 ? String(iso).substring(11, 19) : '--:--:--';
      const age = Number.isFinite(ms) ? `${Math.max(0, Math.round((nowMs - ms) / 1000))}s` : '--';
      return `${label}: <span class="mono">${C.escapeHtml(hms)}</span> (${age})`;
    };
    fleetTbody.innerHTML = vehicles.map((v) => {
      const telTag = v.telemetry_source === 'timbus'
        ? '<span class="chip ok">timbus</span>'
        : '<span class="chip warn">busmap</span>';
      const timingLines = [];
      if (v.telemetry_source === 'timbus') {
        const tbLine = fmtStamp('TB query', v.updated_at);
        if (tbLine) timingLines.push(tbLine);
        const bmLine = fmtStamp('BM thiết bị', v.busmap_updated_at);
        if (bmLine) timingLines.push(bmLine);
      } else {
        const bmLine = fmtStamp('BM thiết bị', v.busmap_updated_at || v.updated_at);
        if (bmLine) timingLines.push(bmLine);
      }
      const rawSpd = v.raw_speed_kmh !== null && v.raw_speed_kmh !== undefined ? Number(v.raw_speed_kmh).toFixed(1) : '--';
      const winDt = v.speed_window_sec !== null && v.speed_window_sec !== undefined ? `${Math.round(v.speed_window_sec)}s` : '--';
      return `
        <tr data-vid="${v.id}">
          <th scope="row" class="mono">${C.escapeHtml(v.plate)}</th>
          <td>${telTag}</td>
          <td style="font-size:11px;line-height:1.35">${timingLines.join('<br>') || '--'}</td>
          <td class="mono">${Number(v.speed_kmh || 0).toFixed(1)} km/h</td>
          <td class="mono">${rawSpd} km/h</td>
          <td class="mono">${winDt}</td>
          <td class="mono">${v.current_station_id || '-'} &rarr; ${v.next_station_id || '-'}</td>
        </tr>
      `;
    }).join('');
  }

  async function refreshHealth() {
    const res = await C.fetchJson('/api/health');
    if (!res.ok) {
      healthBadge.classList.add('is-degraded');
      healthText.textContent = `HEALTH ERR (${res.error})`;
      return;
    }
    const h = res.data;
    const p = h.poller || {};
    const counts = p.counts || {};
    const srv = h.serving || {};
    const model = srv.model || {};

    const degraded = !h.healthy || p.circuit_state === 'OPEN';
    healthBadge.classList.toggle('is-degraded', degraded);
    healthText.textContent = `${String(h.status || '').toUpperCase()} | CB:${p.circuit_state || 'N/A'} | Cycle #${p.cycle_count ?? 0}`;

    const gapTop = p.gap_routes_top ? Object.entries(p.gap_routes_top).map(([k, v]) => `${k}(${v})`).join(', ') : '--';
    systemGrid.innerHTML = `
      <div class="sys-card">
        <h3>SpeedLayerPoller</h3>
        <div class="kv-grid">
          <span class="kv-k">Trạng thái</span><span class="kv-v">${C.escapeHtml(p.status || 'unknown')}</span>
          <span class="kv-k">Giờ vận hành (04:45–22:30)</span><span class="kv-v">${p.operating_hours ? 'YES' : 'CLOSED'}</span>
          <span class="kv-k">Số chu kỳ</span><span class="kv-v">${p.cycle_count ?? 0}</span>
          <span class="kv-k">Thời lượng vòng cuối</span><span class="kv-v">${p.last_cycle_duration_sec ?? '--'}s</span>
          <span class="kv-k">Tuổi vòng cuối</span><span class="kv-v">${p.last_cycle_age_sec ?? '--'}s</span>
          <span class="kv-k">Circuit Breaker</span><span class="kv-v">${C.escapeHtml(p.circuit_state || 'CLOSED')} (${p.circuit_remaining_sec ?? 0}s)</span>
        </div>
      </div>
      <div class="sys-card">
        <h3>Bộ đếm Phân loại 4 Trạng thái</h3>
        <div class="kv-grid">
          <span class="kv-k">busmap_ok / busmap_error</span><span class="kv-v">${counts.busmap_ok ?? 0} / ${counts.busmap_error ?? 0}</span>
          <span class="kv-k">RECOVERED_LIVE</span><span class="kv-v">${counts.recovered_live ?? 0}</span>
          <span class="kv-k">TERMINAL_OR_DEPOT_PARKED</span><span class="kv-v">${counts.parked_skip ?? 0}</span>
          <span class="kv-k">ON_CORRIDOR_GAP</span><span class="kv-v">${counts.on_corridor_gap ?? 0}</span>
          <span class="kv-k">UPSTREAM_ERROR</span><span class="kv-v">${counts.upstream_error ?? 0}</span>
          <span class="kv-k">Top tuyến gap</span><span class="kv-v">${C.escapeHtml(gapTop || '--')}</span>
        </div>
      </div>
      <div class="sys-card">
        <h3>ModelRuntime &amp; Serving</h3>
        <div class="kv-grid">
          <span class="kv-k">Model khả dụng</span><span class="kv-v">${h.model_available ? 'TRUE' : 'FALSE'}</span>
          <span class="kv-k">Schema / Trees</span><span class="kv-v">${C.escapeHtml(model.schema || '--')} (${model.best_iteration ?? '--'})</span>
          <span class="kv-k">Baseline routes</span><span class="kv-v">${(srv.baseline_routes || []).length}</span>
          <span class="kv-k">Trace / Raw Capture</span><span class="kv-v">${h.capture?.backend_trace ? 'ON' : 'OFF'} / ${h.capture?.upstream_raw ? 'ON' : 'OFF'}</span>
          <span class="kv-k">Last Poller Error</span><span class="kv-v">${C.escapeHtml(p.last_error || 'none')}</span>
        </div>
      </div>
    `;
  }

  async function pollAll() {
    if (!currentRouteId || isPolling || isPaused) return;
    isPolling = true;
    const gen = generation;
    const [liveRes] = await Promise.all([
      C.fetchJson(`/api/live-vehicles?route_id=${currentRouteId}&direction=${currentDirection}`),
      refreshHealth(),
    ]);
    isPolling = false;
    if (gen !== generation) return;

    if (!liveRes.ok) {
      liveAlert.textContent = `Lỗi tải live-vehicles: ${liveRes.error}`;
      liveAlert.hidden = false;
    } else {
      const d = liveRes.data;
      syncPollInterval(Boolean(d.timbus_supported), d.poll_interval_sec);
      latestVehicles = d.vehicles || [];
      renderFleetTable(d);
      renderBusMarkers(latestVehicles);
      if (pinnedOrder !== null) {
        refreshEta();
      }
    }
    resetCountdown();
  }

  function syncPollInterval(supportsFast, serverSec) {
    const targetMs = (supportsFast || serverSec === 5) ? TIMBUS_POLL_MS : DEFAULT_POLL_MS;
    if (targetMs !== activePollMs) {
      activePollMs = targetMs;
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = setInterval(pollAll, activePollMs);
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
    pollTimer = setInterval(pollAll, activePollMs);
    countdownTimer = setInterval(() => {
      if (!isPaused && countdownSec > 1) {
        countdownSec -= 1;
        countdownEl.textContent = `${countdownSec}s`;
      }
    }, 1000);
  }

  async function reloadRoute(fitBounds) {
    generation += 1;
    const gen = generation;
    busLayer.clearLayers();
    busMarkers.clear();
    latestVehicles = [];
    leadingBusInfo = null;
    await loadGeometry(gen, fitBounds);
    if (gen !== generation) return;
    await pollAll();
    startTimers();
  }

  function focusVehicleOnMap(vid) {
    const v = latestVehicles.find((item) => item.id === Number(vid));
    if (v) map.setView([v.lat, v.lng], Math.max(map.getZoom(), 15), { animate: true });
  }

  routeInput.addEventListener('focus', () => {
    routeInput.select();
    renderRouteDropdown('');
  });
  routeInput.addEventListener('input', () => renderRouteDropdown(routeInput.value));
  routeDropdown.addEventListener('click', (e) => {
    const btn = e.target.closest('.dbg-route-opt');
    if (btn) selectRoute(btn.dataset.routeId);
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#dbgRouteCombobox')) routeDropdown.hidden = true;
  });

  dirGoBtn.addEventListener('click', () => setDirection(0));
  dirBackBtn.addEventListener('click', () => setDirection(1));
  stationSelect.addEventListener('change', () => {
    if (stationSelect.value !== '') pinStationByOrder(stationSelect.value, true);
  });
  refreshBtn.addEventListener('click', () => {
    const wasPaused = isPaused;
    isPaused = false;
    pollAll().finally(() => { isPaused = wasPaused; });
  });
  pauseBtn.addEventListener('click', () => {
    isPaused = !isPaused;
    pauseBtn.textContent = isPaused ? 'Tiếp tục' : 'Tạm dừng';
  });

  etaTbody.addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-vid]');
    if (tr) focusVehicleOnMap(tr.dataset.vid);
  });
  fleetTbody.addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-vid]');
    if (tr) focusVehicleOnMap(tr.dataset.vid);
  });

  if (splitterEl && workspaceEl) {
    let dragging = false;
    splitterEl.addEventListener('pointerdown', (e) => {
      dragging = true;
      splitterEl.classList.add('is-dragging');
      splitterEl.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    splitterEl.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      const rect = workspaceEl.getBoundingClientRect();
      if (rect.width <= 0) return;
      const pct = Math.max(22, Math.min(72, ((e.clientX - rect.left) / rect.width) * 100));
      workspaceEl.style.setProperty('--map-col', `${pct.toFixed(1)}%`);
      map.invalidateSize();
    });
    const stopSplit = () => {
      if (!dragging) return;
      dragging = false;
      splitterEl.classList.remove('is-dragging');
      map.invalidateSize();
    };
    splitterEl.addEventListener('pointerup', stopSplit);
    splitterEl.addEventListener('pointercancel', stopSplit);
  }

  (async function init() {
    const res = await C.fetchJson('/api/routes');
    if (!res.ok || !Array.isArray(res.data) || !res.data.length) {
      healthBadge.classList.add('is-degraded');
      healthText.textContent = `ROUTES ERR (${res.error || 'empty'})`;
      return;
    }
    catalog = res.data;
    const preferred = catalog.find((r) => r.route_no === '32') || catalog[0];
    selectRoute(preferred.route_id);
  })();
})();
