/**
 * Hanoi Bus Live ETA - Leaflet Map Manager
 * Handles map lifecycle, polyline drawing, station markers, and live vehicle tracking.
 */

class MapManager {
    constructor(containerId, onStationSelected, onBusSelected) {
        this.containerId = containerId;
        this.onStationSelected = onStationSelected;
        this.onBusSelected = onBusSelected;

        this.map = null;
        this.routeLayer = null;
        this.stationsLayerGroup = L.layerGroup();
        this.busMarkers = new Map(); // vehicle_id -> L.Marker
        this.selectedStationHalo = null;

        this._initMap();
    }

    _initMap() {
        // Center on Hanoi coordinates
        this.map = L.map(this.containerId, {
            center: [21.0285, 105.8542],
            zoom: 13,
            zoomControl: false,
        });

        // Add clean CartoDB Positron tiles
        L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: "abcd",
            maxZoom: 19,
        }).addTo(this.map);

        // Add Zoom Control at bottom right
        L.control.zoom({ position: "bottomright" }).addTo(this.map);

        // Add stations layer group
        this.stationsLayerGroup.addTo(this.map);
    }

    clearCorridor() {
        if (this.routeLayer) {
            this.map.removeLayer(this.routeLayer);
            this.routeLayer = null;
        }
        this.stationsLayerGroup.clearLayers();
        this.clearBuses();
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
    }

    renderRoute(geometryData) {
        this.clearCorridor();

        // 1. Draw Polyline (coordinates from GeoJSON [lon, lat] -> Leaflet [lat, lon])
        const latLngs = geometryData.shape_geojson.coordinates.map(pt => [pt[1], pt[0]]);
        this.routeLayer = L.polyline(latLngs, {
            color: "#2563eb",
            weight: 5,
            opacity: 0.85,
            lineJoin: "round",
            lineCap: "round",
        }).addTo(this.map);

        // Fit map bounds smoothly
        this.map.fitBounds(this.routeLayer.getBounds(), { padding: [40, 40] });

        // 2. Render Stations
        const totalStations = geometryData.stations.length;
        geometryData.stations.forEach((st, idx) => {
            let fillColor = "#1e40af"; // Intermediate: navy blue
            let radius = 5;

            if (idx === 0) {
                fillColor = "#16a34a"; // Origin terminal: green
                radius = 8;
            } else if (idx === totalStations - 1) {
                fillColor = "#dc2626"; // Destination terminal: red
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

            const lat = b.lat;
            const lon = b.lon;
            const heading = b.heading_deg || 0;
            const status = b.status || "ACTIVE_IN_TRANSIT";

            let circleClass = "";
            let pulseHtml = "";

            if (status === "AT_ORIGIN_TERMINAL") {
                circleClass = "staging";
            } else if (status === "AT_DESTINATION_TERMINAL") {
                circleClass = "destination";
            } else if (status === "DETOUR_OFF_CORRIDOR") {
                circleClass = "detour";
            } else {
                // Active in-transit
                pulseHtml = '<div class="pulse-ring"></div>';
            }

            const iconHtml = `
                <div class="bus-marker-container">
                    ${pulseHtml}
                    <div class="bus-icon-circle ${circleClass}" style="transform: rotate(${heading}deg);">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-1.1 0-2 .9-2 2v7h2"></path>
                            <circle cx="7" cy="17" r="2"></circle>
                            <path d="M9 17h6"></path>
                            <circle cx="17" cy="17" r="2"></circle>
                        </svg>
                    </div>
                    <div class="bus-plate-badge">${b.plate || vid}</div>
                </div>
            `;

            const customIcon = L.divIcon({
                html: iconHtml,
                className: "custom-bus-div-icon",
                iconSize: [44, 44],
                iconAnchor: [22, 22],
            });

            if (this.busMarkers.has(vid)) {
                // In-place update position & icon to prevent map redraw thrashing
                const existingMarker = this.busMarkers.get(vid);
                existingMarker.setLatLng([lat, lon]);
                existingMarker.setIcon(customIcon);
            } else {
                // Create new bus marker
                const newMarker = L.marker([lat, lon], { icon: customIcon });
                newMarker.on("click", () => {
                    if (this.onBusSelected) {
                        this.onBusSelected(b);
                    }
                });
                newMarker.addTo(this.map);
                this.busMarkers.set(vid, newMarker);
            }
        });

        // Prune stale markers
        for (const [vid, marker] of this.busMarkers.entries()) {
            if (!currentVids.has(vid)) {
                this.map.removeLayer(marker);
                this.busMarkers.delete(vid);
            }
        }
    }
}
