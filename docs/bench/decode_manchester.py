"""Decode a Manchester-coded differential pair from a sigrok .sr logic capture, using only the capture.

    python docs/bench/decode_manchester.py capture.sr [--mode eth|dali] [--plus 0] [--minus 1]
                                           [--expect HEX] [--halfbit-us US]

The capture: 8 channels, one byte a sample (the Binghe / fx2lafw analyser), TD+ on --plus (default D0 = CH1), TD- on
--minus (default D1 = CH2). Both lines idle low; while the pair carries a frame exactly one of them is high.
Steps:
  1. The frame is the longest run of samples where either line is high (gaps of up to 2 samples, which an edge
     caught between the two lines can make, are joined), not touching either end of the capture.
  2. Bit clock. eth: from the preamble: its first 56 bits alternate 1, 0, so TD+ has one edge in the middle of
     each bit; a straight-line fit of those edge times gives the bit period and the phase. dali: from the edge
     spacings, which are one half-bit or two: the short ones, averaged.
  3. Manchester (IEEE 802.3 / DALI: the first half of a bit is the inverse of the bit, a 1 rises mid-bit): every
     bit has an edge in its middle; each one found re-times the next. Each half is read a quarter-bit either side
     of the middle. Decoding stops at the first bit whose halves are both high with no mid-bit edge: the end marker.
  4. TD- against TD+: every sample of the frame must have TD- = not TD+, except single samples at an edge.
  5. End marker: from the end of the last bit to the end of the frame, in half-bits (expect 6).
  6. Bytes: eth LSB first, dali MSB first. eth: 7 x 55 and D5, then the frame; the last 4 bytes are the FCS, which
     must equal zlib.crc32 of the bytes before it (little-endian). --expect HEX: the bytes must equal HEX (eth: the
     frame after the SFD, without the FCS; dali: all the bytes). --halfbit-us: the half-bit must be within 1 %.
Prints the bytes and PASS or FAIL.
"""
import argparse, configparser, re, sys, zipfile, zlib
import numpy as np


def read_sr(path):
    z = zipfile.ZipFile(path)
    cfg = configparser.ConfigParser()
    cfg.read_string(z.read("metadata").decode())
    dev = cfg["device 1"]
    m = re.match(r"([\d.]+)\s*([kMG]?)Hz", dev["samplerate"])
    rate = float(m.group(1)) * {"": 1, "k": 1e3, "M": 1e6, "G": 1e9}[m.group(2)]
    unit = int(dev.get("unitsize", "1"))
    base = dev.get("capturefile", "logic-1")
    chunks = sorted((n for n in z.namelist() if n.startswith(base + "-")), key=lambda n: int(n.rsplit("-", 1)[1]))
    raw = b"".join(z.read(n) for n in chunks)
    data = np.frombuffer(raw, dtype=np.uint8 if unit == 1 else np.uint16)
    return rate, data


def runs(x):
    """Runs of True in a bool array: list of (start, end) with end exclusive."""
    d = np.diff(np.concatenate(([0], x.astype(np.int8), [0])))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sr")
    ap.add_argument("--mode", choices=("eth", "dali"), default="eth")
    ap.add_argument("--plus", type=int, default=0)
    ap.add_argument("--minus", type=int, default=1)
    ap.add_argument("--expect", default=None)
    ap.add_argument("--halfbit-us", type=float, default=None)
    a = ap.parse_args()
    fails = []

    def check(what, ok, detail=""):
        print(f"  {'ok  ' if ok else 'FAIL'}  {what}" + (f": {detail}" if detail else ""))
        if not ok:
            fails.append(what)

    rate, data = read_sr(a.sr)
    p = ((data >> a.plus) & 1).astype(np.int8)
    m = ((data >> a.minus) & 1).astype(np.int8)
    us = 1e6 / rate
    print(f"{a.sr}: {len(data)} samples at {rate / 1e6:g} MHz ({len(data) * us / 1000:.3f} ms), "
          f"TD+ = D{a.plus}, TD- = D{a.minus}, mode {a.mode}")

    # 1. the frame
    act = runs((p | m) == 1)
    merged = []
    for s, e in act:
        if merged and s - merged[-1][1] <= 2:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    inside = [(s, e) for s, e in merged if s > 0 and e < len(data)]
    print(f"  {len(merged)} active runs on the pair, {len(inside)} complete; longest "
          + ", ".join(f"{(e - s) * us:.1f} us" for s, e in sorted(inside, key=lambda r: r[0] - r[1])[:3]))
    if not inside:
        check("a complete frame in the capture", False)
        print("\n==== FAIL ====")
        return 1
    s0, s1 = max(inside, key=lambda r: r[1] - r[0])
    print(f"  frame: samples {s0} to {s1}, {(s1 - s0) * us:.1f} us, starting {s0 * us:.1f} us into the capture")

    # TD+ edges inside the frame (sample index of the first sample at the new level)
    pe = np.nonzero(np.diff(p[s0 - 1:s1 + 1]))[0] + s0
    me = np.nonzero(np.diff(m[s0 - 1:s1 + 1]))[0] + s0

    # 2. bit clock
    if a.mode == "eth":
        mids = pe[pe > s0][:56].astype(float)
        if len(mids) < 56:
            check("56 preamble edges", False, f"{len(mids)}")
            print("\n==== FAIL ====")
            return 1
        B, m0 = np.polyfit(np.arange(56), mids, 1)
        resid = mids - (m0 + B * np.arange(56))
        print(f"  bit clock from the preamble: 56 mid-bit edges, bit {B * us:.4f} us, half-bit {B * us / 2:.4f} us "
              f"({1e6 / (B * us) / 1e3:.2f} kbit/s), fit residual max {np.abs(resid).max():.2f} samples")
    else:
        iv = np.diff(pe).astype(float)
        short = iv[iv < 1.5 * iv.min()]
        T = short.mean()
        B = 2 * T
        long_ = iv[(iv > 1.5 * T) & (iv < 2.5 * T)]
        m0 = s0 + T
        print(f"  bit clock from the edge spacings: {len(short)} one-half-bit gaps averaging {T * us:.2f} us, "
              f"{len(long_)} two-half-bit gaps averaging {long_.mean() * us if len(long_) else 0:.2f} us; "
              f"half-bit {T * us:.2f} us ({1e6 / (B * us):.1f} bit/s)")
    T = B / 2
    if a.halfbit_us:
        check(f"half-bit within 1 % of {a.halfbit_us} us", abs(T * us - a.halfbit_us) <= 0.01 * a.halfbit_us,
              f"{T * us:.4f} us")

    # 3. Manchester: walk mid-bit edges
    def level(x, t):
        i = int(round(t))
        return int(x[min(max(i, 0), len(x) - 1)])

    bits, mid, k = [], m0, 0
    end_of_bits = None
    while True:
        exp = m0 if k == 0 else mid + B
        near = pe[np.abs(pe - exp) <= B / 4]
        h0, h1 = level(p, exp - B / 4), level(p, exp + B / 4)
        if len(near):
            mid = float(near[np.argmin(np.abs(near - exp))])
            h0, h1 = level(p, mid - B / 4), level(p, mid + B / 4)
            if h0 == h1:
                check(f"bit {k}: Manchester halves", False, f"edge but halves {h0}{h1}")
                break
            bits.append(h1)
            k += 1
            continue
        if (h0, h1) == (1, 1):
            end_of_bits = exp - B / 2
            break
        check(f"bit {k}: mid-bit edge", False, f"none, halves {h0}{h1} at {exp * us:.1f} us")
        break
    print(f"  {len(bits)} bits ({len(bits) / 8:g} bytes) before the end marker")
    check("whole number of bytes", len(bits) % 8 == 0 and len(bits) > 0, f"{len(bits)} bits")

    # 4. TD- against TD+
    same = (p[s0:s1] == m[s0:s1])
    bad = np.nonzero(same)[0] + s0
    edges = np.union1d(pe, me)
    lone = [i for i in bad if not len(edges[np.abs(edges - i) <= 1])]
    longest = max((e - s for s, e in runs(same)), default=0)
    check("TD- is the inverse of TD+ throughout the frame", not lone and longest <= 1,
          f"{len(bad)} of {s1 - s0} samples equal, each beside an edge, longest run {longest}" if not lone else
          f"{len(lone)} samples equal away from any edge, first at {lone[0] * us:.1f} us")

    # 5. end marker
    if end_of_bits is not None:
        hb = (s1 - end_of_bits) / T
        tdm_low = int(m[int(end_of_bits) + 2:s1 - 1].max(initial=0)) == 0
        check("end marker 6 half-bits, TD+ high and TD- low", abs(hb - 6) < 0.25 and tdm_low,
              f"{hb:.2f} half-bits = {(s1 - end_of_bits) * us:.2f} us")
    after = slice(s1, min(s1 + int(4 * B), len(data)))
    check("both lines low after the frame", p[after].max(initial=0) == 0 and m[after].max(initial=0) == 0)

    # 6. bytes
    n = len(bits) // 8 * 8
    if a.mode == "eth":
        got = bytes(sum(bits[i + j] << j for j in range(8)) for i in range(0, n, 8))
    else:
        got = bytes(sum(bits[i + j] << (7 - j) for j in range(8)) for i in range(0, n, 8))
    print("  bytes on the wire (%s first):" % ("LSB" if a.mode == "eth" else "MSB"))
    for i in range(0, len(got), 16):
        print(f"    {i:4d}  " + " ".join(f"{b:02x}" for b in got[i:i + 16]))
    if a.mode == "eth":
        check("preamble 55 x 7 and SFD d5", got[:8] == bytes([0x55] * 7 + [0xD5]), got[:8].hex(" "))
        fr = got[8:]
        check("frame at least 64 bytes with the FCS", len(fr) >= 64, f"{len(fr)}")
        if len(fr) >= 18:
            body, fcs = fr[:-4], fr[-4:]
            calc = zlib.crc32(body) & 0xFFFFFFFF
            print(f"  destination {body[0:6].hex(':')}  source {body[6:12].hex(':')}  type 0x{body[12:14].hex()}  "
                  f"payload {len(body) - 14} bytes")
            check("FCS = zlib.crc32 of the frame", fcs == calc.to_bytes(4, "little"),
                  f"on the wire {fcs.hex()}, computed {calc.to_bytes(4, 'little').hex()} (0x{calc:08X})")
            if a.expect:
                want = bytes.fromhex(a.expect)
                check("frame equals the bytes sent", body == want,
                      "" if body == want else f"sent {want.hex()}")
    elif a.expect:
        want = bytes.fromhex(a.expect)
        check("bytes equal the bytes sent", got == want, "" if got == want else f"sent {want.hex()}")

    print("\n==== %s ====" % ("FAIL (" + "; ".join(fails) + ")" if fails else "PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
