"""Bounded private-network WebHDFS transport for HDFS artifacts."""
import json
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class PrivateWebHdfs:
    def __init__(self, base_url: str = "http://namenode:9870", user_name: str = "root"):
        self.base_url = base_url.rstrip("/")
        self.user_name = user_name

    def url(self, path: str, operation: str) -> str:
        if path.startswith("hdfs://namenode:8020"):
            path = path[len("hdfs://namenode:8020"):]
        if not path.startswith("/bus-eta/v1/"):
            raise ValueError("unexpected artifact namespace")
        return (
            f"{self.base_url}/webhdfs/v1/{quote(path.lstrip('/'))}"
            f"?op={operation}&user.name={quote(self.user_name)}"
        )

    def exists(self, path: str) -> bool:
        try:
            with build_opener().open(self.url(path, "GETFILESTATUS"), timeout=20) as response:
                json.loads(response.read())["FileStatus"]
            return True
        except HTTPError as error:
            if error.code == 404:
                return False
            raise

    def read(self, path: str, max_bytes=None) -> bytes:
        with build_opener().open(self.url(path, "OPEN"), timeout=20) as response:
            content = response.read() if max_bytes is None else response.read(max_bytes + 1)
        if max_bytes is not None and len(content) > max_bytes:
            raise ValueError("remote object exceeds configured byte limit")
        return content

    def create(self, path: str, content: bytes) -> None:
        temporary = path + ".upload-" + str(uuid4())
        request = Request(self.url(temporary, "CREATE&overwrite=false"), data=b"", method="PUT")
        try:
            build_opener(_NoRedirect()).open(request, timeout=20)
        except HTTPError as error:
            if error.code != 307:
                raise
            location = error.headers["Location"]
        else:
            raise RuntimeError("expected DataNode redirect")
        with build_opener().open(Request(location, data=content, method="PUT"), timeout=20):
            pass
        destination = path[len("hdfs://namenode:8020"):] if path.startswith("hdfs://namenode:8020") else path
        with build_opener().open(
            Request(self.url(temporary, "RENAME&destination=" + quote(destination, safe="")), data=b"", method="PUT"),
            timeout=20,
        ) as response:
            if not json.loads(response.read())["boolean"]:
                raise RuntimeError("immutable artifact rename failed")
