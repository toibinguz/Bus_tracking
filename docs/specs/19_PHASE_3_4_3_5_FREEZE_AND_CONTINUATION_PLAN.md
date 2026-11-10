# SPEC-19: Freeze and Continuation Plan for Modules 3.4 and 3.5

**Status:** READY FOR IMPLEMENTATION  
**Audit date:** 2026-11-10  
**Scope:** freeze upstream work; complete the serving-to-web integration only.

## 1. Decision and boundaries

Effective immediately, no feature, schema, model, pipeline, crawler, lakehouse,
or data-contract change is in scope for Modules 1, 2, 3.1, 3.2, or 3.3.
Their existing artifacts are read-only dependencies for this phase.

Allowed work is limited to:

1. Module 3.4 public serving facade and its existing dependencies.
2. Module 3.5 FastAPI adapter, launcher contract, and existing static client.
3. Independently authored black-box tests under `tests/` for this public
   contract.
4. Documentation/status updates that report the verified result.

An upstream defect discovered during this phase is recorded as a blocker; it is
not repaired in the frozen modules without an explicit unfreeze decision.

## 2. Current state (evidence)

| Surface | State | Evidence |
| --- | --- | --- |
| Split 3.4 design | Present, not public | `dto.py`, `data_access.py`, `live_feed.py`, `frenet.py`, `online_features.py`, `model_runtime.py`, `eta_policy.py`, and `serving_service.py` exist. |
| Running 3.5 adapter | Still monolithic | `app.py` imports `busmap_service.py`, not the package facade/new `serving_service.py`. |
| Public endpoints | Present but unverified | `/api/routes`, `/api/live-vehicles`, `/api/route-shape`, `/api/route-stations`, and `/api/station-eta` are declared by `app.py`. |
| Health/launcher contract | Blocked | App declares `/api/health` with `status: "ok"`; `run_demo.ps1` probes `/api/v1/health` and expects `"healthy"`. |
| Browser behavior | Implemented, unverified | `static/app.js` polls live vehicles and consumes the route/station/ETA endpoints. |
| Verification | Absent | `tests/` contains no test files; current docs therefore cannot certify runtime behavior. |

## 3. Mandatory work order

### M1 — Establish one 3.4 public facade

`@leaf_coder` must make the app import the split public contract, either from
the package `__init__` facade or from a deliberately thin compatibility facade.
The choice must preserve the declared endpoint request/response schemas and
must not duplicate serving logic. `busmap_service.py` cannot remain the active
implementation after this milestone.

**Verify:** static import inspection shows `app.py` no longer imports the
monolith; each declared API route resolves through the split service.

### M2 — Restore the launcher health contract

Define one health payload and make both `/api/health` and `/api/v1/health`
return it. It must satisfy the existing launcher condition (`status ==
"healthy"`) without changing the frozen upstream modules.

**Verify:** black-box GETs to both paths return HTTP 200 and the same healthy
payload; `run_demo.ps1` recognizes an already-running compatible server.

### M3 — Make the web adapter safe and contract-faithful

Limit changes to SPEC-16's existing scope: explicit localhost CORS policy
without wildcard credentials, HTML escaping at every client-side insertion of
provider data, and removal only of CSS/JS made dead by this work. Preserve
BusMap-only discrete polling and the approved CDN references.

**Verify:** endpoint schema tests pass; an injected HTML-looking station or
plate value renders as text; browser requests from an unapproved origin do not
receive a wildcard-with-credentials response.

### M4 — Independent verification and status promotion

`@blind_tester` writes black-box tests from SPEC-08, SPEC-15, and SPEC-16,
without reading the implementation. Minimum suites are the five files listed
in SPEC-16 section 6. The coder fixes only demonstrated failures. Documentation
may change from "verification pending" to "implemented" only after the full
suite passes and raw logs are retained.

**Verify:** `pytest tests` exits 0, includes health, endpoint validation,
BusMap-discrete UI, ETA response, and safety/CORS cases.

## 4. Stop conditions

- Missing/invalid frozen database, model, or upstream BusMap data: report the
  dependency and stop; do not fabricate a fallback dataset or alter Modules 1–3.3.
- API schema divergence between the monolith and split facade: preserve the
  documented public schema and resolve only in Module 3.4/3.5.
- Any requested model retraining, lakehouse rebuild, or crawler change requires
  an explicit unfreeze decision.

## 5. Definition of done

1. 3.5 imports the split 3.4 facade, not the legacy implementation.
2. Both health paths satisfy the launcher contract.
3. No TimBus, browser interpolation, or new upstream data source is introduced.
4. The black-box suite exists and passes from a clean test invocation.
5. The module README and SPEC-16 state only the verified completion status.
