"""SQLite WAL bridge (Shared Real-time View) giữa Speed Layer Worker và Serving Layer."""

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union
from uuid import uuid4

from config.system_config import DEFAULT_DB_PATH
from modules.eta.serving.speed_poller import is_operating_hours

logger = logging.getLogger(__name__)

DEFAULT_SPEED_VIEW_TTL_SEC = 3600.0
DEFAULT_HEALTH_STALE_SEC = 120.0

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS speed_batches (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    writer_session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    route_id INTEGER NOT NULL,
    dir_int INTEGER NOT NULL,
    observed_epoch REAL NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_speed_batches_created ON speed_batches(created_at);

CREATE TABLE IF NOT EXISTS recent_timbus_focus (
    route_id INTEGER NOT NULL,
    dir_int INTEGER NOT NULL,
    plate_norm TEXT NOT NULL,
    tb_ts REAL NOT NULL,
    PRIMARY KEY (route_id, dir_int, plate_norm)
);
CREATE INDEX IF NOT EXISTS idx_timbus_focus_ts ON recent_timbus_focus(tb_ts);

CREATE TABLE IF NOT EXISTS live_incidents_snapshot (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    payload_json TEXT NOT NULL,
    fetched_at TEXT,
    updated_epoch REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS poller_health (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    writer_session_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    heartbeat_epoch REAL NOT NULL,
    snapshot_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS store_meta (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    db_lifecycle_id TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def default_speed_view_db_path(serving_db_path: Optional[Union[str, Path]] = None) -> Path:
    """Đường dẫn mặc định cho `speed_view.db` đặt cùng thư mục với Serving DB."""
    override = (os.environ.get("SPEED_VIEW_DB_PATH") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    base = Path(serving_db_path) if serving_db_path else Path(DEFAULT_DB_PATH)
    return base.expanduser().resolve().parent / "speed_view.db"


class SpeedViewStore:
    """Cầu nối SQLite WAL 2 chiều giữa tiến trình Speed Layer và Serving Layer."""

    def __init__(self, db_path: Union[str, Path], create_if_missing: bool = True):
        self.db_path = Path(db_path).expanduser().resolve()
        self._create_if_missing = bool(create_if_missing)
        self._local = threading.local()
        self._conn_lock = threading.Lock()
        self._conns: Dict[int, Tuple[sqlite3.Connection, int]] = {}
        self._schema_initialized = False
        if self._create_if_missing:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    @staticmethod
    def _configure_connection(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA busy_timeout = 3000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")

    def _current_inode_key(self) -> int:
        try:
            st = self.db_path.stat()
            return hash((st.st_ino, getattr(st, "st_ctime_ns", 0), st.st_dev))
        except FileNotFoundError:
            return 0

    def _get_conn(self, create_now: bool = False) -> Optional[sqlite3.Connection]:
        tid = threading.get_ident()
        exists = self.db_path.exists()
        if not exists and not (create_now or self._create_if_missing):
            return None
        if not exists and (create_now or self._create_if_missing):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        inode_key = self._current_inode_key()
        entry = getattr(self._local, "conn_entry", None)
        if entry is not None:
            conn, prev_inode = entry
            if prev_inode == inode_key or not exists:
                return conn
            try:
                conn.close()
            except Exception:
                pass
            with self._conn_lock:
                self._conns.pop(tid, None)
            self._local.conn_entry = None
            self._schema_initialized = False

        conn = sqlite3.connect(str(self.db_path), timeout=3.0, isolation_level=None, check_same_thread=False)
        self._configure_connection(conn)
        if (create_now or self._create_if_missing) and not self._schema_initialized:
            self._init_schema(conn)
            self._schema_initialized = True
        new_inode = self._current_inode_key()
        self._local.conn_entry = (conn, new_inode)
        with self._conn_lock:
            self._conns[tid] = (conn, new_inode)
        return conn

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            "INSERT OR IGNORE INTO store_meta (singleton_id, db_lifecycle_id, created_at) VALUES (1, ?, ?)",
            (uuid4().hex, time.time()),
        )

    def _ensure_schema(self) -> None:
        conn = self._get_conn(create_now=True)
        if conn is not None and not self._schema_initialized:
            self._init_schema(conn)
            self._schema_initialized = True

    @contextmanager
    def _write_tx(self):
        conn = self._get_conn(create_now=True)
        assert conn is not None
        if not self._schema_initialized:
            self._init_schema(conn)
            self._schema_initialized = True
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

    def close(self) -> None:
        with self._conn_lock:
            conns = list(self._conns.values())
            self._conns.clear()
        for conn, _ in conns:
            try:
                conn.close()
            except Exception:
                pass
        self._local = threading.local()

    # ------------------------------------------------------------------ Writers (Speed Layer)
    def append_busmap_batch(
        self,
        writer_session_id: str,
        route_id: int,
        dir_int: int,
        observed_epoch: float,
        vehicles: Iterable[Any],
        created_at: Optional[float] = None,
    ) -> int:
        payload_list = [
            v.model_dump(mode="json") if hasattr(v, "model_dump") else dict(v)
            for v in vehicles
        ]
        if not payload_list:
            return 0
        payload_json = json.dumps(payload_list, ensure_ascii=False, separators=(",", ":"))
        now_ts = float(observed_epoch if created_at is None else created_at)
        with self._write_tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO speed_batches
                    (writer_session_id, kind, route_id, dir_int, observed_epoch, payload_json, created_at)
                VALUES (?, 'busmap_route', ?, ?, ?, ?, ?)
                """,
                (writer_session_id, int(route_id), int(dir_int), float(observed_epoch), payload_json, now_ts),
            )
            return int(cur.lastrowid or 0)

    def append_timbus_hit(
        self,
        writer_session_id: str,
        route_id: int,
        dir_int: int,
        bm_v: Any,
        tb_rec: Any,
        now_epoch: float,
    ) -> int:
        bm_payload = bm_v.model_dump(mode="json") if hasattr(bm_v, "model_dump") else dict(bm_v)
        tb_payload = {
            "plate": getattr(tb_rec, "plate", getattr(bm_v, "plate", "")),
            "route": getattr(tb_rec, "route", ""),
            "speed_kmh": float(getattr(tb_rec, "speed_kmh", 0.0)),
            "latitude": float(getattr(tb_rec, "latitude", 0.0)),
            "longitude": float(getattr(tb_rec, "longitude", 0.0)),
            "fetch_timestamp": getattr(tb_rec, "fetch_timestamp", None),
        }
        payload_json = json.dumps(
            {"bm_v": bm_payload, "tb_rec": tb_payload},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._write_tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO speed_batches
                    (writer_session_id, kind, route_id, dir_int, observed_epoch, payload_json, created_at)
                VALUES (?, 'timbus_hit', ?, ?, ?, ?, ?)
                """,
                (writer_session_id, int(route_id), int(dir_int), float(now_epoch), payload_json, float(now_epoch)),
            )
            return int(cur.lastrowid or 0)

    def save_incidents(self, payload: dict, updated_epoch: float) -> None:
        if not isinstance(payload, dict):
            return
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        fetched_at = payload.get("fetched_at")
        with self._write_tx() as conn:
            conn.execute(
                """
                INSERT INTO live_incidents_snapshot (singleton_id, payload_json, fetched_at, updated_epoch)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at,
                    updated_epoch = excluded.updated_epoch
                """,
                (payload_json, str(fetched_at) if fetched_at else None, float(updated_epoch)),
            )

    def save_health(
        self,
        writer_session_id: str,
        pid: int,
        snapshot: Dict[str, Any],
        heartbeat_epoch: float,
    ) -> None:
        snapshot_json = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        with self._write_tx() as conn:
            conn.execute(
                """
                INSERT INTO poller_health (singleton_id, writer_session_id, pid, heartbeat_epoch, snapshot_json)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    writer_session_id = excluded.writer_session_id,
                    pid = excluded.pid,
                    heartbeat_epoch = excluded.heartbeat_epoch,
                    snapshot_json = excluded.snapshot_json
                """,
                (writer_session_id, int(pid), float(heartbeat_epoch), snapshot_json),
            )

    def prune_expired(self, now_epoch: float, ttl_sec: float = DEFAULT_SPEED_VIEW_TTL_SEC) -> int:
        cutoff = float(now_epoch) - float(ttl_sec)
        removed = 0
        with self._write_tx() as conn:
            c1 = conn.execute("DELETE FROM speed_batches WHERE created_at < ?", (cutoff,))
            c2 = conn.execute("DELETE FROM recent_timbus_focus WHERE tb_ts < ?", (cutoff,))
            removed = int(c1.rowcount or 0) + int(c2.rowcount or 0)
        conn = self._get_conn()
        if conn is not None:
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.OperationalError:
                pass
        return removed

    # --------------------------------------------------------- Bidirectional TimBus Focus Leases
    def record_focus_timbus_hits(
        self,
        route_id: int,
        dir_int: int,
        plates_with_ts: Iterable[Tuple[str, float]],
    ) -> int:
        rows = [
            (int(route_id), int(dir_int), str(plate_norm), float(tb_ts))
            for plate_norm, tb_ts in plates_with_ts
            if plate_norm
        ]
        if not rows:
            return 0
        try:
            with self._write_tx() as conn:
                conn.executemany(
                    """
                    INSERT INTO recent_timbus_focus (route_id, dir_int, plate_norm, tb_ts)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(route_id, dir_int, plate_norm) DO UPDATE SET
                        tb_ts = MAX(recent_timbus_focus.tb_ts, excluded.tb_ts)
                    """,
                    rows,
                )
            return len(rows)
        except sqlite3.OperationalError as exc:
            logger.warning("Không ghi được recent_timbus_focus (non-fatal): %s", exc)
            return 0

    def get_recent_focus_plates(
        self,
        route_id: int,
        dir_int: int,
        now_epoch: float,
        max_age_sec: float = 45.0,
    ) -> Set[str]:
        conn = self._get_conn()
        if conn is None:
            return set()
        cutoff = float(now_epoch) - float(max_age_sec)
        try:
            rows = conn.execute(
                """
                SELECT plate_norm
                FROM recent_timbus_focus
                WHERE route_id = ? AND dir_int = ? AND tb_ts > ?
                """,
                (int(route_id), int(dir_int), cutoff),
            ).fetchall()
            return {str(r[0]) for r in rows}
        except sqlite3.OperationalError:
            return set()

    # ------------------------------------------------------------------ Readers (Serving Layer)
    def fetch_batches_since(
        self,
        last_seq: int,
        known_session_id: Optional[str],
        min_epoch: float,
        known_db_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str], Optional[str], bool]:
        conn = self._get_conn()
        if conn is None:
            return [], 0, None, None, False
        effective_last_seq = int(last_seq)
        session_reset = False
        try:
            try:
                meta_row = conn.execute(
                    "SELECT db_lifecycle_id FROM store_meta WHERE singleton_id = 1"
                ).fetchone()
                current_db_id = str(meta_row[0]) if meta_row else None
            except sqlite3.OperationalError:
                current_db_id = None

            health_row = conn.execute(
                "SELECT writer_session_id FROM poller_health WHERE singleton_id = 1"
            ).fetchone()
            current_session = str(health_row[0]) if health_row else None

            if current_session is None:
                latest = conn.execute(
                    "SELECT writer_session_id FROM speed_batches ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                current_session = str(latest[0]) if latest else None

            max_seq_row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM speed_batches").fetchone()
            max_seq = int(max_seq_row[0]) if max_seq_row else 0

            # Reset cursor if DB file was replaced (new db_lifecycle_id) or truncated (max_seq < cursor),
            # even if the replacement DB already accumulated more rows than effective_last_seq.
            if (known_db_id is not None and current_db_id is not None and current_db_id != known_db_id) or (
                max_seq < effective_last_seq
            ):
                effective_last_seq = 0
                session_reset = True

            rows = conn.execute(
                """
                SELECT seq, writer_session_id, kind, route_id, dir_int, observed_epoch, payload_json
                FROM speed_batches
                WHERE seq > ? AND observed_epoch >= ?
                ORDER BY seq ASC
                """,
                (effective_last_seq, float(min_epoch)),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("Không đọc được speed_batches từ %s (sẽ thử lại): %s", self.db_path, exc)
            return [], int(last_seq), known_session_id, known_db_id, False

        batches: List[Dict[str, Any]] = []
        new_last_seq = effective_last_seq
        for seq, sess_id, kind, route_id, dir_int, obs_epoch, payload_json in rows:
            if known_session_id is None and current_session is None:
                current_session = str(sess_id)
            batches.append(
                {
                    "seq": int(seq),
                    "writer_session_id": str(sess_id),
                    "kind": str(kind),
                    "route_id": int(route_id),
                    "dir_int": int(dir_int),
                    "observed_epoch": float(obs_epoch),
                    "payload": json.loads(payload_json),
                }
            )
            new_last_seq = int(seq)

        return batches, new_last_seq, current_session, current_db_id, session_reset

    def load_incidents(self) -> Optional[Tuple[dict, float]]:
        conn = self._get_conn()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT payload_json, updated_epoch FROM live_incidents_snapshot WHERE singleton_id = 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if not row:
            return None
        return json.loads(row[0]), float(row[1])

    def load_health(
        self,
        now_epoch: float,
        stale_after_sec: float = DEFAULT_HEALTH_STALE_SEC,
    ) -> Dict[str, Any]:
        conn = self._get_conn()
        base_waiting = {
            "mode": "external",
            "status": "waiting_external",
            "operating_hours": is_operating_hours(now_epoch),
            "cycle_count": 0,
            "last_cycle_epoch": None,
            "last_cycle_age_sec": None,
            "last_cycle_duration_sec": None,
            "heartbeat_epoch": None,
            "heartbeat_age_sec": None,
            "circuit_state": "CLOSED",
            "circuit_remaining_sec": 0.0,
            "error_streak": 0,
            "last_error": None,
            "counts": {},
            "gap_routes_top": {},
            "incidents": {"fetched_at": None, "count": 0, "last_sync_epoch": None, "error": None},
        }
        if conn is None:
            return base_waiting
        try:
            row = conn.execute(
                "SELECT writer_session_id, pid, heartbeat_epoch, snapshot_json FROM poller_health WHERE singleton_id = 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return base_waiting
        if not row:
            return base_waiting

        writer_session_id, pid, heartbeat_epoch, snapshot_json = row
        snap = json.loads(snapshot_json)
        hb_epoch = float(heartbeat_epoch)
        hb_age = round(max(0.0, float(now_epoch) - hb_epoch), 1)
        last_ep = snap.get("last_cycle_epoch")
        snap["mode"] = "external"
        snap["worker_pid"] = int(pid)
        snap["writer_session_id"] = str(writer_session_id)
        snap["heartbeat_epoch"] = hb_epoch
        snap["heartbeat_age_sec"] = hb_age
        snap["operating_hours"] = is_operating_hours(now_epoch)
        snap["last_cycle_age_sec"] = (
            round(max(0.0, float(now_epoch) - float(last_ep)), 1)
            if last_ep is not None
            else None
        )
        if snap["operating_hours"] and hb_age > float(stale_after_sec):
            snap["status"] = "stale"
        return snap


class SpeedViewSyncer:
    """Thread đọc incremental nhẹ cho Serving Layer khi chạy ở `SPEED_LAYER_MODE=external`."""

    def __init__(
        self,
        service: Any,
        store: SpeedViewStore,
        poll_interval_sec: float = 2.0,
        sweep_interval_sec: float = 60.0,
    ):
        self._service = service
        self._store = store
        self.poll_interval_sec = max(0.2, float(poll_interval_sec))
        self.sweep_interval_sec = max(1.0, float(sweep_interval_sec))
        self._last_sweep_mono = time.monotonic()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> int:
        """Bootstrap dữ liệu hiện có từ `speed_view.db` rồi chạy thread đồng bộ 2s."""
        replayed = self._service.sync_from_speed_view()
        self._last_sweep_mono = time.monotonic()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return replayed
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="SpeedViewSyncer", daemon=True)
            self._thread.start()
        return replayed

    def stop(self, timeout: float = 0.5) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        with self._lock:
            self._thread = None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._stop_event.wait(self.poll_interval_sec):
                break
            try:
                self._service.sync_from_speed_view()
                now_mono = time.monotonic()
                if (now_mono - self._last_sweep_mono) >= self.sweep_interval_sec:
                    sweeper = getattr(self._service, "sweep_stale_state", None)
                    if callable(sweeper):
                        sweeper(time.time())
                    self._last_sweep_mono = now_mono
            except Exception as exc:
                logger.warning("SpeedViewSyncer sync failed: %s", exc)
