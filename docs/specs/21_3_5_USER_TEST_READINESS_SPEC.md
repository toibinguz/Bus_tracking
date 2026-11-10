# SPEC-21: Module 3.5 User-Test Readiness

**Status:** BLOCKED — remediation required before end-user test.  
**Scope:** Module 3.5 FastAPI adapter and static client only.  Modules 1, 2,
3.1, 3.2, and 3.3 remain frozen under SPEC-19.

## 1. Observed readiness

| Surface | Observed result | Readiness |
| --- | --- | --- |
| Application startup and launcher health | The public ASGI app starts; both health paths return the SPEC-20 payload. The existing black-box suite passed 4 tests. | Ready |
| Core HTTP surface | `/api/routes`, live vehicles, route shape, route stations, and station ETA are discovered and exercised by the current black-box suite. | Ready, subject to live upstream availability |
| Browser client data rendering | Provider-controlled values are interpolated into `innerHTML` / Leaflet popup HTML, including vehicle plate, station name, ETA display text, and provider message. | **P0 blocker** |
| Cross-origin policy | The app enables `allow_origins=["*"]` together with credentials. This is not the explicit local-demo policy required by SPEC-19. | **P1 blocker** |
| Browser-runtime verification | Current tests cover HTTP/launcher behavior but not a real browser rendering of hostile provider text or CORS response behavior. | **P1 blocker** |
| External assets/upstream | Leaflet, fonts, map tiles, and BusMap are network dependencies. The UI reports request failures, but cannot guarantee live map/data while offline or while the provider is unavailable. | P2 operating constraint |

The P0 finding means the demo is **not ready to hand to an end user**. The
current route catalogue is not a trust boundary: any upstream-originated text
must be treated as untrusted at the browser boundary.

## 2. Minimal remediation

### R1 — preserve text boundaries in the static client (P0)

The coder must ensure every provider-derived value reaches a DOM text node, not
an HTML parser. This applies at minimum to: vehicle `plate`, `next_station_id`,
timestamps displayed as text, station `station_name`, ETA `display_text`,
provider `message`, recommendation text, and all fields of the second-bus
card. It covers vehicle cards, vehicle popups, station popups, pinned-station
cards, and ETA popup content.

Static markup may stay static. For dynamic regions, use DOM-node construction
with `textContent`, or one documented escaping boundary used before any
provider string is interpolated. Do not change ETA calculation, polling
interval, endpoint schema, or BusMap-only/discrete behavior. Do not sanitize by
silently dropping/rewriting provider values.

### R2 — restrict the local-demo CORS policy (P1)

Replace the wildcard-plus-credentials policy with the documented local demo
origins `http://127.0.0.1:8000` and `http://localhost:8000`. Cross-origin
credentials are not required by this demo and must not be enabled. Same-origin
serving of `/` and `/api/*` remains supported. No upstream configuration or
frozen-module change is permitted.

### R3 — add independent browser-facing verification (P1)

`@blind_tester` must independently verify the public demo behavior after R1/R2.
The test harness may run a local browser or an equivalent DOM-capable runtime,
but it must not inspect the coder's source. It must feed API-shaped hostile
strings through the public UI flow and assert that they appear as literal text,
with no created element, event-handler execution, or script execution. It must
also issue browser-style requests with the two allowed origins and an unlisted
origin, asserting no wildcard credential response and no `Access-Control-
Allow-Origin` grant for the unlisted origin.

If an executable browser/DOM runner is unavailable locally, that is a test
environment blocker: record it and do not promote readiness based on a static
source check or HTTP-only test.

## 3. Required acceptance order

1. `@leaf_coder` implements R1/R2 only.
2. `@whitebox_auditor` verifies that all listed provider fields cross a text or
   single escaping boundary; checks no policy/math or frozen module changed.
3. `@blind_tester` writes/runs R3 plus the existing SPEC-20 black-box suite.
4. The orchestrator may mark module 3.5 **ready for user test** only after both
   reports pass and `pytest tests -q -p no:cacheprovider` exits zero.

## 4. Manual end-user smoke check after acceptance

Start `run_demo.ps1`, open the root page, select a route and direction, inspect
the route line/stations/vehicle count, pin one station, and confirm the ETA or
an explicit no-live-data state. A missing BusMap response or missing external
map tile is an operational message, not permission to fabricate data.
