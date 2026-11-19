/**
 * Hanoi Bus Live - Discrete Stepped Tracking Client
 * 100% Thuan BusMap roi rac - UX truc tiep, khong noi suy
 */

(() => {
  'use strict';

  // Constants
  const POLL_INTERVAL_MS = 15000;
  const TIMBUS_POLL_MS = 5000;
  const HANOI_COORDS = [21.0285, 105.8542];
  const DEFAULT_ZOOM = 13;
  const DEFAULT_ROUTE_NO = '27';
  const COLOR_GO = '#10b981';
  const COLOR_RE = '#3b82f6';

  // State
  let currentRouteId = null;
  let currentDirection = 0; // 0: Chiều đi, 1: Chiều về
  let activePollIntervalMs = POLL_INTERVAL_MS;
  let countdownSeconds = 15;
  let pollTimer = null;
  let countdownTimer = null;
  let isPolling = false;
  let routeGeneration = 0;
  let focusRequestId = 0;
  let popupRequestId = 0;
  let latestLiveVehicles = [];

  // Active markers map: vehicleId -> Leaflet Marker
  const activeMarkers = new Map();
  const routeTimbusMap = new Map();

  // Pinned Station State (SPEC-08)
  let pinnedStation = null;

  // Polyline tim tuyến & Nhóm trạm dừng đánh số
  let routePolyline = null;
  let stationsLayerGroup = null;

  // DOM Elements
  const routeSelect = document.getElementById('routeSelect');
  const dirBackBtn = document.getElementById('dirBackBtn');
  const dirGoBtn = document.getElementById('dirGoBtn');
  const vehicleCountEl = document.getElementById('vehicleCount');
  const countdownEl = document.getElementById('countdown');
  const vehicleListEl = document.getElementById('vehicleList');
  const listCounterBadge = document.getElementById('listCounterBadge');
  const stationFocusCardEl = document.getElementById('stationFocusCard');
  const presentationModeEl = document.getElementById('presentationMode');
  let presentationMode = 'debug';

  // Sidebar Tabs (Lỗi 2)
  const tabBtnStation = document.getElementById('tabBtnStation');
  const tabBtnFleet = document.getElementById('tabBtnFleet');
  const tabPaneStation = document.getElementById('tabPaneStation');
  const tabPaneFleet = document.getElementById('tabPaneFleet');
  const stationEmptyGuide = document.getElementById('stationEmptyGuide');

  // Single boundary for provider text interpolated into static HTML templates.
  function escapeHtml(value) {
    const textNode = document.createElement('span');
    textNode.textContent = value == null ? '' : String(value);
    return textNode.innerHTML;
  }

  // Real-time ETA Ticker Cache (Lỗi 3)
  let latestPinnedEtaData = null;
  let latestPopupEtaData = null;
  let latestPopupStationOrder = null;
  let latestPopupContainer = null;
  let latestPopupStationRef = null;

  // Initialize Leaflet Map
  const map = L.map('map', {
    center: HANOI_COORDS,
    zoom: DEFAULT_ZOOM,
    zoomControl: true
  });

  // Base Layer: Esri World Imagery (Thuần ảnh vệ tinh Esri mặc định và duy nhất)
  const esriSatelliteLayer = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {
      maxZoom: 19,
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
    }
  ).addTo(map);

  // Overlay Layer: Esri Reference (Nhãn địa danh & đường xá trên nền vệ tinh)
  const esriReferenceLayer = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
    {
      maxZoom: 19
    }
  ).addTo(map);

  // Layer Switcher Control: Bật/tắt lớp nhãn địa danh
  const overlayMaps = {
    'Nhãn địa danh & đường': esriReferenceLayer
  };
  L.control.layers(null, overlayMaps, { position: 'topright' }).addTo(map);

  // Khởi tạo nhóm lớp trạm dừng
  stationsLayerGroup = L.layerGroup().addTo(map);

  map.on('popupclose', () => {
    latestPopupStationRef = null;
    latestPopupStationOrder = null;
    latestPopupContainer = null;
    latestPopupEtaData = null;
    syncStationFastPolling(latestPinnedEtaData);
  });

  /**
   * Tạo HTML Icon xe buýt kèm góc xoay SVG
   */
  function createBusIcon(deg) {
    const rotation = (typeof deg === 'number' && !isNaN(deg)) ? deg : 0;
    return L.divIcon({
      className: 'bus-marker-icon-wrapper',
      html: `<img src="/static/bus_icon.svg" class="bus-marker-img" style="transform: rotate(${rotation}deg);" alt="bus"/>`,
      iconSize: [40, 40],
      iconAnchor: [20, 20],
      popupAnchor: [0, -18]
    });
  }

  /**
   * Các helper định dạng hiển thị 1 thông tin / 1 dòng & thời điểm đến (time now + ETA)
   */
  function formatTelemetryLabel(bus) {
    return bus && bus.telemetry_source === 'timbus' ? 'TIMBUS 5s' : 'BUSMAP 15s';
  }

  function formatRemainingDuration(secVal) {
    const s = Math.max(0, Math.round(Number(secVal || 0)));
    if (s < 60) return `${s} giây`;
    const mins = Math.floor(s / 60);
    const rem = s % 60;
    return rem > 0 ? `${mins} phút ${rem}s` : `${mins} phút`;
  }

  function formatEpochClock(epochMs) {
    if (isNaN(epochMs)) return '--:--:--';
    const d = new Date(epochMs);
    const pad = n => String(n).padStart(2, '0');
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function formatEstimatedArrival(bus) {
    if (bus && bus.estimated_arrival_time) {
      return bus.estimated_arrival_time;
    }
    let epochMs = NaN;
    if (bus && typeof bus.arrival_time_epoch === 'number') {
      epochMs = bus.arrival_time_epoch * 1000;
    } else if (bus && typeof bus.eta_seconds === 'number') {
      epochMs = Date.now() + bus.eta_seconds * 1000;
    }
    return formatEpochClock(epochMs);
  }

  function getOptimisticSeconds(bus) {
    if (bus && typeof bus.optimistic_eta_seconds === 'number') {
      return bus.optimistic_eta_seconds;
    }
    if (bus && bus.safe_window && typeof bus.safe_window.optimistic_eta_seconds === 'number') {
      return bus.safe_window.optimistic_eta_seconds;
    }
    const p50 = Number((bus && bus.eta_seconds) || 0);
    const buf = Number((bus && bus.safe_window && bus.safe_window.buffer_seconds) || 0);
    return Math.max(0, p50 - buf);
  }

  function formatOptimisticArrival(bus) {
    if (bus && bus.optimistic_arrival_time) {
      return bus.optimistic_arrival_time;
    }
    if (bus && bus.safe_window && bus.safe_window.optimistic_arrival_time) {
      return bus.safe_window.optimistic_arrival_time;
    }
    const optSec = getOptimisticSeconds(bus);
    return formatEpochClock(Date.now() + optSec * 1000);
  }

  function formatTrafficMeta(status) {
    if (status === 'THONG_THOANG') return { label: 'Thông thoáng', cls: 'traffic-ok' };
    if (status === 'UN_TAC') return { label: 'Ùn tắc', cls: 'traffic-jam' };
    return { label: 'Bình thường', cls: 'traffic-normal' };
  }

  function formatDistanceText(distM) {
    const m = Math.round(Number(distM || 0));
    if (m >= 1000) return `${(m / 1000).toFixed(2)} km (${m} m)`;
    return `${m} m`;
  }

  function renderKvRowsHtml(rows, dividerBeforeIndex = -1) {
    return rows.map((r, idx) => {
      const dividerCls = (dividerBeforeIndex >= 0 && idx === dividerBeforeIndex) ? ' kv-debug-divider' : '';
      const valCls = r.valClass ? ` ${r.valClass}` : '';
      const idAttr = r.valId ? ` id="${escapeHtml(r.valId)}"` : '';
      return `<div class="kv-row${dividerCls}"><span class="kv-label">${escapeHtml(r.label)}</span><span class="kv-val${valCls}"${idAttr}>${r.valHtml}</span></div>`;
    }).join('');
  }

  /**
   * Xây dựng nội dung Popup hiển thị thông tin xe (mỗi thông tin 1 dòng)
   */
  function buildPopupContent(vehicle) {
    const speed = (typeof vehicle.speed_kmh === 'number') ? vehicle.speed_kmh.toFixed(1) : '0.0';
    const timeFormatted = vehicle.updated_at ? vehicle.updated_at.replace('T', ' ').substring(11, 19) : '--:--:--';
    const stationInfo = vehicle.next_station_id ? `Trạm #${vehicle.next_station_id}` : 'Đang di chuyển';
    let ageStr = '';
    if (vehicle.updated_at) {
      try {
        const pingTime = new Date(vehicle.updated_at).getTime();
        if (!isNaN(pingTime)) {
          const ageSec = Math.max(0, Math.round((Date.now() - pingTime) / 1000));
          ageStr = ` (${ageSec}s trước)`;
        }
      } catch (e) {}
    }

    const debug = presentationMode === 'debug';
    const rows = [
      { label: 'Vận tốc ổn định:', valHtml: `${escapeHtml(speed)} km/h` },
      { label: 'Hướng đi:', valHtml: `${Math.round(vehicle.deg || 0)}&deg;` },
      { label: 'Trạm tiếp theo:', valHtml: escapeHtml(stationInfo) },
      { label: 'Cập nhật GPS:', valHtml: `${escapeHtml(timeFormatted)}${escapeHtml(ageStr)}` },
      { label: 'Tọa độ:', valHtml: `${Number(vehicle.lat).toFixed(5)}, ${Number(vehicle.lng).toFixed(5)}` }
    ];
    let dividerIdx = -1;
    if (debug) {
      dividerIdx = rows.length;
      rows.push({ label: 'Nguồn GPS:', valHtml: escapeHtml(formatTelemetryLabel(vehicle)) });
      if (typeof vehicle.raw_speed_kmh === 'number') {
        const winText = (typeof vehicle.speed_window_sec === 'number') ? ` (&Delta;t=${Math.round(vehicle.speed_window_sec)}s)` : '';
        rows.push({ label: 'Vận tốc hộp đen:', valHtml: `${escapeHtml(vehicle.raw_speed_kmh.toFixed(1))} km/h${winText}` });
      }
    }

    return `
      <div class="bus-popup">
        <div class="bus-popup-header">
          <span class="bus-popup-plate">${escapeHtml(vehicle.plate)}</span>
          <span class="bus-popup-speed">${speed} km/h</span>
        </div>
        <div class="kv-list">${renderKvRowsHtml(rows, dividerIdx)}</div>
      </div>
    `;
  }

  /**
   * Cập nhật danh sách thẻ xe ở Sidebar
   */
  function renderVehicleList(vehicles) {
    if (!vehicles || vehicles.length === 0) {
      vehicleListEl.innerHTML = '<div class="empty-state">Hiện không có xe hoạt động trên chiều này.</div>';
      listCounterBadge.textContent = '0 xe';
      return;
    }

    listCounterBadge.textContent = `${vehicles.length} xe`;
    vehicleListEl.innerHTML = '';
    const debug = presentationMode === 'debug';

    vehicles.forEach(v => {
      const card = document.createElement('div');
      card.className = 'vehicle-card';
      const speed = (typeof v.speed_kmh === 'number') ? v.speed_kmh.toFixed(1) : '0.0';
      const timeStr = v.updated_at ? v.updated_at.substring(11, 19) : '--:--:--';
      const debugLine = debug
        ? `<div class="vehicle-card-bottom"><span>Nguồn: ${escapeHtml(formatTelemetryLabel(v))}</span><span>${typeof v.raw_speed_kmh === 'number' ? `Gốc: ${v.raw_speed_kmh.toFixed(0)} km/h` : ''}</span></div>`
        : '';

      card.innerHTML = `
        <div class="vehicle-card-top">
          <span class="vehicle-plate">${escapeHtml(v.plate)}</span>
          <span class="vehicle-speed">${speed} km/h</span>
        </div>
        <div class="vehicle-card-bottom">
          <span>${escapeHtml(v.next_station_id ? 'Tới trạm #' + v.next_station_id : 'Trên đường')}</span>
          <span>${escapeHtml(timeStr)}</span>
        </div>
        ${debugLine}
      `;

      card.addEventListener('click', () => {
        const marker = activeMarkers.get(v.id);
        if (marker) {
          map.panTo([v.lat, v.lng], { animate: true, duration: 0.5 });
          marker.openPopup();
        }
      });

      vehicleListEl.appendChild(card);
    });
  }

  /**
   * Cập nhật Marker rời rạc (Discrete Stepped Update)
   * Cập nhật trực tiếp tọa độ GPS, không loop animation
   */
  function updateMarkers(vehicles) {
    const currentIds = new Set();
    const bounds = [];

    vehicles.forEach(v => {
      currentIds.add(v.id);
      bounds.push([v.lat, v.lng]);

      const existingMarker = activeMarkers.get(v.id);
      if (existingMarker) {
        // Cập nhật vị trí trực tiếp (Giật cục rời rạc chính xác theo GPS mẫu)
        existingMarker.setLatLng([v.lat, v.lng]);
        existingMarker.setIcon(createBusIcon(v.deg));
        existingMarker.setPopupContent(buildPopupContent(v));
      } else {
        // Tạo marker mới
        const marker = L.marker([v.lat, v.lng], {
          icon: createBusIcon(v.deg)
        });
        marker.bindPopup(buildPopupContent(v));
        marker.addTo(map);
        activeMarkers.set(v.id, marker);
      }
    });

    // Xóa bỏ các xe không còn xuất hiện trong phản hồi mới
    for (const [id, marker] of activeMarkers.entries()) {
      if (!currentIds.has(id)) {
        marker.remove();
        activeMarkers.delete(id);
      }
    }

    // Tự động căn chỉnh khung hình nếu có xe và chưa có hình tuyến
    if (bounds.length > 0 && !map._hasFittedInitialBounds && !routePolyline) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
      map._hasFittedInitialBounds = true;
    }
  }

  /**
   * Tạo HTML Icon huy hiệu tròn đánh số trạm dừng (SPEC-05)
   */
  function createStationBadgeIcon(orderIndex, direction) {
    const isGo = (direction === 0 || direction === 'go');
    const badgeClass = isGo ? 'station-badge-go' : 'station-badge-re';
    const badgeNumber = orderIndex + 1;

    return L.divIcon({
      className: 'station-badge-icon-wrapper',
      html: `<div class="station-badge ${badgeClass}">${badgeNumber}</div>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
      popupAnchor: [0, -12]
    });
  }

  /**
   * Xây dựng nội dung Popup hiển thị trạm dừng chuẩn mực
   */
  function buildStationPopupContent(station, index, totalStations, direction) {
    const isGo = (direction === 0 || direction === 'go');
    const dirLabel = isGo ? 'Chiều đi' : 'Chiều về';
    const dirBadgeClass = isGo ? 'badge-go' : 'badge-re';
    const distKm = (station.cum_distance_m / 1000.0).toFixed(2);
    const addressStr = station.address ? station.address : 'Đang cập nhật';
    const latStr = (typeof station.lat === 'number') ? station.lat.toFixed(6) : station.lat;
    const lonStr = (typeof station.lon === 'number') ? station.lon.toFixed(6) : station.lon;

    return `
      <div class="station-popup">
        <div class="station-popup-header">
          <div class="station-popup-title">${escapeHtml(station.station_name)}</div>
          <span class="station-dir-badge ${dirBadgeClass}">${dirLabel}</span>
        </div>
        <div class="station-popup-order">Trạm số: <strong>${index + 1}</strong> / ${totalStations}</div>
        <div class="station-popup-divider"></div>
        <div class="station-popup-row">
          <span class="popup-label">Mã trạm:</span>
          <span class="popup-value">#${escapeHtml(station.station_id)}</span>
        </div>
        <div class="station-popup-row">
          <span class="popup-label">Lý trình từ bến:</span>
          <span class="popup-value">${distKm} km</span>
        </div>
        <div class="station-popup-row">
          <span class="popup-label">Địa chỉ:</span>
          <span class="popup-value">${escapeHtml(addressStr)}</span>
        </div>
        <div class="station-popup-row">
          <span class="popup-label">Tọa độ WGS84:</span>
          <span class="popup-value">${escapeHtml(latStr)}, ${escapeHtml(lonStr)}</span>
        </div>
        <div class="popup-eta-section" id="popupEtaSection_${index}">
          <div class="popup-eta-loading">Đang tải dự báo thời gian xe đến...</div>
        </div>
        <button type="button" class="btn-pin-station" id="btnPinStation_${index}">📌 Ghim theo dõi trạm</button>
      </div>
    `;
  }

  /**
   * Quản lý chuyển đổi Tabs Sidebar (Tab 1: Trạm theo dõi, Tab 2: Đoàn xe tuyến)
   */
  function switchTab(tabName) {
    if (tabName === 'station') {
      if (tabBtnStation) tabBtnStation.classList.add('active');
      if (tabBtnFleet) tabBtnFleet.classList.remove('active');
      if (tabPaneStation) tabPaneStation.style.display = 'flex';
      if (tabPaneFleet) tabPaneFleet.style.display = 'none';
    } else {
      if (tabBtnFleet) tabBtnFleet.classList.add('active');
      if (tabBtnStation) tabBtnStation.classList.remove('active');
      if (tabPaneFleet) tabPaneFleet.style.display = 'flex';
      if (tabPaneStation) tabPaneStation.style.display = 'none';
    }
  }

  function setupSidebarTabs() {
    if (tabBtnStation) {
      tabBtnStation.addEventListener('click', () => switchTab('station'));
    }
    if (tabBtnFleet) {
      tabBtnFleet.addEventListener('click', () => switchTab('fleet'));
    }
  }

  /**
   * Cập nhật độ tươi gói tin GPS (tuổi ping) hiển thị trên UI theo thời gian thực
   */
  function updateLiveGpsAge() {
    const nowSec = Date.now() / 1000.0;

    // 1. Cập nhật thẻ trạm đang ghim
    if (latestPinnedEtaData && latestPinnedEtaData.buses && latestPinnedEtaData.buses.length > 0) {
      const b0 = latestPinnedEtaData.buses[0];
      const focusAgeEl = document.getElementById('focusEtaAge');
      if (focusAgeEl && b0.ping_time) {
        const pingEpoch = new Date(b0.ping_time).getTime() / 1000.0;
        if (!isNaN(pingEpoch)) {
          const age = Math.max(0, Math.round(nowSec - pingEpoch));
          const hm = escapeHtml(b0.ping_time.substring(11, 19));
          focusAgeEl.textContent = `${age}s trước (${hm})`;
        }
      }
    }

    // 2. Cập nhật Popup trạm đang mở trên bản đồ
    if (latestPopupEtaData && latestPopupEtaData.buses && latestPopupEtaData.buses.length > 0) {
      const pb0 = latestPopupEtaData.buses[0];
      const popupAgeEl = document.getElementById('popupEtaAge');
      if (popupAgeEl && pb0.ping_time) {
        const pingEpoch = new Date(pb0.ping_time).getTime() / 1000.0;
        if (!isNaN(pingEpoch)) {
          const age = Math.max(0, Math.round(nowSec - pingEpoch));
          const hm = escapeHtml(pb0.ping_time.substring(11, 19));
          popupAgeEl.textContent = `${age}s trước (${hm})`;
        }
      }
    }
  }

  /**
   * Quản lý Ghim trạm theo dõi vào thanh Sidebar (SPEC-08)
   */
  function pinStation(station, index, totalStations) {
    pinnedStation = {
      routeId: currentRouteId,
      direction: currentDirection,
      stationOrder: station.station_order,
      stationName: station.station_name,
      stationIndex: index,
      totalStations: totalStations
    };
    switchTab('station');
    if (stationFocusCardEl) {
      stationFocusCardEl.style.display = 'flex';
      if (stationEmptyGuide) stationEmptyGuide.style.display = 'none';
      updateStationFocusCard();
    }
  }

  async function refreshOpenPopupEta() {
    if (!latestPopupStationRef || !latestPopupContainer || !latestPopupContainer.isConnected) return;
    const ref = latestPopupStationRef;
    const container = latestPopupContainer;
    const requestId = ++popupRequestId;
    if (ref.routeId !== currentRouteId || ref.direction !== currentDirection) return;
    try {
      const res = await fetch(`/api/station-eta?route_id=${ref.routeId}&direction=${ref.direction}&station_order=${ref.stationOrder}`);
      if (!res.ok) return;
      const data = await res.json();
      if (requestId !== popupRequestId || latestPopupStationRef !== ref ||
          latestPopupContainer !== container || !container.isConnected) return;
      latestPopupEtaData = data;
      renderStationPopupEta(latestPopupContainer, data);
    } catch (err) {
      console.error('[Station Popup ETA] Lỗi cập nhật ETA popup:', err);
    }
  }

  function syncVehiclePolling(supportsFast, serverIntervalSec) {
    const targetMs = (supportsFast || serverIntervalSec === 5) ? TIMBUS_POLL_MS : POLL_INTERVAL_MS;
    if (targetMs !== activePollIntervalMs) {
      activePollIntervalMs = targetMs;
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = setInterval(pollVehicles, activePollIntervalMs);
      }
      const targetSec = Math.floor(activePollIntervalMs / 1000);
      if (countdownSeconds > targetSec || countdownSeconds <= 0) {
        countdownSeconds = targetSec;
        if (countdownEl) countdownEl.textContent = `${countdownSeconds}s`;
      }
    }
  }

  function syncStationFastPolling(etaData) {
    if (!etaData) return;
    if (etaData.timbus_supported || etaData.poll_interval_sec === 5) {
      syncVehiclePolling(true, 5);
    }
  }

  function unpinStation() {
    pinnedStation = null;
    latestPinnedEtaData = null;
    if (stationFocusCardEl) {
      stationFocusCardEl.style.display = 'none';
      stationFocusCardEl.innerHTML = '';
    }
    if (stationEmptyGuide) {
      stationEmptyGuide.style.display = 'flex';
    }
  }

  async function updateStationFocusCard() {
    if (!pinnedStation || !stationFocusCardEl) return;
    if (pinnedStation.routeId !== currentRouteId || pinnedStation.direction !== currentDirection) {
      return;
    }

    const ref = pinnedStation;
    const requestId = ++focusRequestId;
    try {
      const res = await fetch(`/api/station-eta?route_id=${ref.routeId}&direction=${ref.direction}&station_order=${ref.stationOrder}`);
      if (!res.ok) return;
      const data = await res.json();
      if (pinnedStation !== ref || requestId !== focusRequestId) return;
      renderStationFocusCard(data);
      syncStationFastPolling(data);
    } catch (err) {
      console.error('[Station ETA] Lỗi cập nhật thẻ trạm ghim:', err);
    }
  }

  function buildEtaInfoRows(bus, debug, ageElementId) {
    const sw = bus.safe_window || {};
    const p10Sec = typeof sw.p10_seconds === 'number' ? sw.p10_seconds : (bus.eta_seconds || 0);
    const p50Sec = typeof sw.p50_seconds === 'number' ? sw.p50_seconds : (bus.eta_seconds || 0);
    const p90Sec = typeof sw.p90_seconds === 'number' ? sw.p90_seconds : (bus.eta_seconds || 0);
    const p10m = sw.p10_minutes !== undefined ? sw.p10_minutes : Math.ceil(p10Sec / 60.0);
    const p90m = sw.p90_minutes !== undefined ? sw.p90_minutes : Math.ceil(p90Sec / 60.0);
    const delaySec = typeof sw.delay_seconds === 'number' ? sw.delay_seconds : 0;
    const bufSec = typeof sw.buffer_seconds === 'number' ? sw.buffer_seconds : 0;
    const consSec = typeof sw.conservative_eta_seconds === 'number' ? sw.conservative_eta_seconds : (p50Sec + bufSec);
    const traffic = formatTrafficMeta(bus.traffic_status);
    const arrivalClock = formatEstimatedArrival(bus);
    const p50Remain = formatRemainingDuration(bus.eta_seconds);
    const optSec = getOptimisticSeconds(bus);
    const optRemain = formatRemainingDuration(optSec);
    const optClock = formatOptimisticArrival(bus);

    const rows = [
      {
        label: 'Dự kiến (P50):',
        valHtml: `${escapeHtml(p50Remain)} &bull; <span class="arrival-highlight">${escapeHtml(arrivalClock)}</span>`
      },
      {
        label: 'Lạc quan (-Δ đệm):',
        valHtml: `${escapeHtml(optRemain)} &bull; <span class="optimistic-highlight">${escapeHtml(optClock)}</span>`
      },
      { label: 'Khoảng an toàn:', valHtml: `${p10m} &ndash; ${p90m} phút` },
      { label: 'Quãng đường còn lại:', valHtml: escapeHtml(formatDistanceText(bus.distance_to_station_m)) },
      { label: 'Số trạm còn lại:', valHtml: `${escapeHtml(bus.stops_remaining)} trạm` },
      { label: 'Vận tốc ổn định:', valHtml: `${Number(bus.speed_kmh || 0).toFixed(1)} km/h` },
      { label: 'Tình trạng giao thông:', valHtml: escapeHtml(traffic.label), valClass: traffic.cls }
    ];

    let dividerIdx = -1;
    if (debug) {
      dividerIdx = rows.length;
      const ageSec = typeof bus.ping_age_seconds === 'number' ? Math.round(bus.ping_age_seconds) : 0;
      const pingHm = bus.ping_time ? bus.ping_time.substring(11, 19) : '--:--:--';
      const rawSpd = typeof bus.raw_speed_kmh === 'number' ? bus.raw_speed_kmh.toFixed(1) : Number(bus.speed_kmh || 0).toFixed(1);
      const winText = typeof bus.speed_window_sec === 'number' ? `${Math.round(bus.speed_window_sec)}s` : '--';

      rows.push({ label: 'Nguồn GPS:', valHtml: escapeHtml(formatTelemetryLabel(bus)) });
      rows.push({ label: 'Tuổi gói GPS:', valHtml: `${ageSec}s trước (${escapeHtml(pingHm)})`, valId: ageElementId });
      rows.push({ label: 'Hộp đen gốc / Δt:', valHtml: `${escapeHtml(rawSpd)} km/h (&Delta;t=${escapeHtml(winText)})` });
      rows.push({ label: 'Nguồn dự báo ETA:', valHtml: escapeHtml(bus.prediction_source) });
      rows.push({
        label: 'Độ trễ thực tế:',
        valHtml: `+${delaySec}s (${sw.is_delayed ? 'Cảnh báo trễ' : 'Đúng lịch'})`
      });
      rows.push({
        label: 'P10 / P50 / P90:',
        valHtml: `${p10Sec}s / ${p50Sec}s / ${p90Sec}s`
      });
      rows.push({
        label: 'Đệm (B) / Lạc quan / Bảo thủ:',
        valHtml: `-${bufSec}s &rarr; ${Math.round(optSec)}s | +${bufSec}s &rarr; ${consSec}s`
      });
    }
    return { rows, dividerIdx };
  }

  function renderStationFocusCard(data) {
    latestPinnedEtaData = data;
    if (!pinnedStation || !stationFocusCardEl) return;
    const target = data.target_station || {};
    const stName = target.station_name || pinnedStation.stationName;
    const stOrder = target.station_order !== undefined ? target.station_order + 1 : pinnedStation.stationIndex + 1;
    const debug = presentationMode === 'debug';

    if (stationEmptyGuide) {
      stationEmptyGuide.style.display = 'none';
    }
    stationFocusCardEl.style.display = 'flex';

    let bodyHtml = '';
    if (data.buses && data.buses.length > 0) {
      const b0 = data.buses[0];
      const info0 = buildEtaInfoRows(b0, debug, 'focusEtaAge');

      // Mini Timeline (tối đa 3 xe đang tiếp cận)
      let timelineStepsHtml = '';
      data.buses.slice(0, 3).forEach((bx, idx) => {
        const arrBx = formatEstimatedArrival(bx);
        const optBx = formatOptimisticArrival(bx);
        const optRemBx = formatRemainingDuration(getOptimisticSeconds(bx));
        const speedBx = Number(bx.speed_kmh || 0).toFixed(1);
        const distBx = formatDistanceText(bx.distance_to_station_m);
        timelineStepsHtml += `
          <div class="timeline-step">
            <div class="timeline-dot">${idx + 1}</div>
            <div class="timeline-body">
              <div class="timeline-main-text">${escapeHtml(bx.plate)} &bull; <span id="timelineStep${idx}Countdown">${escapeHtml(bx.display_text)}</span></div>
              <div class="timeline-sub-text">Dự kiến (P50): <strong style="color:#fbbf24;">${escapeHtml(arrBx)}</strong> &bull; Lạc quan: <strong class="optimistic-highlight">${escapeHtml(optRemBx)} (${escapeHtml(optBx)})</strong></div>
              <div class="timeline-sub-text">Còn ${escapeHtml(bx.stops_remaining)} trạm &bull; ${escapeHtml(distBx)} &bull; ${escapeHtml(speedBx)} km/h${debug ? ` &bull; ${escapeHtml(formatTelemetryLabel(bx))}` : ''}</div>
            </div>
          </div>
        `;
      });

      timelineStepsHtml += `
        <div class="timeline-step">
          <div class="timeline-dot dest-dot">🚏</div>
          <div class="timeline-body">
            <div class="timeline-main-text">[#${escapeHtml(stOrder)}] ${escapeHtml(stName)}</div>
            <div class="timeline-sub-text">Trạm dừng theo dõi</div>
          </div>
        </div>
      `;

      bodyHtml = `
        <div class="focus-eta-box">
          <div class="focus-eta-main">
            <span class="focus-eta-plate">${escapeHtml(b0.plate)}</span>
            <span class="focus-eta-val" id="focusEtaCountdown">${escapeHtml(b0.display_text)}</span>
          </div>
          <div class="kv-list">${renderKvRowsHtml(info0.rows, info0.dividerIdx)}</div>
        </div>

        <div class="mini-timeline">
          <div class="timeline-title">Tiến trình tiếp cận trạm</div>
          ${timelineStepsHtml}
        </div>
      `;
    } else {
      bodyHtml = `<div class="focus-empty">${escapeHtml(data.message || 'Không có dữ liệu ETA cho trạm này.')}</div>`;
    }

    stationFocusCardEl.innerHTML = `
      <div class="focus-card-header">
        <span class="focus-tag">📌 Trạm theo dõi</span>
        <button type="button" class="btn-unpin" id="btnUnpinStation">✕ Bỏ ghim</button>
      </div>
      <div class="focus-station-name">[#${escapeHtml(stOrder)}] ${escapeHtml(stName)}</div>
      ${bodyHtml}
    `;

    const unpinBtn = document.getElementById('btnUnpinStation');
    if (unpinBtn) {
      unpinBtn.onclick = unpinStation;
    }
  }

  function renderStationPopupEta(container, data) {
    const debug = presentationMode === 'debug';
    if (!data.buses || data.buses.length === 0) {
      container.innerHTML = `<div class="popup-eta-loading">${escapeHtml(data.message || 'Không có dữ liệu ETA cho trạm này.')}${debug ? '<br><small>Lý do empty state được trả bởi dịch vụ ETA.</small>' : ''}</div>`;
      return;
    }
    const b0 = data.buses[0];
    const headerRows = [
      { label: 'Biển số xe:', valHtml: `<strong>${escapeHtml(b0.plate)}</strong>` }
    ];
    const info0 = buildEtaInfoRows(b0, debug, 'popupEtaAge');
    const allRows = headerRows.concat(info0.rows);
    const divIdx = info0.dividerIdx >= 0 ? info0.dividerIdx + headerRows.length : -1;

    let nextBusHtml = '';
    if (data.buses.length >= 2) {
      const b1 = data.buses[1];
      const nextRows = [
        { label: 'Chuyến kế tiếp:', valHtml: `<strong>${escapeHtml(b1.plate)}</strong> &bull; ${escapeHtml(b1.display_text)}` },
        { label: 'Dự kiến (P50):', valHtml: `${escapeHtml(formatRemainingDuration(b1.eta_seconds))} &bull; <span class="arrival-highlight">${escapeHtml(formatEstimatedArrival(b1))}</span>` },
        { label: 'Lạc quan (-&Delta; đệm):', valHtml: `${escapeHtml(formatRemainingDuration(getOptimisticSeconds(b1)))} &bull; <span class="optimistic-highlight">${escapeHtml(formatOptimisticArrival(b1))}</span>` },
        { label: 'Khoảng cách & trạm:', valHtml: `Còn ${escapeHtml(b1.stops_remaining)} trạm &bull; ${escapeHtml(formatDistanceText(b1.distance_to_station_m))}` }
      ];
      if (debug) {
        nextRows.push({
          label: 'Nguồn & tuổi GPS:',
          valHtml: `${escapeHtml(formatTelemetryLabel(b1))} (${Math.round(b1.ping_age_seconds || 0)}s trước)`
        });
      }
      nextBusHtml = `<div class="popup-next-bus"><div class="kv-list">${renderKvRowsHtml(nextRows)}</div></div>`;
    }

    container.innerHTML = `
      <div class="popup-eta-box">
        <div class="popup-eta-header">
          <span class="popup-eta-badge">Xe gần nhất đang đến</span>
          <span class="popup-eta-time" id="popupEtaCountdown">${escapeHtml(b0.display_text)}</span>
        </div>
        <div class="kv-list">${renderKvRowsHtml(allRows, divIdx)}</div>
        ${nextBusHtml}
      </div>
    `;
  }

  async function loadStationPopupEta(station, index, totalStations, direction) {
    const container = document.getElementById(`popupEtaSection_${index}`);
    const pinBtn = document.getElementById(`btnPinStation_${index}`);

    if (pinBtn) {
      pinBtn.onclick = () => {
        pinStation(station, index, totalStations);
        pinBtn.textContent = '✓ Đã ghim vào thanh bên';
      };
    }

    if (!container) return;

    const ref = { routeId: currentRouteId, direction, stationOrder: station.station_order };
    const requestId = ++popupRequestId;
    latestPopupStationRef = ref;
    latestPopupContainer = container;
    latestPopupEtaData = null;
    const isCurrent = () => requestId === popupRequestId && latestPopupStationRef === ref &&
      latestPopupContainer === container && container.isConnected &&
      ref.routeId === currentRouteId && direction === currentDirection;

    try {
      const res = await fetch(`/api/station-eta?route_id=${ref.routeId}&direction=${direction}&station_order=${station.station_order}`);
      if (!res.ok) {
        if (!isCurrent()) return;
        container.innerHTML = '<div class="popup-eta-loading">Không có dữ liệu ETA trạm này</div>';
        return;
      }
      const data = await res.json();
      if (!isCurrent()) return;
      latestPopupEtaData = data;
      latestPopupStationOrder = station.station_order;
      latestPopupContainer = container;
      renderStationPopupEta(container, data);
      syncStationFastPolling(data);
      return;
    } catch (err) {
      if (!isCurrent()) return;
      console.error('[Station Popup ETA] Lỗi nạp ETA:', err);
      container.innerHTML = '<div class="popup-eta-loading">Lỗi kết nối khi tính ETA</div>';
    }
  }

  /**
   * Tải và vẽ tim tuyến (Route Shape Polyline)
   */
  async function fetchRouteShape(routeId, direction) {
    if (!routeId) return;
    const generation = routeGeneration;
    try {
      const res = await fetch(`/api/route-shape?route_id=${routeId}&direction=${direction}`);
      if (!res.ok) {
        console.warn(`[Route Shape] HTTP ${res.status}`);
        return;
      }
      const data = await res.json();
      if (generation !== routeGeneration || routeId !== currentRouteId || direction !== currentDirection) return;
      const coords = data.coordinates;
      if (!coords || coords.length === 0) return;

      if (routePolyline) {
        routePolyline.remove();
        routePolyline = null;
      }

      const isGo = (direction === 0 || direction === 'go');
      const routeColor = isGo ? '#10b981' : '#3b82f6';

      routePolyline = L.polyline(coords, {
        color: routeColor,
        weight: 4,
        opacity: 0.9,
        lineJoin: 'round',
        smoothFactor: 1.0
      }).addTo(map);

      // Tự động căn khung hình theo tim tuyến
      map.fitBounds(routePolyline.getBounds(), {
        padding: [40, 40],
        maxZoom: 16,
        animate: true,
        duration: 0.8
      });
    } catch (err) {
      console.error('[Route Shape] Lỗi nạp hình học tuyến:', err);
    }
  }

  /**
   * Tải và vẽ các trạm dừng đánh số (Route Stations)
   */
  async function fetchRouteStations(routeId, direction) {
    if (!routeId) return;
    const generation = routeGeneration;
    try {
      const res = await fetch(`/api/route-stations?route_id=${routeId}&direction=${direction}`);
      if (!res.ok) {
        console.warn(`[Route Stations] HTTP ${res.status}`);
        return;
      }
      const data = await res.json();
      if (generation !== routeGeneration || routeId !== currentRouteId || direction !== currentDirection) return;
      const stations = data.stations;
      if (!stations || stations.length === 0) return;

      stationsLayerGroup.clearLayers();

      const total = stations.length;
      stations.forEach((st, idx) => {
        const marker = L.marker([st.lat, st.lon], {
          icon: createStationBadgeIcon(idx, direction),
          zIndexOffset: 500
        });
        marker.bindPopup(buildStationPopupContent(st, idx, total, direction));
        marker.on('popupopen', () => {
          loadStationPopupEta(st, idx, total, direction);
        });
        stationsLayerGroup.addLayer(marker);
      });
    } catch (err) {
      console.error('[Route Stations] Lỗi nạp danh sách trạm dừng:', err);
    }
  }

  /**
   * Truy vấn vị trí xe trực tiếp từ API backend
   */
  async function pollVehicles() {
    if (!currentRouteId || isPolling) return;
    isPolling = true;
    const generation = routeGeneration;
    const routeId = currentRouteId;
    const direction = currentDirection;

    try {
      const response = await fetch(`/api/live-vehicles?route_id=${routeId}&direction=${direction}`);
      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
      }

      const data = await response.json();
      if (generation !== routeGeneration) return;
      const vehicles = data.vehicles || [];
      latestLiveVehicles = vehicles;

      // Tự đồng bộ chu kỳ 5s (TimBus) hoặc 15s (BusMap-only)
      syncVehiclePolling(Boolean(data.timbus_supported), data.poll_interval_sec);

      // Cập nhật UI trạng thái
      vehicleCountEl.textContent = `${vehicles.length} xe hoạt động`;

      // Cập nhật Marker trên bản đồ & Danh sách thẻ ở Sidebar
      updateMarkers(vehicles);
      renderVehicleList(vehicles);

      // Đồng bộ trạm ghim & popup trạm đang mở cùng nhịp poll
      if (pinnedStation && pinnedStation.routeId === currentRouteId && pinnedStation.direction === currentDirection) {
        updateStationFocusCard();
      }
      if (latestPopupStationRef && latestPopupContainer && latestPopupContainer.isConnected) {
        refreshOpenPopupEta();
      }
    } catch (err) {
      if (generation !== routeGeneration) return;
      console.error('[Hanoi Bus Live] Lỗi lấy dữ liệu xe trực tiếp:', err);
      vehicleCountEl.textContent = 'Mất kết nối GPS';
    } finally {
      if (generation === routeGeneration) {
        isPolling = false;
        resetCountdown();
      }
    }
  }

  /**
   * Quản lý đồng hồ đếm ngược chu kỳ làm mới
   */
  function resetCountdown() {
    countdownSeconds = Math.floor(activePollIntervalMs / 1000);
    if (countdownEl) {
      countdownEl.textContent = `${countdownSeconds}s`;
    }
  }

  function startCountdownTicker() {
    if (countdownTimer) clearInterval(countdownTimer);
    countdownTimer = setInterval(() => {
      countdownSeconds = Math.max(0, countdownSeconds - 1);
      if (countdownEl) {
        countdownEl.textContent = `${countdownSeconds}s`;
      }
      updateLiveGpsAge();
    }, 1000);
  }

  /**
   * Bắt đầu chu kỳ Polling (5s cho tuyến TimBus sạch, 15s cho tuyến BusMap-only)
   */
  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    activePollIntervalMs = routeTimbusMap.get(currentRouteId) ? TIMBUS_POLL_MS : POLL_INTERVAL_MS;
    resetCountdown();
    pollVehicles();
    pollTimer = setInterval(pollVehicles, activePollIntervalMs);
  }

  /**
   * Xóa sạch toàn bộ Marker xe hiện có trên bản đồ
   */
  function clearAllMarkers() {
    activeMarkers.forEach(m => m.remove());
    activeMarkers.clear();
    const srcLabel = routeTimbusMap.get(currentRouteId) ? 'TimBus' : 'BusMap';
    vehicleListEl.innerHTML = `<div class="empty-state">Đang tải dữ liệu trực tiếp từ ${srcLabel}...</div>`;
    vehicleCountEl.textContent = '0 xe hoạt động';
    listCounterBadge.textContent = '0 xe';
    map._hasFittedInitialBounds = false;
  }

  /**
   * Xóa sạch các lớp hình học tim tuyến và trạm dừng
   */
  function clearRouteLayers() {
    routeGeneration += 1;
    isPolling = false;
    latestLiveVehicles = [];
    if (routePolyline) {
      routePolyline.remove();
      routePolyline = null;
    }
    if (stationsLayerGroup) {
      stationsLayerGroup.clearLayers();
    }
    latestPopupStationRef = null;
    latestPopupStationOrder = null;
    latestPopupContainer = null;
    latestPopupEtaData = null;
    syncStationFastPolling(null);
  }

  /**
   * Tải danh mục tuyến từ `/api/routes`
   */
  async function loadRoutes() {
    try {
      const res = await fetch('/api/routes');
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const routes = await res.json();

      routeSelect.innerHTML = '';
      if (!routes || routes.length === 0) {
        routeSelect.innerHTML = '<option value="" disabled>Không có dữ liệu tuyến</option>';
        return;
      }

      let defaultOptionIndex = 0;
      routeTimbusMap.clear();
      routes.forEach((r, idx) => {
        routeTimbusMap.set(r.route_id, Boolean(r.timbus_supported));
        const opt = document.createElement('option');
        opt.value = r.route_id;
        opt.textContent = `${r.route_no} - ${r.name}`;
        if (r.route_no === DEFAULT_ROUTE_NO || String(r.route_id) === DEFAULT_ROUTE_NO) {
          defaultOptionIndex = idx;
        }
        routeSelect.appendChild(opt);
      });

      routeSelect.selectedIndex = defaultOptionIndex;
      currentRouteId = parseInt(routeSelect.value, 10);

      // Tải hình tuyến, trạm dừng và bắt đầu chu kỳ lấy dữ liệu xe
      fetchRouteShape(currentRouteId, currentDirection);
      fetchRouteStations(currentRouteId, currentDirection);
      startPolling();
    } catch (err) {
      console.error('[Hanoi Bus Live] Lỗi tải danh mục tuyến:', err);
      routeSelect.innerHTML = '<option value="" disabled>Lỗi tải tuyến</option>';
    }
  }

  /**
   * Xử lý chuyển đổi Chiều hành trình (Đi / Về)
   */
  function setupDirectionButtons() {
    function setDirection(dir) {
      if (currentDirection === dir) return;
      currentDirection = dir;

      if (dir === 0) {
        dirGoBtn.classList.add('active');
        dirBackBtn.classList.remove('active');
      } else {
        dirBackBtn.classList.add('active');
        dirGoBtn.classList.remove('active');
      }

      clearAllMarkers();
      clearRouteLayers();
      unpinStation();
      fetchRouteShape(currentRouteId, currentDirection);
      fetchRouteStations(currentRouteId, currentDirection);
      startPolling();
    }

    dirGoBtn.addEventListener('click', () => setDirection(0));
    dirBackBtn.addEventListener('click', () => setDirection(1));
  }

  /**
   * Xử lý khi người dùng chọn tuyến khác
   */
  function setupRouteSelect() {
    routeSelect.addEventListener('change', () => {
      const selectedId = parseInt(routeSelect.value, 10);
      if (selectedId && selectedId !== currentRouteId) {
        currentRouteId = selectedId;
        clearAllMarkers();
        clearRouteLayers();
        unpinStation();
        fetchRouteShape(currentRouteId, currentDirection);
        fetchRouteStations(currentRouteId, currentDirection);
        startPolling();
      }
    });
  }

  function setupPresentationMode() {
    if (!presentationModeEl) return;
    presentationModeEl.addEventListener('change', () => {
      presentationMode = presentationModeEl.value;
      if (latestPinnedEtaData) renderStationFocusCard(latestPinnedEtaData);
      if (latestPopupContainer && latestPopupEtaData) renderStationPopupEta(latestPopupContainer, latestPopupEtaData);
      if (latestLiveVehicles && latestLiveVehicles.length > 0) {
        renderVehicleList(latestLiveVehicles);
        latestLiveVehicles.forEach(v => {
          const m = activeMarkers.get(v.id);
          if (m) m.setPopupContent(buildPopupContent(v));
        });
      }
    });
  }

  // Khởi chạy ứng dụng
  document.addEventListener('DOMContentLoaded', () => {
    setupSidebarTabs();
    setupDirectionButtons();
    setupRouteSelect();
    setupPresentationMode();
    startCountdownTicker();
    loadRoutes();
  });
})();
