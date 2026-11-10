"""Small WebHDFS client used only for immutable Bronze uploads."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .receipt import file_sha256, load_receipt, write_receipt


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


@dataclass(frozen=True)
class WebHdfsUploader:
    base_url: str
    bronze_root: str = "/bus-eta/v1/bronze/telemetry"

    def _url(self, hdfs_path: str, operation: str) -> str:
        return f"{self.base_url.rstrip('/')}/webhdfs/v1/{quote(hdfs_path.lstrip('/'))}?op={operation}"

    def _remote_status(self, hdfs_path: str) -> dict[str, Any] | None:
        request = Request(self._url(hdfs_path, "GETFILESTATUS"), method="GET")
        try:
            with build_opener().open(request) as response:
                return json.loads(response.read().decode("utf-8"))["FileStatus"]
        except HTTPError as error:
            if error.code == 404:
                return None
            raise

    def _remote_bytes(self, hdfs_path: str) -> bytes:
        with build_opener().open(Request(self._url(hdfs_path, "OPEN"), method="GET")) as response:
            return response.read()

    def _create(self, hdfs_path: str, content: bytes) -> None:
        create_request = Request(self._url(hdfs_path, "CREATE&overwrite=false"), data=b"", method="PUT")
        opener = build_opener(_NoRedirect())
        try:
            opener.open(create_request)
        except HTTPError as error:
            if error.code != 307:
                raise
            redirect_url = error.headers["Location"]
        else:
            raise RuntimeError("WebHDFS CREATE did not return a DataNode redirect")
        with build_opener().open(Request(redirect_url, data=content, method="PUT")):
            pass

    def upload(self, spool_file: str | Path) -> str:
        """Upload once, verify a collision byte-for-byte, then atomically record receipt."""
        spool_path = Path(spool_file)
        payload = spool_path.read_bytes()
        payload_hash = file_sha256(spool_path)
        receipt = load_receipt(spool_path)
        if receipt and receipt["sha256"] == payload_hash:
            return receipt["hdfs_path"]
        parent_parts = spool_path.parent.parts
        dt_part = next(part for part in parent_parts if part.startswith("dt="))
        hour_part = next(part for part in parent_parts if part.startswith("hr="))
        hdfs_path = f"{self.bronze_root}/{dt_part}/{hour_part}/{spool_path.name}"
        remote_status = self._remote_status(hdfs_path)
        if remote_status is None:
            self._create(hdfs_path, payload)
        elif int(remote_status["length"]) != len(payload) or file_sha256_bytes(self._remote_bytes(hdfs_path)) != payload_hash:
            raise RuntimeError(f"existing HDFS object differs from spool payload: {hdfs_path}")
        write_receipt(spool_path, hdfs_path, payload_hash)
        return hdfs_path


def file_sha256_bytes(content: bytes) -> str:
    from hashlib import sha256

    return sha256(content).hexdigest()
