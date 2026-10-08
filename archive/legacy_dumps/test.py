import ssl
import socket

# Cấu hình máy chủ
host = "api.busmap.city"
port = 443

# Chuỗi raw request (lưu ý các dòng phải kết thúc bằng \r\n và kết thúc request bằng \r\n\r\n)
raw_request = (
    "GET /v2/public/busmap/vehicle_hn/get?id=8831234 HTTP/1.1\r\n"
    "language: vi\r\n"
    "client-version: android|20600\r\n"
    "device-id: 7ab54c3ba04cceac\r\n"
    "package-name: com.t7.busmaphn\r\n"
    "Host: api.busmap.city\r\n"
    "Connection: close\r\n"
    "Accept-Encoding: identity\r\n"
    "User-Agent: okhttp/4.12.0\r\n"
    "If-Modified-Since: Thu, 24 Sep 2026 13:37:07 GMT\r\n\r\n"
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