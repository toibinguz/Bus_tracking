"""
Experimental audit: Test querying BusMap by route (`route_bus_gps`) vs querying by vehicle (`vehicle_hn/get`).
Check authentication, proof requirements, rate-limits, and response stability.
"""
import ssl
import socket
import json
import time

HOST = "api.busmap.city"
ssl_ctx = ssl.create_default_context()

def test_route_query(route_id, direction, with_proof=False, epoch="", proof=""):
    headers = [
        f"GET /v2/public/busmap/route_bus_gps?regionCode=hn&routeId={route_id}&direction={direction} HTTP/1.1",
        f"Host: {HOST}",
        "language: vi",
        "client-version: android|20600",
        "device-id: 7ab54c3ba04cceac",
        "package-name: com.t7.busmaphn",
        "Connection: close",
    ]
    if with_proof:
        headers.append(f"epoch: {epoch}")
        headers.append(f"proof: {proof}")
    req = "\r\n".join(headers) + "\r\n\r\n"
    
    t0 = time.time()
    try:
        with socket.create_connection((HOST, 443), timeout=5.0) as s:
            with ssl_ctx.wrap_socket(s, server_hostname=HOST) as ss:
                ss.sendall(req.encode("utf-8"))
                resp = b""
                while True:
                    d = ss.recv(4096)
                    if not d:
                        break
                    resp += d
        dt = time.time() - t0
        head, _, body = resp.partition(b"\r\n\r\n")
        status_line = head.decode("latin1", errors="ignore").splitlines()[0] if head else "No header"
        body_str = body.decode("utf-8", errors="ignore")[:300]
        return status_line, dt, body_str
    except Exception as e:
        return "ERROR", 0, str(e)

print("1. Querying route_bus_gps WITHOUT epoch/proof (Route 1, dir 1):")
st, dt, b = test_route_query(1, 1, with_proof=False)
print("  Status:", st, f"({dt:.3f}s)")
print("  Body preview:", b)

print("\n2. Querying route_bus_gps WITH legacy epoch/proof from archive:")
st2, dt2, b2 = test_route_query(1, 1, with_proof=True, epoch="1791382691939", proof="a35f2c368f895176575b575b6bf43739")
print("  Status:", st2, f"({dt2:.3f}s)")
print("  Body preview:", b2)
