# SPEC-20: 3.4 Facade and 3.5 Health Integration

**Status:** READY FOR IMPLEMENTATION  
**Scope:** the two integration defects identified by SPEC-19. This does not
alter frozen Modules 1, 2, 3.1, 3.2, or 3.3.

## 1. Observed boundary

The split 3.4 package already exposes `BusMapServingService`, the six public
DTOs used by the web adapter, `normalize_direction`, and
`fetch_live_vehicles_for_route` through its package `__init__.py`.  The 3.5
adapter currently imports the same names from `busmap_service.py`. The public
HTTP routes must therefore keep their schemas while their import boundary
changes to the package facade.

`/api/health` returns `status: "ok"`, while `run_demo.ps1` probes
`/api/v1/health` and accepts only `status: "healthy"`.

## 2. Required implementation

### I1 -- one 3.4 public import boundary

In `step_3_5_web_demo/app.py`, import only these existing public names from
`module_3_bus_eta_prediction.step_3_4_eta_serving_and_evaluation`:

```
BusMapServingService
RouteItemDTO, RouteLiveResponse, RouteShapeResponse,
RouteStationsResponse, StationEtaResponse
normalize_direction, fetch_live_vehicles_for_route
```

No app import may name `busmap_service`. Do not copy service methods into the
web adapter and do not create a second facade. `BusMapServingService` owns
catalogue, shape, station and ETA queries; `fetch_live_vehicles_for_route`
remains the live-feed owner. The endpoint paths, parameters, response models,
and current 400/404 meanings remain unchanged.

### I2 -- one health representation, two paths

Define one module-level health payload in `app.py` and return that same
payload object/value for both decorators:

```
GET /api/health
GET /api/v1/health
```

Its required fields are:

```
status: "healthy"
healthy: true
provider: "busmap"
mode: "busmap_discrete_only"
upstream: "https://api.busmap.city/v2/public/busmap/route_bus_gps"
```

The literal values above are the public health contract, not tuning numbers.
They must have one definition; neither route may construct a divergent payload.
The launcher remains the consumer of `/api/v1/health` and needs no upstream
or port change.

## 3. Invariants and prohibited shortcuts

1. `busmap_service.py` is not imported by the active 3.5 module.
2. No data/model/crawler/config change is permitted by this milestone.
3. No fallback response may invent routes, vehicles, stations, ETA values, or
   an upstream-health result.
4. There are no new numeric policy values. Any future numeric behavior belongs
   to an existing named configuration or a separately approved specification.
5. Existing BusMap-only discrete tracking is preserved; no TimBus, socket, or
   browser interpolation path is introduced.

## 4. Independent observable checks

The black-box verifier must be able to assert all of the following without
reading implementation code:

| ID | Request / inspection | Expected result |
| --- | --- | --- |
| F-01 | Import and start the FastAPI app | Startup does not require the legacy monolith import. |
| F-02 | `GET /api/health` | HTTP 200 and exactly the required health contract values. |
| F-03 | `GET /api/v1/health` | HTTP 200 and JSON-equal to `/api/health`. |
| F-04 | Existing valid/invalid calls to every declared route endpoint | Same response-model fields and same 400/404 class as before I1. |
| F-05 | Run `run_demo.ps1` against a compatible existing server | Its existing-server health decision accepts the response. |

## 5. Acceptance sequence

1. `@leaf_coder` performs I1 and I2 only.
2. `@whitebox_auditor` checks the diff against Sections 2--3, including the
   absence of a monolith import and of duplicated logic/magic policy values.
3. `@blind_tester` authors/runs F-01--F-05 plus the broader SPEC-16 contract
   tests without reading the coder implementation.
4. Only a passing white-box audit and black-box suite allow the status in
   SPEC-16/19 to move beyond verification pending.
