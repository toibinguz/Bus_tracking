import ssl
import socket

import time

# Cấu hình máy chủ
host = "api.busmap.city"
port = 443

# Lấy epoch thời gian thực hiện tại (milliseconds)
current_epoch = int(time.time() * 1000)
proof = "3664fc15390a6a8d81df56b52c6b4f4e"

# Chuỗi raw request với epoch hiện tại và giữ nguyên proof
raw_request = (
    "GET /v2/public/busmap/route_bus_gps?regionCode=hn&routeId=708&direction=0 HTTP/1.1\r\n"
    "language: vi\r\n"
    f"epoch: {current_epoch}\r\n"
    "client-version: android|20600\r\n"
    f"proof: {proof}\r\n"
    "device-id: 7ab54c3ba04cceac\r\n"
    "package-name: com.t7.busmaphn\r\n"
    "Host: api.busmap.city\r\n"
    "Connection: close\r\n"
    "Accept-Encoding: identity\r\n"
    "User-Agent: okhttp/4.12.0\r\n"
    "If-Modified-Since: Thu, 01 Jan 2026 00:00:00 GMT\r\n\r\n"
)



# Tạo kết nối TCP socket và bọc SSL
context = ssl.create_default_context()
with socket.create_connection((host, port)) as sock:
  with context.wrap_socket(sock, server_hostname=host) as ssock:
    # Gửi gói tin RAW
    ssock.sendall(raw_request.encode("utf-8"))

    # Nhận phản hồi từ server
    response = b""
    while True:
      data = ssock.recv(4096)
      if not data:
        break
      response += data

    # In kết quả phản hồi
    print(response.decode("utf-8", errors="ignore"))