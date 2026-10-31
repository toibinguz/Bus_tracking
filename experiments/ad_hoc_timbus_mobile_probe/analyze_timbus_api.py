import base64
import urllib.parse

with open("tmp_2.txt", "r", encoding="utf-8") as f:
    lines = [line.strip() for line in f if line.strip()]

requests = []
responses = []

for line in lines:
    if line.startswith("GET "):
        requests.append(line)
    elif line.startswith('"') and line.endswith('"'):
        responses.append(line.strip('"'))

print(f"Total requests: {len(requests)}, Total responses: {len(responses)}")

for i, (req, resp) in enumerate(zip(requests, responses)):
    parsed = urllib.parse.urlparse(req.split()[1])
    params = urllib.parse.parse_qs(parsed.query)
    req_param = params.get("ReqParams", [""])[0]
    
    resp_bytes = base64.b64decode(resp)
    print(f"\n--- Pair {i+1} ---")
    print(f"ReqParams raw len: {len(req_param)}")
    try:
        req_b64 = base64.b64decode(req_param)
        print(f"Req decoded bytes len: {len(req_b64)}, preview: {req_b64[:30]!r}")
    except Exception as e:
        print(f"Req b64 decode error: {e}")
        
    print(f"Resp decoded bytes len: {len(resp_bytes)}")
    print(f"Resp preview: {resp_bytes[:40]!r} ... {resp_bytes[-40:]!r}")

