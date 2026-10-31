import base64
import struct

with open("tmp_2.txt", "r", encoding="utf-8") as f:
    lines = [line.strip() for line in f if line.strip()]

responses = [line.strip('"') for line in lines if line.startswith('"')]

r3 = base64.b64decode(responses[2])
print("R3 hex:", r3.hex())
print("R3 len:", len(r3))

# Byte 0..1: "18" (route 18?)
# Let's break down each chunk
# 0..2: 31 38 -> '18'
# 2..4: 02 09
# 4..5: 72 -> 'r'
# 5..7: 01 09
# 7..9: 04 04
# 9..11: 02 33 -> '\x023'
# 11..13: 00 03
# 13..14: 71 -> 'q'
# 14..18: 66 33 30 30 -> 'f300'
# 18..22: a9 30 30 30 -> '\xa9000'
# 22..25: 23 30 72 -> '#0r'
# 25..29: d1 8a 8f 5e -> 4 bytes float or int?
# 29..33: 10 48 55 10
# 33..37: 77 59 f3 91
# 37..41: 40 10 72 f3
# 41..45: 91 44 11 ff
# 45..49: 29 98 71 f7
# 49..53: 9e e3 72 30 -> '\x9e\xe3r0'
# 53..87: '1' + '0'*33
# 87..88: ' '
# 88..120: '0'*32
# 120..121: 48 -> 'H'

for name, fmt, sz in [
    ("int32 LE", "<i", 4),
    ("uint32 LE", "<I", 4),
    ("float LE", "<f", 4),
    ("int32 BE", ">i", 4),
    ("uint32 BE", ">I", 4),
    ("float BE", ">f", 4),
]:
    vals = [struct.unpack(fmt, r3[i:i+sz])[0] for i in range(25, 49, sz)]
    print(f"{name:10s} from 25 to 49: {vals}")

