/**
 * Hanoi Bus Live ETA - Leaflet Map Manager
 * Handles map lifecycle, polyline drawing, station markers, and live vehicle tracking.
 * Implements 1D Frenet Centerline Dead Reckoning & Momentum-based Continuous Interception.
 * Adheres strictly to TimBus Dalvik Bytecode invariants (map/f.C, map/f.K, map/f.i).
 * 
 * ZERO TELEPORT GUARANTEE:
 * - When packet is duplicate/stale: NEVER jump backwards. Continues from current virtual position with damped speed.
 * - When packet has discrepancy: NEVER snap. Intercepts future lead position from current virtual position.
 */

// ======================================================================================
// 1. CÔNG CỤ TÍNH TOÁN HÌNH CẦU & GÓC XOAY THEO TIMBUS (map/f.K & map/f.i)
// ======================================================================================

function computeSphericalHeading(lat1, lon1, lat2, lon2) {
    const rad = Math.PI / 180.0;
    const phi1 = lat1 * rad;
    const phi2 = lat2 * rad;
    const dLon = (lon2 - lon1) * rad;
    const y = Math.sin(dLon) * Math.cos(phi2);
    const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLon);
    return (Math.atan2(y, x) * 180.0 / Math.PI + 360.0) % 360.0;
}

function shortestArcDelta(currentAngle, targetAngle) {
    return ((targetAngle - currentAngle + 540.0) % 360.0) - 180.0;
}

function calculateEquirectangularDistance(lat1, lon1, lat2, lon2) {
    const dLat = (lat2 - lat1) * 110574.0;
    const latMid = (lat1 + lat2) * 0.5 * Math.PI / 180.0;
    const dLon = (lon2 - lon1) * 111320.0 * Math.cos(latMid);
    return Math.sqrt(dLat * dLat + dLon * dLon);
}

// ======================================================================================
// 2. LỚP QUẢN LÝ QUỸ ĐẠO TIM ĐƯỜNG 1D FRENET (CORRIDOR TRAJECTORY)
// ======================================================================================

class CorridorTrajectory {
    constructor(coordinates) {
        this.points = [];
        this.totalLength = 0;
        this._buildTrajectory(coordinates);
    }

    _buildTrajectory(coordinates) {
        if (!coordinates || coordinates.length < 2) return;

        let accumDist = 0.0;
        for (let i = 0; i < coordinates.length; i++) {
            const lon = coordinates[i][0];
            const lat = coordinates[i][1];

            if (i > 0) {
                const prev = this.points[i - 1];
                const d = calculateEquirectangularDistance(prev.lat, prev.lng, lat, lon);
                accumDist += d;
                prev.heading = computeSphericalHeading(prev.lat, prev.lng, lat, lon);
            }

            this.points.push({
                lat: lat,
                lng: lon,
                s: accumDist,
                heading: 0.0,
            });
        }

        if (this.points.length >= 2) {
            this.points[this.points.length - 1].heading = this.points[this.points.length - 2].heading;
        }

        this.totalLength = accumDist;
    }

    getPointAtS(s) {
        if (!this.points || this.points.length === 0) {
            return { lat: 0, lng: 0, heading: 0 };
        }

        if (s <= 0.0) {
            return {
                lat: this.points[0].lat,
                lng: this.points[0].lng,
                heading: this.points[0].heading,
            };
        }

        if (s >= this.totalLength) {
            const last = this.points[this.points.length - 1];
            return {
                lat: last.lat,
                lng: last.lng,
                heading: last.heading,
            };
        }

        // Binary Search O(log N) finding segment [i, i+1] where s_i <= s <= s_{i+1}
        let low = 0;
        let high = this.points.length - 1;
        while (low <= high) {
            const mid = (low + high) >> 1;
            if (this.points[mid].s <= s) {
                low = mid + 1;
            } else {
                high = mid - 1;
            }
        }

        const idx = Math.max(0, Math.min(this.points.length - 2, high));
        const pA = this.points[idx];
        const pB = this.points[idx + 1];
        const segDist = pB.s - pA.s;

        let u = 0.0;
        if (segDist > 1e-4) {
            u = (s - pA.s) / segDist;
        }

        return {
            lat: pA.lat + u * (pB.lat - pA.lat),
            lng: pA.lng + u * (pB.lng - pA.lng),
            heading: pA.heading,
        };
    }
}

// ======================================================================================
// 3. LỚP ĐỘNG HỌC XE BUÝT: MOMENTUM-BASED INTERCEPTION (ZERO TELEPORT & ZERO BACK-JUMP)
// ======================================================================================

class BusKinematics {
    constructor(vehicleId, plate, initialS, initialSpeedKmh, status, telemetrySource, marker, initialLat, initialLon) {
        this.vehicleId = vehicleId;
        this.plate = plate;
        this.marker = marker;
        this.status = status || "ACTIVE_IN_TRANSIT";
        this.telemetrySource = telemetrySource || "busmap_relay";

        this.currentS = Math.max(0.0, initialS || 0.0);
        this.lastMeasS = this.currentS;
        this.lastMeasLat = initialLat !== undefined ? initialLat : null;
        this.lastMeasLon = initialLon !== undefined ? initialLon : null;

        const vMps = Math.max(0.0, (initialSpeedKmh || 0.0) / 3.6);
        this.measuredSpeedMps = vMps;
        this.effectiveSpeedMps = vMps;
        this.targetSpeedMps = vMps;

        this.currentHeading = 0.0;
        this.iconCircle = marker.getElement() ? marker.getElement().querySelector(".bus-icon-circle") : null;
    }

    step(dt, trajectory) {
        if (!trajectory) return;

        // Nếu xe dừng đỗ hoặc ở bến và vận tốc = 0
        if (this.status !== "ACTIVE_IN_TRANSIT" && this.effectiveSpeedMps <= 0.01) {
            return;
        }

        // 1. Điều hòa Vi sai Động lượng (Critically Damped Momentum Smoothing):
        // Vận tốc effectiveSpeedMps biến thiên trơn nhẵn hướng tới targetSpeedMps
        const momentumRate = 4.0; // Hệ số đáp ứng động lượng (1/s)
        this.effectiveSpeedMps += (this.targetSpeedMps - this.effectiveSpeedMps) * Math.min(1.0, momentumRate * dt);

        if (this.effectiveSpeedMps <= 0.01) {
            this.effectiveSpeedMps = 0.0;
            return;
        }

        // 2. Tịnh tiến từ vị trí nội suy ảo hiện tại vào tương lai gần dọc tim đường
        const deltaS = this.effectiveSpeedMps * dt;
        this.currentS += deltaS;

        if (this.currentS >= trajectory.totalLength) {
            this.currentS = trajectory.totalLength;
            this.effectiveSpeedMps = 0.0;
            this.targetSpeedMps = 0.0;
        }

        // 3. Ánh xạ lý trình Frenet s -> Tọa độ địa lý WGS-84 & Góc hướng tim đường
        const pt = trajectory.getPointAtS(this.currentS);
        this.marker.setLatLng([pt.lat, pt.lng]);

        // 4. Xoay icon mượt mà theo cung quay ngắn nhất (TimBus map/f.i)
        const dHeading = shortestArcDelta(this.currentHeading, pt.heading);
        this.currentHeading = (this.currentHeading + dHeading * Math.min(1.0, 10.0 * dt) + 360.0) % 360.0;

        if (!this.iconCircle && this.marker.getElement()) {
            this.iconCircle = this.marker.getElement().querySelector(".bus-icon-circle");
        }
        if (this.iconCircle) {
            this.iconCircle.style.transform = `rotate(${this.currentHeading.toFixed(1)}deg)`;
        }
    }

    updateTelemetry(lat, lon, sMeas, speedKmh, status, telemetrySource, trajectory, tau = 4.5) {
        this.status = status || "ACTIVE_IN_TRANSIT";
        this.telemetrySource = telemetrySource || "busmap_relay";
        const vMeas = Math.max(0.0, (speedKmh || 0.0) / 3.6);
        this.measuredSpeedMps = vMeas;

        // BẢO VỆ KHẨN CẤP: Chỉ snap khi khoảng cách dị thường cực lớn (> 800m) do xe đổi tuyến / quay đầu bến
        if (Math.abs(sMeas - this.currentS) > 800.0) {
            this.currentS = sMeas;
            this.lastMeasS = sMeas;
            this.lastMeasLat = lat;
            this.lastMeasLon = lon;
            this.effectiveSpeedMps = vMeas;
            this.targetSpeedMps = vMeas;
            if (trajectory) {
                const pt = trajectory.getPointAtS(sMeas);
                this.marker.setLatLng([pt.lat, pt.lng]);
                this.currentHeading = pt.heading;
            }
            return;
        }

        // ==============================================================================
        // 1. KIỂM TRA GÓI TIN TRÙNG LẶP (CHUẨN TIMBUS map/f.C IEEE-754 ĐẲNG CỰ):
        // GÓI TIN TRÙNG LÀ KHI VĨ ĐỘ (LAT) VÀ KINH ĐỘ (LON) ĐỀU TRÙNG NHAU!
        // (Do trôi pha viễn thông, server trả lại gói cũ hoặc xe đang dừng đỗ)
        // -> TIẾP TỤC NỘI SUY TIẾP TỪ VỊ TRÍ ẢO HIỆN TẠI NHƯNG GIẢM CHẬM TỐC ĐỘ (MOMENTUM DAMPING)
        // -> TUYỆT ĐỐI CẤM GIẬT LÙI VỀ sMeas!
        // ==============================================================================
        const isDuplicate = (
            this.lastMeasLat !== null &&
            this.lastMeasLon !== null &&
            Math.abs(lat - this.lastMeasLat) < 1e-6 &&
            Math.abs(lon - this.lastMeasLon) < 1e-6
        );

        if (isDuplicate) {
            // Gói tin trùng: xe tiếp tục tiến về phía trước từ vị trí ảo hiện tại nhưng giảm chậm tốc độ
            if (vMeas < 0.5) {
                // Xe thực tế ngoài đời đã dừng hẳn: giảm dần targetSpeed về 0 để hãm phanh êm
                this.targetSpeedMps = 0.0;
            } else {
                // Xe đang chạy nhưng gói tin trùng do trôi pha mạng: giảm dần tốc độ mục tiêu để bảo lưu quán tính
                this.targetSpeedMps = Math.max(0.0, this.effectiveSpeedMps * 0.7);
            }
            return;
        }

        // ==============================================================================
        // 2. GÓI TIN MỚI: TỌA ĐỘ GPS (LAT, LON) ĐÃ CÓ SỰ THAY ĐỔI THỰC TẾ
        // -> TUYỆT ĐỐI KHÔNG SNAP / KHÔNG TELEPORT!
        // -> VI SAI ĐÓN ĐẦU VỊ TRÍ NỘI SUY MỚI TỪ VỊ TRÍ NỘI SUY ẢO HIỆN TẠI
        // ==============================================================================
        this.lastMeasLat = lat;
        this.lastMeasLon = lon;
        this.lastMeasS = sMeas;

        // Điểm đón đầu của xe thật trong tương lai sau tau giây:
        // sLead = sMeas + vMeas * tau
        const sLead = sMeas + vMeas * tau;

        // Quãng đường cần vượt qua tính từ vị trí nội suy ảo hiện tại:
        const deltaSNeeded = sLead - this.currentS;

        if (deltaSNeeded <= 0.0) {
            // Xe ảo đã chạy vượt trước xe thật (overshoot do xe thật phanh gấp/dừng đèn đỏ)
            // Xe buýt không bao giờ chạy lùi: hạ targetSpeed về 0 để hãm phanh êm chờ xe thật
            this.targetSpeedMps = 0.0;
        } else {
            // Vận tốc cần thiết để đón đầu điểm sLead trong tau giây:
            const vInter = deltaSNeeded / tau;

            // Kẹp chặn giới hạn vận tốc an toàn của xe buýt đô thị [0.5 m/s .. 22.2 m/s (~80 km/h)]
            this.targetSpeedMps = Math.max(0.5, Math.min(22.2, vInter));
        }

        // Nếu xe ngoài đời thực đã dừng hẳn và khoảng cách sai lệch rất nhỏ (< 2m):
        if (vMeas < 0.5 && Math.abs(sMeas - this.currentS) < 2.0) {
            this.targetSpeedMps = 0.0;
        }
    }
}

// ======================================================================================
// 4. BỘ ĐIỀU PHỐI BẢN ĐỒ LEAFLET (MAP MANAGER)
// ======================================================================================

class MapManager {
    constructor(containerId, onStationSelected, onBusSelected) {
        this.containerId = containerId;
        this.onStationSelected = onStationSelected;
        this.onBusSelected = onBusSelected;

        this.map = null;
        this.routeLayer = null;
        this.stationsLayerGroup = L.layerGroup();
        this.busMarkers = new Map(); // vehicle_id -> L.Marker
        this.busKinematicsMap = new Map(); // vehicle_id -> BusKinematics
        this.selectedStationHalo = null;

        this.corridorTrajectory = null;
        this.lastTickTime = (window.performance && window.performance.now) ? window.performance.now() : Date.now();
        this._animFrameId = null;

        this._initMap();
        this._startKinematicTickLoop();
    }

    _initMap() {
        this.map = L.map(this.containerId, {
            center: [21.0285, 105.8542],
            zoom: 13,
            zoomControl: false,
        });

        const googleRoad = L.tileLayer("https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}", {
            attribution: '&copy; Google Maps',
            maxZoom: 20,
        });

        const esriSatellite = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
            attribution: 'Tiles &copy; Esri &mdash; Source: Esri, USGS, AeroGRID, IGN',
            maxZoom: 18,
        });

        const esriStreet = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
            attribution: 'Tiles &copy; Esri &mdash; Street Map',
            maxZoom: 19,
        });

        googleRoad.addTo(this.map);

        const baseMaps = {
            "🗺️ Google Đường phố": googleRoad,
            "🛰️ Ảnh Vệ tinh (Esri)": esriSatellite,
            "🏙️ Esri Street Map": esriStreet,
        };
        L.control.layers(baseMaps, null, { position: "topright", collapsed: false }).addTo(this.map);
        L.control.zoom({ position: "bottomright" }).addTo(this.map);
        this.stationsLayerGroup.addTo(this.map);
    }

    _startKinematicTickLoop() {
        const tick = (timestamp) => {
            const now = timestamp || ((window.performance && window.performance.now) ? window.performance.now() : Date.now());
            let dt = (now - this.lastTickTime) / 1000.0;
            if (dt <= 0.0 || dt > 0.15) {
                dt = 0.0166;
            }
            this.lastTickTime = now;

            if (this.corridorTrajectory && this.busKinematicsMap.size > 0) {
                for (const busKin of this.busKinematicsMap.values()) {
                    busKin.step(dt, this.corridorTrajectory);
                }
            }

            if (window.requestAnimationFrame) {
                this._animFrameId = window.requestAnimationFrame(tick);
            }
        };

        if (window.requestAnimationFrame) {
            this._animFrameId = window.requestAnimationFrame(tick);
        }
    }

    clearCorridor() {
        if (this.routeLayer) {
            this.map.removeLayer(this.routeLayer);
            this.routeLayer = null;
        }
        this.stationsLayerGroup.clearLayers();
        this.clearBuses();
        this.corridorTrajectory = null;

        if (this.selectedStationHalo) {
            this.map.removeLayer(this.selectedStationHalo);
            this.selectedStationHalo = null;
        }
    }

    clearBuses() {
        for (const marker of this.busMarkers.values()) {
            this.map.removeLayer(marker);
        }
        this.busMarkers.clear();
        this.busKinematicsMap.clear();
    }

    renderRoute(geometryData) {
        this.clearCorridor();

        // 1. Build Frenet 1D Corridor Trajectory
        const coords = geometryData.shape_geojson.coordinates;
        this.corridorTrajectory = new CorridorTrajectory(coords);

        // 2. Draw Polyline (coordinates from GeoJSON [lon, lat] -> Leaflet [lat, lon])
        const latLngs = coords.map(pt => [pt[1], pt[0]]);
        this.routeLayer = L.polyline(latLngs, {
            color: "#2563eb",
            weight: 5,
            opacity: 0.85,
            lineJoin: "round",
            lineCap: "round",
        }).addTo(this.map);

        this.map.fitBounds(this.routeLayer.getBounds(), { padding: [40, 40] });

        // 3. Render Stations
        const totalStations = geometryData.stations.length;
        geometryData.stations.forEach((st, idx) => {
            let fillColor = "#1e40af";
            let radius = 5;

            if (idx === 0) {
                fillColor = "#16a34a";
                radius = 8;
            } else if (idx === totalStations - 1) {
                fillColor = "#dc2626";
                radius = 8;
            }

            const marker = L.circleMarker([st.lat, st.lon], {
                radius: radius,
                fillColor: fillColor,
                color: "#ffffff",
                weight: 2,
                opacity: 1,
                fillOpacity: 0.95,
                className: "station-marker-circle",
            });

            marker.bindTooltip(
                `<b>#${st.station_order} - ${st.station_name}</b><br><span style="color:#64748b;">${(st.cum_distance_m / 1000).toFixed(1)} km</span>`,
                { direction: "top", offset: [0, -6] }
            );

            marker.on("click", () => {
                this.highlightStation(st);
                if (this.onStationSelected) {
                    this.onStationSelected(st);
                }
            });

            this.stationsLayerGroup.addLayer(marker);
        });
    }

    highlightStation(station) {
        if (this.selectedStationHalo) {
            this.map.removeLayer(this.selectedStationHalo);
        }
        this.selectedStationHalo = L.circleMarker([station.lat, station.lon], {
            radius: 14,
            fillColor: "#3b82f6",
            fillOpacity: 0.25,
            color: "#2563eb",
            weight: 2,
            dashArray: "3, 3",
            interactive: false,
        }).addTo(this.map);
    }

    updateBuses(buses) {
        const currentVids = new Set();

        buses.forEach(b => {
            const vid = b.vehicle_id;
            currentVids.add(vid);

            const status = b.status || "ACTIVE_IN_TRANSIT";
            let sBus = b.current_s_bus_m;
            if (sBus === undefined || sBus === null) {
                sBus = 0.0;
            }

            let circleClass = "";
            let pulseHtml = "";

            if (status === "AT_ORIGIN_TERMINAL") {
                circleClass = "staging";
            } else if (status === "AT_DESTINATION_TERMINAL") {
                circleClass = "destination";
            } else if (status === "DETOUR_OFF_CORRIDOR") {
                circleClass = "detour";
            } else {
                pulseHtml = '<div class="pulse-ring"></div>';
            }

            const isTimbus = b.telemetry_source === "timbus_5s";
            const badgeClass = isTimbus ? "bus-plate-badge bg-emerald-700 text-white font-bold" : "bus-plate-badge";
            const badgePrefix = isTimbus ? "⚡ " : "";

            if (this.busKinematicsMap.has(vid)) {
                // Xe đã có trên map: Cập nhật viễn trắc và điều hòa vi sai động lượng đón đầu
                const busKin = this.busKinematicsMap.get(vid);
                busKin.updateTelemetry(
                    b.lat,
                    b.lon,
                    sBus,
                    b.speed_kmh || 0.0,
                    status,
                    b.telemetry_source,
                    this.corridorTrajectory,
                    4.5 // tau = 4.5s
                );

                // Cập nhật DOM in-place không hủy DOM element
                const el = busKin.marker.getElement();
                if (el) {
                    const badge = el.querySelector(".bus-plate-badge");
                    if (badge) {
                        badge.textContent = `${badgePrefix}${b.plate || vid}`;
                        badge.className = badgeClass;
                    }
                    const circle = el.querySelector(".bus-icon-circle");
                    if (circle) {
                        circle.className = `bus-icon-circle ${circleClass}`;
                    }
                }
            } else {
                // Khởi tạo xe mới khi lần đầu xuất hiện trên tuyến
                let initLat = b.lat;
                let initLng = b.lon;
                let initHeading = b.heading_deg || 0;

                if (this.corridorTrajectory) {
                    const pt = this.corridorTrajectory.getPointAtS(sBus);
                    initLat = pt.lat;
                    initLng = pt.lng;
                    initHeading = pt.heading;
                }

                const iconHtml = `
                    <div class="bus-marker-container">
                        ${pulseHtml}
                        <div class="bus-icon-circle ${circleClass}" style="transform: rotate(${initHeading}deg);">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-1.1 0-2 .9-2 2v7h2"></path>
                                <circle cx="7" cy="17" r="2"></circle>
                                <path d="M9 17h6"></path>
                                <circle cx="17" cy="17" r="2"></circle>
                            </svg>
                        </div>
                        <div class="${badgeClass}">${badgePrefix}${b.plate || vid}</div>
                    </div>
                `;

                const customIcon = L.divIcon({
                    html: iconHtml,
                    className: "custom-bus-div-icon",
                    iconSize: [44, 44],
                    iconAnchor: [22, 22],
                });

                const newMarker = L.marker([initLat, initLng], { icon: customIcon });
                newMarker.on("click", () => {
                    if (this.onBusSelected) {
                        this.onBusSelected(b);
                    }
                });
                newMarker.addTo(this.map);

                const newKin = new BusKinematics(
                    vid,
                    b.plate || vid,
                    sBus,
                    b.speed_kmh || 0.0,
                    status,
                    b.telemetry_source,
                    newMarker,
                    b.lat,
                    b.lon
                );
                newKin.currentHeading = initHeading;

                this.busMarkers.set(vid, newMarker);
                this.busKinematicsMap.set(vid, newKin);
            }
        });

        // Prune stale vehicles
        for (const [vid, marker] of this.busMarkers.entries()) {
            if (!currentVids.has(vid)) {
                this.map.removeLayer(marker);
                this.busMarkers.delete(vid);
                this.busKinematicsMap.delete(vid);
            }
        }
    }
}
