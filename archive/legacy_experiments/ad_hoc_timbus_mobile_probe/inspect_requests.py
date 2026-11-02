import base64
import urllib.parse

with open("tmp_2.txt", "r", encoding="utf-8") as f:
    lines = [line.strip() for line in f if line.strip()]

requests = [line for line in lines if line.startswith("GET ")]

for idx, req in enumerate(requests):
    parsed = urllib.parse.urlparse(req.split()[1])
    params = urllib.parse.parse_qs(parsed.query)
    req_param = params.get("ReqParams", [""])[0]
    
    b = base64.b64decode(req_param)
    print(f"\n=== Request {idx+1} (Len: {len(b)}) ===")
    print("Hex:", b.hex())
    printable = "".join(chr(c) if 32 <= c <= 126 else "." for c in b)
    print("ASCII:", printable)

