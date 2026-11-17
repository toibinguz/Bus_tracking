#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
MODULE CHUẨN THAM CHIẾU: CLIENT VIỄN TRẮC XE BUÝT THỜI GIAN THỰC TIMBUS (BA GPS)
========================================================================================
Tài liệu bàn giao kỹ thuật cho nhóm phát triển sản phẩm (Product & Engineering Team).
Mã định danh gói mục tiêu: com.binhanh.bushanoi (Tìm Buýt - Phiên bản 5.6.0)
Endpoint: http://www.timbus.vn:9149/SearchBuyt/VehicleState

Hỗ trợ 2 chế độ:
  1. Thư viện Python (Importable Library): from tools.timbus_tracker import TimBusClient, BusRecord
  2. Công cụ dòng lệnh CLI: python tools/timbus_tracker.py --station 157 --routes "03A,25,32"
"""

import sys
import argparse
import base64
import urllib.request
import urllib.parse
import struct
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any

# Đảm bảo UTF-8 cho console Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ======================================================================================
# 1. ĐỊNH NGHĨA DTO (DATA TRANSFER OBJECT) THỰC THỂ PHƯƠNG TIỆN
# ======================================================================================

@dataclass
class BusRecord:
    """Thực thể đại diện cho một xe buýt đang hoạt động trên tuyến (tương đương class Lij; trong Dalvik).

    Lưu ý tên trường giữ nguyên để tương thích ngược; xem 3 property bên dưới để lấy đúng ngữ nghĩa:
    - `next_station_id`   -> `distance_to_queried_station_m` (cự ly mét tới đúng `station_id` vừa hỏi)
    - `distance_m`        -> `eta_to_queried_station_sec` (ETA giây tới `station_id` vừa hỏi)
    - `next_station_name` -> `destination_name` (tên bến cuối của chiều chạy)
    """
    plate: str                 # Biển kiểm soát (ví dụ: '29F05192')
    route: str                 # Mã hiệu tuyến buýt (ví dụ: '03A', '32', '04CT')
    next_station_id: int       # Tên cũ; thực tế là khoảng cách (mét) tới `station_id` đã truy vấn
    distance_m: int            # Tên cũ; thực tế là ETA dự kiến (giây) tới `station_id` đã truy vấn
    next_station_name: str     # Tên cũ; thực tế là tên bến cuối của chiều chạy đó
    speed_kmh: int             # Vận tốc tức thời đo bằng GPS hộp đen (0 - 255 km/h)
    latitude: float            # Vĩ độ WGS-84 (IEEE-754 Single-Precision Float, 6 chữ số thập phân)
    longitude: float           # Kinh độ WGS-84 (IEEE-754 Single-Precision Float, 6 chữ số thập phân)
    status: int                # Chiều thực tế trên gói tin (trên Tuyến 32: 0 = Đi, 1 = Về; có thể đổi sớm gần bến)
    direction: str             # Byte hướng cuối gói tin (thực tế thường cố định 'Về' = 1, không dùng phân biệt chiều)

    @property
    def distance_to_queried_station_m(self) -> int:
        """Khoảng cách (mét) từ xe tới đúng `station_id` truyền vào request."""
        return self.next_station_id

    @property
    def eta_to_queried_station_sec(self) -> int:
        """Thời gian dự kiến (giây) từ xe tới `station_id` truyền vào request."""
        return self.distance_m

    @property
    def destination_name(self) -> str:
        """Tên bến cuối của chiều xe đang chạy."""
        return self.next_station_name

    @property
    def has_valid_coords(self) -> bool:
        """Kiểm tra tọa độ GPS khác (0, 0)."""
        return self.latitude != 0.0 or self.longitude != 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ======================================================================================
# 2. LỚP CLIENT VIỄN TRẮC CHUẨN (TIMBUS CLIENT)
# ======================================================================================

class TimBusClient:
    """
    Client viễn trắc đóng gói toàn bộ quy trình:
    Serialization -> Symmetric XOR Cipher -> HTTP Transport -> Decryption -> DTO Parsing
    """
    GATEWAY_URL = "http://www.timbus.vn:9149/SearchBuyt/VehicleState"
    DEFAULT_CLIENT_ID = 0x001b02f5  # Tiền tố Client ID chuẩn (4 bytes LE)
    DEFAULT_USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 14; Pixel Build/UP1A.231005.007)"

    @staticmethod
    def _create_random_key(length: int = 32) -> bytes:
        """Sinh chuỗi khóa ngẫu nhiên từ bảng ký tự ASCII in được [48, 127] (tương đương ConnectionExecute.createKeys)"""
        chars = [chr(random.randint(48, 127)) for _ in range(length)]
        return "".join(chars).encode('utf-8')

    @staticmethod
    def _calculate_checksum(data: bytes) -> int:
        """Tính Checksum kiểm toàn Modulo 256 của toàn bộ chuỗi byte (sum(data) & 0xFF)"""
        return sum(data) & 0xff

    @classmethod
    def encrypt_packet(cls, payload_data: bytes, client_id: int = DEFAULT_CLIENT_ID) -> str:
        """
        Đóng frame mật mã đối xứng dòng:
        [Encrypted Body] + [Key1] + [len(Key1)] + [Key2] + [len(Key2)] + [Checksum] -> Base64
        """
        key1 = cls._create_random_key(32)
        key2 = cls._create_random_key(64)
        raw = struct.pack('<I', client_id) + payload_data
        
        # Mã hóa dòng XOR với Key 1
        cipher = bytes([raw[i] ^ key1[i % len(key1)] for i in range(len(raw))])
        
        # Đóng gói trailer cấu trúc bảo vệ
        packet = cipher + key1 + bytes([len(key1)]) + key2 + bytes([len(key2)])
        checksum = cls._calculate_checksum(packet)
        packet += bytes([checksum])
        
        return base64.b64encode(packet).decode('ascii')

    @classmethod
    def decrypt_packet(cls, encoded_str: str) -> bytes:
        """
        Giải mã gói tin phản hồi từ Server TimBus:
        Base64 Decode -> Verify Modulo-256 Checksum -> Extract Key1 -> XOR Decrypt
        """
        clean_str = urllib.parse.unquote(encoded_str).replace('\n', '').replace('\r', '').strip().strip('"')
        raw = base64.b64decode(clean_str)
        if len(raw) < 67:
            raise ValueError(f"Packet quá ngắn ({len(raw)} bytes), không đủ cấu trúc trailer tối thiểu 67 bytes")

        # 1. Kiểm tra Checksum kiểm toàn
        expected_cs = raw[-1]
        actual_cs = cls._calculate_checksum(raw[:-1])
        if expected_cs != actual_cs:
            raise ValueError(f"Sai lệch Checksum: Mong đợi {expected_cs}, thực tế tính được {actual_cs}")

        # 2. Trích xuất thông tin khóa đối xứng từ Trailer
        len_key2 = raw[-2]
        len_key1 = raw[-2 - len_key2 - 1]
        idx_key1 = -2 - len_key2 - 1 - len_key1
        key1 = raw[idx_key1 : idx_key1 + len_key1]
        cipher = raw[:idx_key1]

        # 3. Phép giải mã XOR dòng ngược với Key 1 của Server
        plain = bytes([cipher[i] ^ key1[i % len(key1)] for i in range(len(cipher))])
        return plain

    @staticmethod
    def build_request_body(station_id: int, route_param: str = "", vehicle_param: str = "", direction: int = 1) -> bytes:
        """
        Tuần tự hóa nhị phân payload nghiệp vụ viễn trắc (VehicleState Request Body):
        - Station ID: 4 bytes Little-Endian int32
        - Route Param: 2 bytes Little-Endian uint16 độ dài + UTF-8 String
        - Vehicle Param: 2 bytes Little-Endian uint16 độ dài + UTF-8 String
        - Direction: 1 byte uint8 (0: Chiều đi, 1: Chiều về)
        """
        buf = bytearray()
        buf += struct.pack('<I', station_id)
        
        b_route = route_param.encode('utf-8') if route_param else b""
        buf += struct.pack('<H', len(b_route)) + b_route
        
        b_veh = vehicle_param.encode('utf-8') if vehicle_param else b""
        buf += struct.pack('<H', len(b_veh)) + b_veh
        
        buf += bytes([direction & 0x01])
        return bytes(buf)

    @staticmethod
    def parse_bus_packet(raw_data: bytes, direction_fallback: int = 1) -> List[BusRecord]:
        """
        Phân giải nhị phân mảng byte dữ liệu viễn trắc DTO thành danh sách thực thể BusRecord:
        Cấu trúc tuần tự: Count (1B) + N * [Plate + Route + StationID + Dist + SName + Speed + LatLng + Status + Dir]
        """
        if not raw_data or len(raw_data) < 1:
            return []
        
        count = raw_data[0]
        buses = []
        ptr = 1
        
        for _ in range(count):
            if ptr >= len(raw_data):
                break
            
            # 1. Biển số xe (1 byte len + ASCII/UTF-8)
            l_plate = raw_data[ptr]; ptr += 1
            plate = raw_data[ptr:ptr+l_plate].decode('utf-8', errors='ignore'); ptr += l_plate
            
            # 2. Mã hiệu tuyến (1 byte len + ASCII/UTF-8)
            l_rcode = raw_data[ptr]; ptr += 1
            rcode = raw_data[ptr:ptr+l_rcode].decode('utf-8', errors='ignore'); ptr += l_rcode
            
            # 3. Cự ly còn lại tới station_id vừa hỏi tính theo mét (4 bytes Little-Endian int32)
            next_station_id, = struct.unpack('<I', raw_data[ptr:ptr+4]); ptr += 4
            
            # 4. ETA dự kiến còn lại tới station_id vừa hỏi tính theo giây (4 bytes Little-Endian int32)
            dist_m, = struct.unpack('<I', raw_data[ptr:ptr+4]); ptr += 4
            
            # 5. Tên bến cuối của chiều chạy (2 bytes Little-Endian int16 len + UTF-8)
            l_sname, = struct.unpack('<H', raw_data[ptr:ptr+2]); ptr += 2
            sname = raw_data[ptr:ptr+l_sname].decode('utf-8', errors='ignore'); ptr += l_sname
            
            # 6. Vận tốc km/h (1 byte uint8)
            speed = raw_data[ptr]; ptr += 1
            
            # 7. Tọa độ GPS WGS-84 (8 bytes = 2 x IEEE-754 Single-Precision Float Little-Endian)
            lat, lng = struct.unpack('<ff', raw_data[ptr:ptr+8]); ptr += 8
            
            # 8. Trạng thái điều độ (1 byte uint8) & Hướng di chuyển (1 byte uint8)
            status = raw_data[ptr]; ptr += 1
            direction_byte = raw_data[ptr]; ptr += 1
            
            dir_str = "Về" if direction_byte == 1 else "Đi"
            
            buses.append(BusRecord(
                plate=plate,
                route=rcode,
                next_station_id=next_station_id,
                distance_m=dist_m,
                next_station_name=sname,
                speed_kmh=speed,
                latitude=round(lat, 6),
                longitude=round(lng, 6),
                status=status,
                direction=dir_str
            ))
            
        return buses

    @classmethod
    def query(cls, station_id: int, route_param: str = "", vehicle_param: str = "", direction: int = 1, timeout: int = 8) -> List[BusRecord]:
        """
        Thực hiện toàn bộ pipeline truy vấn trực tiếp máy chủ TimBus:
        1. Tạo nhị phân payload
        2. Mã hóa XOR & đóng frame
        3. Phát HTTP GET
        4. Kiểm toàn & giải mã response
        5. Parse thành List[BusRecord]
        """
        payload = cls.build_request_body(station_id, route_param, vehicle_param, direction)
        encrypted_req = cls.encrypt_packet(payload)
        
        # Mã hóa tham số URL an toàn
        url = f"{cls.GATEWAY_URL}?ReqParams={urllib.parse.quote(encrypted_req)}"
        
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": cls.DEFAULT_USER_AGENT,
                "Connection": "Keep-Alive",
                "Accept-Encoding": "gzip"
            },
            method="GET"
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode('utf-8').strip().strip('"')
            decrypted_bytes = cls.decrypt_packet(resp_body)
            return cls.parse_bus_packet(decrypted_bytes, direction_fallback=direction)

    @classmethod
    def query_station_fleet(cls, station_id: int, route_codes: List[str], direction: int = 1) -> List[BusRecord]:
        """Chế độ 1: Tra cứu đa xe theo trạm dừng (Station Fleet Tracking Mode)"""
        routes_str = ",".join(route_codes) if isinstance(route_codes, list) else str(route_codes)
        return cls.query(station_id=station_id, route_param=routes_str, vehicle_param="", direction=direction)

    @staticmethod
    def normalize_plate(plate: str) -> str:
        """Chuẩn hóa biển kiểm soát về chữ hoa không dấu gạch/chấm (ví dụ: '29F-051.92' -> '29F05192')."""
        return plate.replace("-", "").replace(".", "").replace(" ", "").strip().upper()

    @classmethod
    def query_targeted_vehicle(
        cls,
        station_id: int,
        route_code: str = "",
        plate: str = "",
        direction: int = 1,
        timeout: int = 3,
    ) -> Optional[BusRecord]:
        """Chế độ 2: Bám đuổi đơn xe mục tiêu theo thời gian thực (Targeted Vehicle Tracking Mode).

        Mặc định `route_code=""` để tránh trượt do đổi mã tuyến (04->04CT, 11->11CT...) hoặc tuyến mới.
        Chỉ chấp nhận bản ghi khớp chính xác biển số đã chuẩn hóa và có tọa độ khác (0, 0).
        """
        clean_plate = cls.normalize_plate(plate)
        if not clean_plate:
            return None
        buses = cls.query(
            station_id=station_id,
            route_param=route_code,
            vehicle_param=clean_plate,
            direction=direction,
            timeout=timeout,
        )
        for b in buses:
            if cls.normalize_plate(b.plate) == clean_plate and b.has_valid_coords:
                return b
        return None

    @classmethod
    def query_central_vehicles(
        cls,
        station_ids: List[int],
        plates: List[str],
        direction: int = 0,
        route_code: str = "",
        timeout: int = 3,
        inter_request_delay: float = 0.05,
    ) -> Dict[str, BusRecord]:
        """Chế độ 3: Bám đuổi tối đa 4 xe trung tâm với chuỗi trạm mỏ neo dự phòng (Multi-Anchor Fallback).

        Thử từng `station_id` theo thứ tự ưu tiên (ví dụ `[bến cuối đã kiểm chứng, trạm kế cuối, bến cuối BM]`).
        Nếu một anchor tìm thấy ít nhất 1 xe hợp lệ thì dừng (tránh tốn request vô ích cho xe đã vào bến);
        chỉ chuyển sang anchor tiếp theo khi toàn bộ xe ở anchor hiện tại đều rỗng hoặc lỗi.
        Không retry dồn dập khi timeout/lỗi socket để bảo đảm chu kỳ polling 4.9-5.0s.
        """
        anchors: List[int] = []
        for sid in station_ids:
            if sid and int(sid) not in anchors:
                anchors.append(int(sid))

        norm_targets: List[str] = []
        for p in plates:
            np = cls.normalize_plate(p)
            if np and np not in norm_targets:
                norm_targets.append(np)

        results: Dict[str, BusRecord] = {}
        if not anchors or not norm_targets:
            return results

        max_workers = min(6, len(norm_targets))
        for anchor_idx, sid in enumerate(anchors):
            anchor_hits = 0
            if anchor_idx > 0 and inter_request_delay > 0:
                time.sleep(inter_request_delay)
            if max_workers <= 1:
                for np in norm_targets:
                    try:
                        rec = cls.query_targeted_vehicle(
                            station_id=sid,
                            route_code=route_code,
                            plate=np,
                            direction=direction,
                            timeout=timeout,
                        )
                        if rec is not None:
                            results[np] = rec
                            anchor_hits += 1
                    except Exception:
                        continue
            else:
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    fut_map = {
                        pool.submit(
                            cls.query_targeted_vehicle,
                            station_id=sid,
                            route_code=route_code,
                            plate=np,
                            direction=direction,
                            timeout=timeout,
                        ): np
                        for np in norm_targets
                    }
                    for fut in as_completed(fut_map):
                        np = fut_map[fut]
                        try:
                            rec = fut.result()
                            if rec is not None:
                                results[np] = rec
                                anchor_hits += 1
                        except Exception:
                            continue
            if anchor_hits > 0:
                break

        return results


# ======================================================================================
# 3. CÔNG CỤ DÒNG LỆNH CLI (COMMAND LINE INTERFACE)
# ======================================================================================

def main():
    parser = argparse.ArgumentParser(
        description="TimBus Realtime Telemetry CLI (Bình Anh GPS Hanoi)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ sử dụng:
  # 1. Tra cứu đa xe qua Bến xe Giáp Bát (Trạm 1676):
  python experiments/timbus/timbus_tracker.py --station 1676 --routes "03A,08B,21A,25,28,32,41" --direction 0

  # 2. Theo dõi đơn xe mục tiêu bằng bến cuối (mặc định route_param=''):
  python experiments/timbus/timbus_tracker.py --station 1676 --plate 29F05192 --direction 0
        """
    )
    parser.add_argument("--station", type=int, default=1676, help="Station ID mỏ neo (mặc định: 1676 - BX Giáp Bát)")
    parser.add_argument("--routes", type=str, default="03A,08B,08BCT,21A,21B,25,28,32,41,E08", help="Danh sách mã tuyến phân tách bởi dấu phẩy khi quét theo trạm")
    parser.add_argument("--route", type=str, default="", help="Mã tuyến cụ thể (bỏ trống mặc định khi dùng --plate)")
    parser.add_argument("--plate", type=str, default="", help="Biển kiểm soát xe cụ thể khi theo dõi đơn xe (ví dụ: 29F05192)")
    parser.add_argument("--direction", type=int, default=0, choices=[0, 1], help="Hướng di chuyển: 0 (Đi - mặc định), 1 (Về)")
    parser.add_argument("--json", action="store_true", help="Xuất kết quả dưới định dạng JSON")
    args = parser.parse_args()

    r_param = args.route if (args.route or args.plate) else args.routes
    v_param = args.plate

    if not args.json:
        print(f"[*] Đang kết nối tới TimBus Telemetry Gateway: {TimBusClient.GATEWAY_URL}...")
        print(f"[*] Trạm ID: {args.station} | Tham số Tuyến: '{r_param}' | Biển số: '{v_param}' | Hướng: {args.direction}")

    t_start = time.time()
    try:
        if args.plate:
            single = TimBusClient.query_targeted_vehicle(
                station_id=args.station,
                route_code=args.route,
                plate=args.plate,
                direction=args.direction,
            )
            buses = [single] if single else []
        else:
            buses = TimBusClient.query(args.station, r_param, v_param, args.direction)
        latency_ms = int((time.time() - t_start) * 1000)

        if args.json:
            import json
            print(json.dumps([b.to_dict() for b in buses], ensure_ascii=False, indent=2))
            return

        print(f"\n[+] Phản hồi HTTP 200 OK ({latency_ms}ms) | Tìm thấy {len(buses)} xe buýt trực tuyến:")
        print("=" * 120)
        print(f"{'STT':<4} | {'Biển số':<10} | {'Tuyến':<6} | {'Vận tốc':<9} | {'Status':<6} | {'Tới trạm hỏi':<13} | {'ETA':<7} | {'Tọa độ GPS (Lat, Lng)':<25} | {'Bến cuối'}")
        print("-" * 120)
        for i, b in enumerate(buses, 1):
            coord = f"({b.latitude:.6f}, {b.longitude:.6f})"
            dist = f"{b.distance_to_queried_station_m}m"
            eta = f"{b.eta_to_queried_station_sec}s"
            speed = f"{b.speed_kmh} km/h"
            print(f"{i:<4} | {b.plate:<10} | {b.route:<6} | {speed:<9} | {b.status:<6} | {dist:<13} | {eta:<7} | {coord:<25} | {b.destination_name}")
        print("=" * 120)

    except Exception as e:
        print(f"[-] Lỗi truy vấn viễn trắc: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
