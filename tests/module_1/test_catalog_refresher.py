"""Unit tests for catalog_refresher Phase 2 full-route discovery and Phase 3 routeId sync."""

from module_1_data_ingestion_and_preprocessing.step_1_1_busmap_crawler_and_relay import catalog_refresher


def test_refresh_discovers_new_vehicles_even_on_busy_route_and_updates_reassigned_route(monkeypatch):
    saved = {}
    sample_cfg = {
        "routes": [{"route_no": "02", "route_id": 2}],
        "vehicles": [
            {"id": i, "title": f"29A000{i:02d}", "routeId": 2}
            for i in range(1, 15)
        ],
    }

    monkeypatch.setattr(catalog_refresher, "load_cluster_config", lambda *a: sample_cfg)
    monkeypatch.setattr(catalog_refresher, "save_cluster_config", lambda cfg, *a: saved.update(cfg))
    monkeypatch.setattr(
        catalog_refresher,
        "audit_vehicle",
        lambda vid: {
            "id": vid,
            "status": "ACTIVE",
            "route_id": 27 if vid == 1 else 2,
            "age_h": 0.1,
        },
    )
    monkeypatch.setattr(
        catalog_refresher,
        "fetch_route_buses_live",
        lambda rid, direction=0: [{"Id": 999, "RouteId": 2, "VehicleNumber": "29A99999"}] if direction == 0 else [],
    )
    monkeypatch.setattr(catalog_refresher.time, "sleep", lambda *a: None)

    catalog_refresher.run_daily_catalog_refresh()

    by_id = {v["id"]: v for v in saved["vehicles"]}
    assert 999 in by_id
    assert by_id[999]["routeId"] == 2
    assert by_id[1]["routeId"] == 27
