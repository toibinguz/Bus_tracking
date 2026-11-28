"""Standalone CLI Worker cho Speed Layer (tách biệt hoàn toàn khỏi FastAPI/Uvicorn)."""

import argparse
import os
from pathlib import Path
import signal
import sys
import threading
from typing import Optional

from modules.eta.serving.serving_service import BusMapServingService
from modules.eta.serving.speed_poller import SPEED_POLL_INTERVAL_SEC, SpeedLayerPoller
from modules.eta.serving.speed_view_store import SpeedViewStore, default_speed_view_db_path


def run_worker(
    db_path: Optional[str] = None,
    view_db_path: Optional[str] = None,
    poll_interval_sec: float = SPEED_POLL_INTERVAL_SEC,
) -> int:
    """Khởi chạy vòng lặp Speed Layer độc lập ghi xuống `speed_view.db` cho đến khi nhận SIGINT/SIGTERM."""
    resolved_view_db = Path(view_db_path).expanduser().resolve() if view_db_path else default_speed_view_db_path(db_path)
    store = SpeedViewStore(resolved_view_db, create_if_missing=True)
    service = BusMapServingService(db_path=db_path, load_model=False)
    poller = SpeedLayerPoller(service, poll_interval_sec=poll_interval_sec, view_store=store)

    stop_event = threading.Event()

    def _request_stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    print(
        f"[SpeedWorker] View DB: {resolved_view_db} | routes={len(service.get_poller_route_ids())}",
        flush=True,
    )
    poller.start()
    try:
        while not stop_event.is_set():
            stop_event.wait(0.5)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        worker_thread = poller._thread
        poller.stop(timeout=0.5)
        try:
            store.save_health(poller._writer_session_id, os.getpid(), poller.get_health_snapshot(), poller._now_fn())
        except Exception:
            pass
        if worker_thread is None or not worker_thread.is_alive():
            store.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Hanoi Bus Speed Layer Standalone Worker (45s)")
    parser.add_argument("--db-path", default=os.environ.get("SERVING_DB_PATH") or None, help="Đường dẫn Serving SQLite DB")
    parser.add_argument("--view-db", default=os.environ.get("SPEED_VIEW_DB_PATH") or None, help="Đường dẫn Speed View WAL DB")
    parser.add_argument("--interval", type=float, default=SPEED_POLL_INTERVAL_SEC, help="Chu kỳ quét Speed Layer (giây)")
    args = parser.parse_args()
    sys.exit(run_worker(db_path=args.db_path, view_db_path=args.view_db, poll_interval_sec=args.interval))


if __name__ == "__main__":
    main()
