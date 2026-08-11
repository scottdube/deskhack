import sys
SR, BAUD = 100_000, 1000
SPB = SR // BAUD           # samples per bit
def frame(b):
    bits = [0]                                   # start
    bits += [(b >> i) & 1 for i in range(8)]     # LSB first
    bits += [sum((b >> i) & 1 for i in range(8)) & 1]   # even parity
    bits += [1]                                  # stop
    return bits
out = bytearray([1] * (SR // 10))                  # idle high
for b in b'\x55\x2A\x6C\xF0':
    for bit in frame(b):
        out += bytes([bit]) * SPB
    out += bytes([1]) * SPB                      # inter-frame gap
out += bytes([1]) * (SR // 10)
open('uart_test.bin', 'wb').write(bytes(out))
print(f"wrote {len(out)} samples @ {SR} Hz, {SPB} samples/bit")
