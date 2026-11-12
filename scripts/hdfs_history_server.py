"""Single-worker HTTP service backed by a long-lived Spark session."""
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import BoundedSemaphore
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.history_query import query_route_speed, query_snapshot_speed, validate_request, validate_snapshot_id


def handler_for(spark):
    executor = ThreadPoolExecutor(max_workers=1)
    available = BoundedSemaphore(1)
    deadline_seconds = 20
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            if url.path != "/api/history/route-speed":
                return self.reply(404, {"error": "not_found"})
            params = parse_qs(url.query, keep_blank_values=True)
            required = {"route_code", "date_from", "date_to"}
            if not required.issubset(params) or set(params)-required-{'snapshot_id'} or any(len(v) != 1 for v in params.values()):
                return self.reply(400, {"error": "invalid_parameters"})
            args = [params[key][0] for key in ("route_code", "date_from", "date_to")]
            try:
                validate_request(*args)
                if 'snapshot_id' in params:
                    validate_snapshot_id(params['snapshot_id'][0])
            except ValueError as error:
                return self.reply(400, {"error": "invalid_parameters", "detail": str(error)})
            try:
                if not available.acquire(blocking=False):
                    return self.reply(503, {"error": "query_busy"})
                group = str(uuid4())
                def run():
                    try:
                        if hasattr(spark, 'sparkContext'):
                            spark.sparkContext.setJobGroup(group, 'bounded history query', interruptOnCancel=True)
                        if 'snapshot_id' in params:
                            return query_snapshot_speed(spark, params['snapshot_id'][0], *args)
                        return query_route_speed(spark, *args)
                    finally:
                        available.release()
                future = executor.submit(run)
                try:
                    result = future.result(timeout=deadline_seconds)
                except TimeoutError:
                    spark.sparkContext.cancelJobGroup(group)
                    raise RuntimeError('history query deadline exceeded')
                self.reply(200, result)
            except Exception as error:
                print(f"history query failed: {error}", file=sys.stderr, flush=True)
                self.reply(503, {"error": "hdfs_unavailable"})

        def reply(self, status, payload):
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Handler


def main():
    from pyspark.sql import SparkSession
    spark = (SparkSession.builder.appName("bus-eta-history-api")
             .config('spark.driver.host', 'history-api')
             .config('spark.driver.bindAddress', '0.0.0.0')
             .config('spark.hadoop.ipc.client.connect.timeout', '3000')
             .config('spark.hadoop.ipc.client.connect.max.retries', '1')
             .config('spark.hadoop.ipc.client.connect.max.retries.on.timeouts', '1')
             .config('spark.hadoop.dfs.client.socket-timeout', '5000')
             .config('spark.executor.memory', '512m')
             .config('spark.cores.max', '2').getOrCreate())
    try:
        HTTPServer(("0.0.0.0", 8090), handler_for(spark)).serve_forever()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
