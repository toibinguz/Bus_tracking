/**
 * Hanoi Bus Live - Discrete Stepped Tracking Client
 * 100% Thuan BusMap roi rac - UX truc tiep, khong noi suy
 */

(() => {
  'use strict';

  // Constants
  const POLL_INTERVAL_MS = 15000;
  const HANOI_COORDS = [21.0285, 105.8542];
  const DEFAULT_ZOOM = 13;
  const DEFAULT_ROUTE_NO = '27';
  const COLOR_GO = '#10b981';
  const COLOR_RE = '#3b82f6';

  // State
  let currentRouteId = null;
  let currentDirection = 0; // 0: Chiều đi, 1: Chiều về
  let countdownSeconds = 15;
  let pollTimer = null;
  let countdownTimer = null;
  let isPolling = false;

  // Active markers map: vehicleId -> Leaflet Marker
  const activeMarkers = new Map();

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
   * Xây dựng nội dung Popup hiển thị thông tin xe
   */
  function buildPopupContent(vehicle) {
    const speed = (typeof vehicle.speed_kmh === 'number') ? vehicle.speed_kmh.toFixed(1) : '0.0';
    const timeFormatted = vehicle.updated_at ? vehicle.updated_at.replace('T', ' ').substring(11, 19) : '--:--:--';
    const stationInfo = vehicle.next_station_id ? `Trạm kế: #${vehicle.next_station_id}` : 'Đang di chuyển';
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

    return `
      <div class="bus-popup">
        <div class="bus-popup-header">
          <span class="bus-popup-plate">${escapeHtml(vehicle.plate)}</span>
          <span class="bus-popup-speed">${speed} km/h</span>
        </div>
        <div class="bus-popup-row">
          <span>Hướng đi:</span>
          <span>${Math.round(vehicle.deg || 0)}&deg;</span>
        </div>
        <div class="bus-popup-row">
          <span>Trạm tiếp theo:</span>
          <span>${escapeHtml(stationInfo)}</span>
        </div>
        <div class="bus-popup-row">
          <span>Cập nhật GPS:</span>
          <span>${escapeHtml(timeFormatted)}${ageStr}</span>
        </div>
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

    vehicles.forEach(v => {
      const card = document.createElement('div');
      card.className = 'vehicle-card';
      const speed = (typeof v.speed_kmh === 'number') ? v.speed_kmh.toFixed(1) : '0.0';
      const timeStr = v.updated_at ? v.updated_at.substring(11, 19) : '';

      card.innerHTML = `
        <div class="vehicle-card-top">
          <span class="vehicle-plate">${escapeHtml(v.plate)}</span>
          <span class="vehicle-speed">${speed} km/h</span>
        </div>
        <div class="vehicle-card-bottom">
          <span>${escapeHtml(v.next_station_id ? 'Tới trạm #' + v.next_station_id : 'Trên đường')}</span>
          <span>${escapeHtml(timeStr)}</span>
        </div>
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
          focusAgeEl.textContent = `GPS: ${age}s trước`;
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
          popupAgeEl.textContent = `GPS: ${age}s trước`;
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

    try {
      const res = await fetch(`/api/station-eta?route_id=${pinnedStation.routeId}&direction=${pinnedStation.direction}&station_order=${pinnedStation.stationOrder}`);
      if (!res.ok) return;
      const data = await res.json();
      renderStationFocusCard(data);
    } catch (err) {
      console.error('[Station ETA] Lỗi cập nhật thẻ trạm ghim:', err);
    }
  }

  function renderStationFocusCard(data) {
    latestPinnedEtaData = data;
    if (!pinnedStation || !stationFocusCardEl) return;
    const target = data.target_station || {};
    const stName = target.station_name || pinnedStation.stationName;
    const stOrder = target.station_order !== undefined ? target.station_order + 1 : pinnedStation.stationIndex + 1;

    if (stationEmptyGuide) {
      stationEmptyGuide.style.display = 'none';
    }
    stationFocusCardEl.style.display = 'flex';

    let bodyHtml = '';
    if (data.buses && data.buses.length > 0) {
      const b0 = data.buses[0];
      const p10m = b0.safe_window.p10_minutes !== undefined ? b0.safe_window.p10_minutes : Math.ceil(b0.safe_window.p10_seconds / 60.0);
      const p90m = b0.safe_window.p90_minutes !== undefined ? b0.safe_window.p90_minutes : Math.ceil(b0.safe_window.p90_seconds / 60.0);
      const ageSec = typeof b0.ping_age_seconds === 'number' ? Math.round(b0.ping_age_seconds) : 0;
      const speedKmh = Math.round(b0.speed_kmh);
      const distM = Math.round(b0.distance_to_station_m);

      // Mini Timeline
      let timelineStepsHtml = '';
      timelineStepsHtml += `
        <div class="timeline-step">
          <div class="timeline-dot">1</div>
          <div class="timeline-body">
            <div class="timeline-main-text">${escapeHtml(b0.plate)} &bull; <span id="timelineStep0Countdown">${escapeHtml(b0.display_text)}</span></div>
            <div class="timeline-sub-text">Còn ${escapeHtml(b0.stops_remaining)} trạm${presentationMode === 'debug' ? ` (${distM}m) &bull; ${speedKmh} km/h` : ''}</div>
          </div>
        </div>
      `;

      if (data.buses.length >= 2) {
        const b1 = data.buses[1];
        const speedKmh1 = Math.round(b1.speed_kmh);
        const distM1 = Math.round(b1.distance_to_station_m);

        timelineStepsHtml += `
          <div class="timeline-step">
            <div class="timeline-dot">2</div>
            <div class="timeline-body">
              <div class="timeline-main-text">${escapeHtml(b1.plate)} &bull; <span id="timelineStep1Countdown">${escapeHtml(b1.display_text)}</span></div>
              <div class="timeline-sub-text">Còn ${escapeHtml(b1.stops_remaining)} trạm${presentationMode === 'debug' ? ` (${distM1}m) &bull; ${speedKmh1} km/h` : ''}</div>
            </div>
          </div>
        `;
      }

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
          <div class="focus-eta-sub">
            <span>Còn ${escapeHtml(b0.stops_remaining)} trạm${presentationMode === 'debug' ? ` (${distM}m)` : ''}</span>
            ${presentationMode === 'debug' ? `<span id="focusEtaAge">GPS: ${ageSec}s trước</span>` : ''}
          </div>
          ${presentationMode === 'debug' ? `<div class="focus-eta-sub">
            <span>Cửa sổ an toàn: [${p10m} - ${p90m} phút]</span>
            <span>Vận tốc: ${speedKmh} km/h</span>
          </div><div class="focus-recommend">Nguồn: ${escapeHtml(b0.prediction_source)}; Traffic: ${escapeHtml(b0.traffic_status)}; Delay: ${b0.safe_window.is_delayed ? 'yes' : 'no'} (${b0.safe_window.delay_seconds}s); T50 ${b0.safe_window.p50_seconds}s; B ${b0.safe_window.buffer_seconds}s; Tc ${b0.safe_window.conservative_eta_seconds}s; M ${b0.display_eta_minutes}; Giờ khuyến nghị: ${escapeHtml(b0.safe_window.recommended_arrival_time)}</div>` : ''}
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
    if (!data.buses || data.buses.length === 0) {
      container.innerHTML = `<div class="popup-eta-loading">${escapeHtml(data.message || 'Không có dữ liệu ETA cho trạm này.')}${presentationMode === 'debug' ? '<br><small>Lý do empty state được trả bởi dịch vụ ETA.</small>' : ''}</div>`;
      return;
    }
    const b0 = data.buses[0];
    const debug = presentationMode === 'debug';
    const nextBus = data.buses.length >= 2
      ? `<div class="popup-next-bus">Chuyến kế tiếp: <strong>${escapeHtml(data.buses[1].plate)}</strong> &bull; ${escapeHtml(data.buses[1].display_text)}${debug ? ` (GPS: ${Math.round(data.buses[1].ping_age_seconds || 0)}s trước)` : ''}</div>`
      : '';
    const diagnostics = debug ? `<div class="popup-eta-details"><span>GPS: ${Math.round(b0.ping_age_seconds || 0)}s; ${Math.round(b0.distance_to_station_m)}m; ${Math.round(b0.speed_kmh)} km/h</span><span>Stops: ${escapeHtml(b0.stops_remaining)}</span></div><div class="popup-eta-details"><span>Nguồn: ${escapeHtml(b0.prediction_source)}</span><span>Traffic: ${escapeHtml(b0.traffic_status)}</span></div><div class="popup-eta-details"><span>P10/P50/P90: ${b0.safe_window.p10_seconds}/${b0.safe_window.p50_seconds}/${b0.safe_window.p90_seconds}s</span><span>T50: ${b0.safe_window.p50_seconds}s; B: ${b0.safe_window.buffer_seconds}s</span></div><div class="popup-eta-details"><span>Tc: ${b0.safe_window.conservative_eta_seconds}s; M: ${b0.display_eta_minutes}</span><span>Delay: ${b0.safe_window.is_delayed ? 'yes' : 'no'} (${b0.safe_window.delay_seconds}s)</span></div>` : '';
    container.innerHTML = `<div class="popup-eta-box"><div class="popup-eta-header"><span class="popup-eta-badge">Xe gần nhất đang đến</span><span class="popup-eta-time" id="popupEtaCountdown">${escapeHtml(b0.display_text)}</span></div><div class="popup-eta-details"><span>Biển số: <strong>${escapeHtml(b0.plate)}</strong></span><span>Còn ${escapeHtml(b0.stops_remaining)} trạm</span></div>${diagnostics}${nextBus}</div>`;
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

    try {
      const res = await fetch(`/api/station-eta?route_id=${currentRouteId}&direction=${direction}&station_order=${station.station_order}`);
      if (!res.ok) {
        container.innerHTML = '<div class="popup-eta-loading">Không có dữ liệu ETA trạm này</div>';
        return;
      }
      const data = await res.json();
      latestPopupEtaData = data;
      latestPopupStationOrder = station.station_order;
      latestPopupContainer = container;
      renderStationPopupEta(container, data);
      return;
    } catch (err) {
      console.error('[Station Popup ETA] Lỗi nạp ETA:', err);
      container.innerHTML = '<div class="popup-eta-loading">Lỗi kết nối khi tính ETA</div>';
    }
  }

  /**
   * Tải và vẽ tim tuyến (Route Shape Polyline)
   */
  async function fetchRouteShape(routeId, direction) {
    if (!routeId) return;
    try {
      const res = await fetch(`/api/route-shape?route_id=${routeId}&direction=${direction}`);
      if (!res.ok) {
        console.warn(`[Route Shape] HTTP ${res.status}`);
        return;
      }
      const data = await res.json();
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
    try {
      const res = await fetch(`/api/route-stations?route_id=${routeId}&direction=${direction}`);
      if (!res.ok) {
        console.warn(`[Route Stations] HTTP ${res.status}`);
        return;
      }
      const data = await res.json();
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

    try {
      const response = await fetch(`/api/live-vehicles?route_id=${currentRouteId}&direction=${currentDirection}`);
      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
      }

      const data = await response.json();
      const vehicles = data.vehicles || [];

      // Cập nhật UI trạng thái
      vehicleCountEl.textContent = `${vehicles.length} xe hoạt động`;

      // Cập nhật Marker trên bản đồ & Danh sách thẻ ở Sidebar
      updateMarkers(vehicles);
      renderVehicleList(vehicles);

      // Cập nhật trạm ghim đồng bộ với nhịp poll 15s (SPEC-08)
      if (pinnedStation && pinnedStation.routeId === currentRouteId && pinnedStation.direction === currentDirection) {
        updateStationFocusCard();
      }
    } catch (err) {
      console.error('[Hanoi Bus Live] Lỗi lấy dữ liệu xe trực tiếp:', err);
      vehicleCountEl.textContent = 'Mất kết nối GPS';
    } finally {
      isPolling = false;
      resetCountdown();
    }
  }

  /**
   * Quản lý đồng hồ đếm ngược chu kỳ làm mới
   */
  function resetCountdown() {
    countdownSeconds = Math.floor(POLL_INTERVAL_MS / 1000);
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
   * Bắt đầu chu kỳ Polling định kỳ 15 giây
   */
  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    resetCountdown();
    pollVehicles();
    pollTimer = setInterval(pollVehicles, POLL_INTERVAL_MS);
  }

  /**
   * Xóa sạch toàn bộ Marker xe hiện có trên bản đồ
   */
  function clearAllMarkers() {
    activeMarkers.forEach(m => m.remove());
    activeMarkers.clear();
    vehicleListEl.innerHTML = '<div class="empty-state">Đang tải dữ liệu trực tiếp từ BusMap...</div>';
    vehicleCountEl.textContent = '0 xe hoạt động';
    listCounterBadge.textContent = '0 xe';
    map._hasFittedInitialBounds = false;
  }

  /**
   * Xóa sạch các lớp hình học tim tuyến và trạm dừng
   */
  function clearRouteLayers() {
    if (routePolyline) {
      routePolyline.remove();
      routePolyline = null;
    }
    if (stationsLayerGroup) {
      stationsLayerGroup.clearLayers();
    }
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
      routes.forEach((r, idx) => {
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
