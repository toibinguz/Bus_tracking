# SPEC-22: Live Demo Backend Lifecycle and Direction-1 Contract

**Status:** READY FOR VERIFICATION; no production-code change is justified
until a lifecycle failure is reproduced through the documented launcher.

**Scope:** Module 3.5, `run_demo.ps1`, and the existing BusMap-only HTTP
contract. Modules 1, 2, and 3.1--3.3 remain frozen under SPEC-19.

## 1. Product decision

The local demo uses live BusMap data only:

1. Selecting a route and direction requests and displays the vehicles that
   BusMap currently reports for that selection.
2. Selecting a station requests ETA for that station and selection.
3. If BusMap reports no vehicles, the UI must say that live data is absent; it
   must not substitute replay data or manufacture an ETA.

This is a user-test contract, not a promise that every route/direction has a
vehicle at every instant.

## 2. Lifecycle evidence

Observed in the current workspace on 2026-11-10:

| Check | Result | Meaning |
| --- | --- | --- |
| `python -m uvicorn ... --port 8000` | Process completed application startup, then exited with `WinError 10048` while binding `127.0.0.1:8000`. | A port-8000 collision produces the user-visible “started then stopped” sequence. |
| Same ASGI app on port 8011 | Uvicorn remained running; `GET /api/v1/health` and `GET /` returned 200. | The application lifespan does not independently terminate the backend. |
| `run_demo.ps1` | Starts Uvicorn in the foreground and checks an existing process on 8000 first. | Closing its terminal, a port collision/race, or launching Uvicorn outside this script are distinct operational paths. |

The observed failure is therefore port ownership, not a demonstrated FastAPI
or BusMap lifecycle defect. A stale process created by a test harness can
produce the same collision and must not be mistaken for a product failure.

## 3. Minimal operational resolution

No application retry loop, background daemon, or new port configuration is
permitted for this milestone. Before a local user test:

1. Start the demo only with `run_demo.bat` or `run_demo.ps1` from repository
   root, and keep that terminal open.
2. If it reports a compatible server on port 8000, use that server rather than
   launching another instance.
3. If startup reports a port collision but health is not compatible, record the
   owning PID/command line and stop only that known stale demo/test process;
   start the launcher once more.
4. A repeated collision with no listener requires a new evidence-based issue;
   do not add a sleep, forced process kill, or arbitrary alternate port.

## 4. Public behavior to verify

| ID | User action | Expected observable result |
| --- | --- | --- |
| L-01 | Start documented launcher and keep its terminal open. | `GET /api/v1/health` is 200 with `status: "healthy"`; a listener remains on 127.0.0.1:8000. |
| L-02 | Open `/`, choose a route and direction. | The route line/stations load and the vehicle panel shows the exact live count, including an explicit zero-live-data state. |
| L-03 | Choose a station on that route. | The demo requests station ETA and displays provider-derived ETA, or an explicit no-approaching-vehicle/no-ETA state. |
| L-04 | Change direction or route. | Prior route markers/station selection are cleared and the new live selection is requested; no replay/fabricated value appears. |
| L-05 | Close the launcher terminal. | The backend stops; this is expected foreground-process behavior, not an app crash. |

## 5. Implementation decision gate

The current code already defines the L-01--L-05 interaction paths. A leaf
coder may change Module 3.5 only after a reproducible failure identifies an
observable contract violation (for example, a live-result error incorrectly
shown as zero vehicles). The spec does not authorize a fake data fallback,
ETA-policy change, upstream-module change, or speculative lifecycle patch.

## 6. Acceptance sequence

1. `@blind_tester` verifies L-01--L-05 against the launcher and public HTTP/UI
   surface without reading production code.
2. If a product-code change becomes necessary, use the normal sequence:
   architect amendment, leaf implementation, white-box audit, then independent
   black-box test.
3. The manual user test may proceed once L-01 is demonstrated on the user's
   machine; a live upstream empty response is a valid result under L-02/L-03.
