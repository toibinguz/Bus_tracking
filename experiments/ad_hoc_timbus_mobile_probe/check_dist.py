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
    
    # Calculate percentage of printable ascii
    printable = sum(1 for c in b if 32 <= c <= 126)
    print(f"Req {idx+1}: len={len(b)}, printable={printable}/{len(b)} ({printable/len(b)*100:.1f}%)")

