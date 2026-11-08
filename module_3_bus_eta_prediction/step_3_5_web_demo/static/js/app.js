/**
 * Hanoi Bus Live ETA - Main Controller
 * Manages route selection, direction toggles, live polling, and Station/Bus ETA cards.
 */

document.addEventListener("DOMContentLoaded", () => {
    const app = new BusTrackingApp();
    app.init();
});

class BusTrackingApp {
    constructor() {
        this.routes = [];
        this.currentRouteCode = null;
        this.currentDirection = "go";
        this.currentGeometry = null;
        this.currentLiveEta = null;
        this.selectedStation = null;
        this.selectedBus = null;

        this.pollingTimer = null;
        this.countdownTimer = null;
        this.countdownVal = 15;
        this.isPollingActive = true;

        this.mapManager = null;
    }

    async init() {
        // Defensive check: Guard against opening index.html directly from filesystem (file:///)
        if (window.location.protocol === "file:") {
            document.body.innerHTML = `
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 40px; text-align: center; max-width: 600px; margin: 60px auto; background: #fff1f2; border: 2px solid #f43f5e; border-radius: 16px; color: #9f1239; box-shadow: 0 10px 25px rgba(0,0,0,0.08);">
                    <div style="font-size: 40px; margin-bottom: 12px;">⚠️</div>
                    <h2 style="margin-bottom: 12px; font-size: 20px; font-weight: bold;">Bạn đang mở tệp trực tiếp từ ổ đĩa (file:///)</h2>
                    <p style="font-size: 14px; line-height: 1.6; margin-bottom: 20px; color: #881337;">
                        Trình duyệt chặn các kết nối API cục bộ vì chính sách bảo mật CORS của giao thức file://.<br>
                        Vui lòng khởi động máy chủ bằng cách nhấp đúp vào <b>run_demo.bat</b> hoặc chạy <b>.\\run_demo.ps1</b>, sau đó truy cập vào địa chỉ bên dưới:
                    </p>
                    <a href="http://127.0.0.1:8000" style="display: inline-block; padding: 12px 24px; background: #2563eb; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 15px; box-shadow: 0 4px 10px rgba(37,99,235,0.3);">
                        👉 Mở Web Demo: http://127.0.0.1:8000
                    </a>
                </div>
            `;
            return;
        }

        // 1. Initialize Map Manager
        this.mapManager = new MapManager(
            "map",
            (station) => this.onStationSelected(station),
            (bus) => this.onBusSelected(bus)
        );

        // 2. Bind UI Elements
        this.routeSelect = document.getElementById("routeSelect");
        this.btnDirGo = document.getElementById("btnDirGo");
        this.btnDirRe = document.getElementById("btnDirRe");
        this.statusBadge = document.getElementById("statusBadge");
        this.countdownBadge = document.getElementById("countdownBadge");
        this.stationCard = document.getElementById("stationCard");
        this.stationEmptyState = document.getElementById("stationEmptyState");
        this.busCard = document.getElementById("busCard");
        this.trafficBanner = document.getElementById("trafficBanner");
        this.trafficText = document.getElementById("trafficText");
        this.activeBusesCount = document.getElementById("activeBusesCount");

        this.bindEvents();

        // 3. Load Routes Catalog
        await this.loadRoutes();
    }

    bindEvents() {
        // Route change
        this.routeSelect.addEventListener("change", (e) => {
            const val = e.target.value;
            if (val) {
                this.selectRoute(val);
            } else {
                this.resetToBlankState();
            }
        });

        // Direction toggles
        this.btnDirGo.addEventListener("click", () => this.switchDirection("go"));
        this.btnDirRe.addEventListener("click", () => this.switchDirection("re"));

        // Mobile close buttons
        const closeBusCard = document.getElementById("closeBusCard");
        if (closeBusCard) {
            closeBusCard.addEventListener("click", () => {
                this.busCard.classList.add("hidden");
                this.selectedBus = null;
            });
        }
    }

    async loadRoutes() {
        try {
            const res = await fetch("/api/v1/routes");
            if (!res.ok) throw new Error("Không thể tải danh mục tuyến");
            this.routes = await res.json();

            this.routeSelect.innerHTML = '<option value="">-- Chọn một tuyến xe buýt --</option>';
            this.routes.forEach((r) => {
                const opt = document.createElement("option");
                opt.value = r.route_code;
                opt.textContent = `Tuyến ${r.route_code}: ${r.route_name}`;
                this.routeSelect.appendChild(opt);
            });
        } catch (err) {
            console.error("Lỗi khi tải danh mục tuyến:", err);
            this.routeSelect.innerHTML = '<option value="">Lỗi nạp dữ liệu tuyến</option>';
        }
    }

    resetToBlankState() {
        this.currentRouteCode = null;
        this.currentGeometry = null;
        this.currentLiveEta = null;
        this.selectedStation = null;
        this.selectedBus = null;

        this.stopPolling();
        this.mapManager.clearCorridor();

        this.stationCard.classList.add("hidden");
        this.stationEmptyState.classList.remove("hidden");
        this.busCard.classList.add("hidden");
        this.trafficBanner.classList.add("hidden");

        this.statusBadge.textContent = "Sẵn sàng";
        this.statusBadge.className = "px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700";
    }

    async selectRoute(routeCode) {
        this.currentRouteCode = routeCode;
        this.selectedStation = null;
        this.selectedBus = null;

        // Reset UI cards
        this.stationCard.classList.add("hidden");
        this.stationEmptyState.classList.remove("hidden");
        this.busCard.classList.add("hidden");

        // Load geometry
        await this.loadGeometry();
        // Start polling live ETA
        this.startPolling();
    }

    switchDirection(dir) {
        if (this.currentDirection === dir) return;
        this.currentDirection = dir;

        // Update button visual styles
        if (dir === "go") {
            this.btnDirGo.classList.add("bg-blue-600", "text-white", "shadow-sm");
            this.btnDirGo.classList.remove("bg-slate-100", "text-slate-700", "hover:bg-slate-200");
            this.btnDirRe.classList.remove("bg-blue-600", "text-white", "shadow-sm");
            this.btnDirRe.classList.add("bg-slate-100", "text-slate-700", "hover:bg-slate-200");
        } else {
            this.btnDirRe.classList.add("bg-blue-600", "text-white", "shadow-sm");
            this.btnDirRe.classList.remove("bg-slate-100", "text-slate-700", "hover:bg-slate-200");
            this.btnDirGo.classList.remove("bg-blue-600", "text-white", "shadow-sm");
            this.btnDirGo.classList.add("bg-slate-100", "text-slate-700", "hover:bg-slate-200");
        }

        if (this.currentRouteCode) {
            this.selectedStation = null;
            this.selectedBus = null;
            this.stationCard.classList.add("hidden");
            this.stationEmptyState.classList.remove("hidden");
            this.busCard.classList.add("hidden");

            this.loadGeometry().then(() => this.fetchLiveEta(true));
        }
    }

    async loadGeometry() {
        if (!this.currentRouteCode) return;

        this.statusBadge.textContent = "Đang tải lộ trình...";
        this.statusBadge.className = "px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700";

        try {
            const url = `/api/v1/routes/${this.currentRouteCode}/geometry?direction=${this.currentDirection}`;
            const res = await fetch(url);
            if (!res.ok) throw new Error("Không thể tải tim đường");

            this.currentGeometry = await res.json();
            this.mapManager.renderRoute(this.currentGeometry);

            this.statusBadge.textContent = "Đang kết nối live GPS...";
            this.statusBadge.className = "px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700";
        } catch (err) {
            console.error("Lỗi khi tải geometry:", err);
            this.statusBadge.textContent = "Lỗi nạp lộ trình";
            this.statusBadge.className = "px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700";
        }
    }

    async fetchLiveEta(isImmediate = false) {
        if (!this.currentRouteCode) return;

        try {
            const url = `/api/v1/routes/${this.currentRouteCode}/live-eta?direction=${this.currentDirection}`;
            const res = await fetch(url);
            if (!res.ok) throw new Error("Lỗi nạp live ETA");

            this.currentLiveEta = await res.json();

            // 1. Update Map Buses
            this.mapManager.updateBuses(this.currentLiveEta.buses);

            // 2. Update Traffic Banner
            this.trafficBanner.classList.remove("hidden");
            this.trafficText.textContent = this.currentLiveEta.traffic_condition;
            this.activeBusesCount.textContent = `${this.currentLiveEta.active_in_transit_count} xe đang chạy`;

            // 3. Update Status Badge
            const cacheLabel = this.currentLiveEta.cached ? "(Cache)" : "(Live)";
            this.statusBadge.textContent = `Live GPS ${cacheLabel}`;
            this.statusBadge.className = "px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700";

            // 4. Refresh selected station card if open
            if (this.selectedStation) {
                this.renderStationCard(this.selectedStation);
            }

            // 5. Refresh selected bus card if open
            if (this.selectedBus) {
                const refreshedBus = this.currentLiveEta.buses.find(
                    (b) => b.vehicle_id === this.selectedBus.vehicle_id
                );
                if (refreshedBus) {
                    this.renderBusCard(refreshedBus);
                }
            }
        } catch (err) {
            console.error("Lỗi khi kéo live ETA:", err);
            this.statusBadge.textContent = "Mất kết nối GPS";
            this.statusBadge.className = "px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700";
        }
    }

    startPolling() {
        this.stopPolling();
        this.countdownVal = 15;
        this.updateCountdownBadge();

        // Immediate first fetch
        this.fetchLiveEta(true);

        // Polling interval 15s
        this.pollingTimer = setInterval(() => {
            this.countdownVal = 15;
            this.fetchLiveEta();
        }, 15000);

        // 1s countdown ticker
        this.countdownTimer = setInterval(() => {
            this.countdownVal = Math.max(0, this.countdownVal - 1);
            this.updateCountdownBadge();
        }, 1000);
    }

    stopPolling() {
        if (this.pollingTimer) clearInterval(this.pollingTimer);
        if (this.countdownTimer) clearInterval(this.countdownTimer);
        this.pollingTimer = null;
        this.countdownTimer = null;
        if (this.countdownBadge) {
            this.countdownBadge.textContent = "";
        }
    }

    updateCountdownBadge() {
        if (this.countdownBadge) {
            this.countdownBadge.textContent = `Làm mới sau ${this.countdownVal}s`;
        }
    }

    onStationSelected(station) {
        this.selectedStation = station;
        this.renderStationCard(station);
    }

    renderStationCard(station) {
        this.stationEmptyState.classList.add("hidden");
        this.stationCard.classList.remove("hidden");

        document.getElementById("stCardName").textContent = station.station_name;
        document.getElementById("stCardOrder").textContent = `Trạm #${station.station_order} (${(station.cum_distance_m / 1000).toFixed(1)} km từ bến xuất phát)`;

        if (!this.currentLiveEta || !this.currentLiveEta.buses) {
            return;
        }

        // Collect all buses that have predictions for this station order
        const approachingBuses = [];

        this.currentLiveEta.buses.forEach((b) => {
            if (b.status === "ACTIVE_IN_TRANSIT" && b.predictions) {
                const p = b.predictions.find(
                    (pred) => pred.target_station_order === station.station_order
                );
                if (p) {
                    approachingBuses.push({
                        bus: b,
                        prediction: p,
                    });
                }
            }
        });

        // Sort by eta_seconds ascending (closest first)
        approachingBuses.sort((a, b) => a.prediction.eta_seconds - b.prediction.eta_seconds);

        const etaContent = document.getElementById("stCardEtaContent");
        const noBusNotice = document.getElementById("stCardNoBusNotice");

        if (approachingBuses.length === 0) {
            etaContent.classList.add("hidden");
            noBusNotice.classList.remove("hidden");
            return;
        }

        etaContent.classList.remove("hidden");
        noBusNotice.classList.add("hidden");

        // Closest bus (P0 Feature)
        const first = approachingBuses[0];
        const b = first.bus;
        const p = first.prediction;

        document.getElementById("stCardPlate").textContent = b.plate || b.vehicle_id;
        document.getElementById("stCardSpeed").textContent = `${Math.round(b.speed_kmh)} km/h`;

        // Format wait time
        const mins = Math.floor(p.eta_seconds / 60);
        const secs = Math.round(p.eta_seconds % 60);
        let timeStr = "";
        if (mins > 0) {
            timeStr = `${mins} phút ${secs > 0 ? secs + ' giây' : ''}`;
        } else {
            timeStr = `${secs} giây`;
        }
        document.getElementById("stCardCountdown").textContent = timeStr;
        document.getElementById("stCardExpectedClock").textContent = `Cập bến: ${p.expected_arrival_time}`;

        // Asymmetric Arrival Window & Recommendation
        document.getElementById("stCardSafeWindow").textContent = p.safe_window;
        document.getElementById("stCardSafeRecommend").textContent = `👉 Khuyến nghị: Có mặt tại trạm trước ${p.safe_arrival_time} để không lỡ xe!`;

        // Next approaching buses list
        const nextListEl = document.getElementById("stCardNextBusesList");
        nextListEl.innerHTML = "";

        if (approachingBuses.length > 1) {
            document.getElementById("stCardNextBusesContainer").classList.remove("hidden");
            approachingBuses.slice(1, 4).forEach((item) => {
                const row = document.createElement("div");
                row.className = "flex items-center justify-between text-xs py-1.5 border-b border-slate-100 last:border-0";
                row.innerHTML = `
                    <div class="flex items-center space-x-2">
                        <span class="font-semibold text-slate-800">${item.bus.plate || item.bus.vehicle_id}</span>
                        <span class="text-slate-500">(${Math.round(item.bus.speed_kmh)} km/h)</span>
                    </div>
                    <div class="text-right">
                        <span class="font-bold text-blue-600">${Math.round(item.prediction.eta_minutes)} phút</span>
                        <span class="text-slate-400 text-[10px] ml-1">(${item.prediction.expected_arrival_time})</span>
                    </div>
                `;
                nextListEl.appendChild(row);
            });
        } else {
            document.getElementById("stCardNextBusesContainer").classList.add("hidden");
        }
    }

    onBusSelected(bus) {
        this.selectedBus = bus;
        this.renderBusCard(bus);
    }

    renderBusCard(bus) {
        this.busCard.classList.remove("hidden");

        document.getElementById("busCardPlate").textContent = bus.plate || bus.vehicle_id;
        document.getElementById("busCardSpeed").textContent = `${Math.round(bus.speed_kmh)} km/h`;

        const statusEl = document.getElementById("busCardStatus");
        if (bus.status === "ACTIVE_IN_TRANSIT") {
            statusEl.textContent = "Đang chạy trên tuyến";
            statusEl.className = "px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700";
        } else if (bus.status === "AT_ORIGIN_TERMINAL") {
            statusEl.textContent = "Đang chờ xuất bến";
            statusEl.className = "px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700";
        } else if (bus.status === "AT_DESTINATION_TERMINAL") {
            statusEl.textContent = "Đã về bến đích";
            statusEl.className = "px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-700";
        } else if (bus.status === "DETOUR_OFF_CORRIDOR") {
            statusEl.textContent = `Lệch hành lang (${Math.round(bus.cross_track_m || 0)}m)`;
            statusEl.className = "px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700";
        }

        const predsContainer = document.getElementById("busCardUpcomingStations");
        predsContainer.innerHTML = "";

        if (bus.predictions && bus.predictions.length > 0) {
            bus.predictions.slice(0, 5).forEach((p) => {
                const item = document.createElement("div");
                item.className = "flex items-center justify-between py-1 border-b border-slate-100 text-xs";
                item.innerHTML = `
                    <span class="text-slate-700 truncate max-w-[180px]">${p.target_station_name}</span>
                    <div class="text-right">
                        <span class="font-bold text-blue-600">${Math.round(p.eta_minutes)} ph</span>
                        <span class="text-slate-400 text-[10px] ml-1">(${p.expected_arrival_time})</span>
                    </div>
                `;
                predsContainer.appendChild(item);
            });
        } else {
            predsContainer.innerHTML = '<div class="text-xs text-slate-400 py-1 italic">Không có dữ liệu trạm kế tiếp</div>';
        }
    }
}
