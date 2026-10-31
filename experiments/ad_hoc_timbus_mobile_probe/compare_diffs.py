import base64

with open("tmp_2.txt", "r", encoding="utf-8") as f:
    lines = [line.strip() for line in f if line.strip()]

responses = [line.strip('"') for line in lines if line.startswith('"')]

# Let's compare responses 3 to 8 (indices 2 to 7)
r3_to_r8 = [base64.b64decode(r) for r in responses[2:]]

print(f"Comparing {len(r3_to_r8)} responses of length {len(r3_to_r8[0])}:")

diff_indices = []
for i in range(len(r3_to_r8[0])):
    vals = [r[i] for r in r3_to_r8]
    if len(set(vals)) > 1:
        diff_indices.append(i)

print(f"Total diff byte positions: {len(diff_indices)} / {len(r3_to_r8[0])}")
print("Diff positions:", diff_indices)

for pos in diff_indices:
    vals_hex = [f"{r[pos]:02x}" for r in r3_to_r8]
    vals_chr = [chr(r[pos]) if 32 <= r[pos] <= 126 else "." for r in r3_to_r8]
    print(f"Pos {pos:02d} (0x{pos:02x}): hex={vals_hex} chr={vals_chr}")

