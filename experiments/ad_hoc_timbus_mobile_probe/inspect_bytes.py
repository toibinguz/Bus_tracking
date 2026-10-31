import base64

with open("tmp_2.txt", "r", encoding="utf-8") as f:
    lines = [line.strip() for line in f if line.strip()]

responses = [line.strip('"') for line in lines if line.startswith('"')]

for idx, resp in enumerate(responses):
    b = base64.b64decode(resp)
    print(f"\n=== Response {idx+1} (Length: {len(b)}) ===")
    print("Hex:", b.hex())
    # Try ASCII printable
    printable = "".join(chr(c) if 32 <= c <= 126 else "." for c in b)
    print("ASCII:", printable)

