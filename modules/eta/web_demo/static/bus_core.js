/**
 * Shared client utilities for Passenger (/) and Debug (/debug) UIs.
 * No UI/theme assumptions; pure formatting, API fetch wrapper, and Leaflet icon builders.
 */
(function (global) {
  'use strict';

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function normalizeText(value) {
    return String(value || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/đ/g, 'd')
      .trim();
  }

  function formatDistance(meters) {
    const m = Math.max(0, Math.round(Number(meters) || 0));
    if (m >= 1000) return `${(m / 1000).toFixed(1)} km`;
    return `${m} m`;
  }

  function formatDuration(seconds) {
    const s = Math.max(0, Math.round(Number(seconds) || 0));
    if (s < 60) return `${s}s`;
    const mins = Math.floor(s / 60);
    const rem = s % 60;
    return rem > 0 ? `${mins} phút ${rem}s` : `${mins} phút`;
  }

  function formatClock(bus) {
    if (bus && bus.estimated_arrival_time) return String(bus.estimated_arrival_time);
    if (bus && bus.arrival_time_epoch) {
      const d = new Date(bus.arrival_time_epoch * 1000);
      return d.toLocaleTimeString('vi-VN', { hour12: false });
    }
    return '--:--:--';
  }

  function trafficMeta(status) {
    if (status === 'THONG_THOANG') return { label: 'Thông thoáng', cls: 'tone-ok' };
    if (status === 'UN_TAC') return { label: 'Ùn tắc', cls: 'tone-danger' };
    return { label: 'Bình thường', cls: 'tone-warn' };
  }

  function fallbackLabel(reason) {
    const map = {
      ok: 'ML Calibrated',
      cold_start_causal: 'Chưa đủ lịch sử GPS',
      model_unavailable: 'Mô hình chưa sẵn sàng',
      unknown_route: 'Tuyến ngoài tập huấn luyện',
      predict_error: 'Lỗi suy luận ML',
    };
    return map[reason] || 'Ước tính nền';
  }

  async function fetchJson(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const errBody = await res.json();
          if (errBody && errBody.detail) detail = `${detail}: ${errBody.detail}`;
        } catch (_) {}
        return { ok: false, status: res.status, data: null, error: detail };
      }
      const data = await res.json();
      return { ok: true, status: res.status, data, error: null };
    } catch (err) {
      return { ok: false, status: 0, data: null, error: err && err.message ? err.message : 'Lỗi kết nối mạng' };
    }
  }

  function createBusIcon(vehicle, options) {
    const opts = options || {};
    const isLeading = Boolean(opts.isLeading);
    const leadingText = opts.leadingText || '';
    const src = vehicle.telemetry_source === 'timbus' ? 'timbus' : 'busmap';
    const deg = Number(vehicle.deg || 0);
    const size = isLeading ? 42 : 32;
    const classes = ['bus-pin', `src-${src}`];
    if (isLeading) classes.push('is-leading');
    if (opts.isFocused) classes.push('is-focused');

    const badgeHtml = isLeading && leadingText
      ? `<div class="leading-bus-tag">${escapeHtml(leadingText)}</div>`
      : '';

    const html = `
      <div class="${classes.join(' ')}">
        ${badgeHtml}
        ${isLeading ? '<span class="leading-pulse" aria-hidden="true"></span>' : ''}
        <div class="bus-arrow" style="transform: rotate(${deg}deg)">
          <svg viewBox="0 0 24 24" width="${isLeading ? 20 : 16}" height="${isLeading ? 20 : 16}" fill="currentColor" aria-hidden="true">
            <path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z"/>
          </svg>
        </div>
      </div>
    `;

    return L.divIcon({
      className: 'bus-div-icon',
      html,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    });
  }

  function createStationIcon(isPinned) {
    const size = isPinned ? 22 : 13;
    return L.divIcon({
      className: 'station-div-icon',
      html: `<div class="station-dot ${isPinned ? 'is-pinned' : ''}"></div>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    });
  }

  global.BusCore = {
    escapeHtml,
    normalizeText,
    formatDistance,
    formatDuration,
    formatClock,
    trafficMeta,
    fallbackLabel,
    fetchJson,
    createBusIcon,
    createStationIcon,
  };
})(window);
