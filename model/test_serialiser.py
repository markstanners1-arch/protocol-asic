"""The serialiser and the CRC unit on the engine model (docs/isa.md v0.3), decoded back at the pins.

1. Ethernet: programs/eth_tx.asm sends a minimum 10BASE-T frame (preamble, SFD, 14-byte header, 46-byte payload) from a count
   and 34 words pushed by the host; the TD+/TD- pair is decoded from the clock-by-clock pin levels (Manchester, half-bit = SERDIV
   + 1 clocks), every byte checked, the hardware FCS checked against zlib.crc32, the TP_IDL (6 half-bits high) and the idle
   levels checked, the pins checked idle while the serialiser waits for the FIFO to fill; then the link pulse (100 ns on TD+,
   16.4 ms after the frame). Run at SERDIV 0 and 1.
2. NRZ, LSB first, with a 16-bit CRC (Modbus 0xA001 / 0xFFFF, no complement) appended: the 32 appended bits are the CRC in the
   low half and zeros above.
3. DALI-style: MSB first, Manchester, single-ended, SERDIV 4999 (12 MHz), no CRC, no marker.
4. Streaming past the FIFO depth: 70 words with the host refilling; then an underrun: 66 words with only 64 supplied (the line
   released at the word boundary, the flag set, cleared by the next start).
5. Abort: mov ser, null mid-word releases the pins at once.
6. The CRC unit in IN mode: one bit per IN, in crc, time crc reset, checked against a Modbus CRC-16 reference; a multi-bit IN
   feeds its first bit only.
7. An engine without the serialiser: mov ser does nothing, wait 0, ser passes, the FIFO is 4 deep, the CRC unit still works.
Run:  python model/test_serialiser.py [quick]     (quick skips the 16.4 ms link-pulse wait)
"""
import os, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config, SER_FIFO_DEPTH, crc_step

QUICK = "quick" in sys.argv[1:]
fails = []


def check(what, got, want):
    ok = got == want
    print(f"{'ok:  ' if ok else 'FAIL:'} {what} = {got!r}" + ("" if ok else f", expected {want!r}"))
    if not ok:
        fails.append(what)
    return ok


def crc16_modbus(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def words_le(data):
    return [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]


def run(eng, nclocks, pin_a, pin_b=None, feed=None):
    """Clock the model; feed = dict clock -> word to push. Returns the list of (a, b) pin levels per clock."""
    trace = []
    for t in range(nclocks):
        if feed and t in feed:
            assert eng.tx_put(feed[t]), f"FIFO refused a push at clock {t}"
        eng.clock(0)
        v = eng.pins_out
        trace.append(((v >> pin_a) & 1, ((v >> pin_b) & 1) if pin_b is not None else None))
    return trace


def spans(trace, owned):
    """Maximal runs of clocks where owned(level_pair) holds: [(start, end)] with end exclusive."""
    out, start = [], None
    for t, lv in enumerate(trace):
        if owned(lv) and start is None:
            start = t
        elif not owned(lv) and start is not None:
            out.append((start, t)); start = None
    if start is not None:
        out.append((start, len(trace)))
    return out


def slots(levels, period):
    """Split a run of levels into half-bit slots of `period` clocks; every slot must be constant."""
    assert len(levels) % period == 0, f"run of {len(levels)} clocks is not a whole number of {period}-clock half-bits"
    out = []
    for i in range(0, len(levels), period):
        s = levels[i:i + period]
        assert all(x == s[0] for x in s), f"level changed inside half-bit {i // period}"
        out.append(s[0])
    return out


def decode(halves, manch, lsb_first, nbits):
    """Half-bit levels -> bits (Manchester: first half is the inverse of the bit) -> bytes."""
    bits = []
    for i in range(nbits):
        h0, h1 = halves[2 * i], halves[2 * i + 1]
        if manch:
            assert h0 != h1, f"bit {i}: both halves {h0} (not Manchester)"
            bits.append(h1)
        else:
            assert h0 == h1, f"bit {i}: halves differ in NRZ"
            bits.append(h0)
    return bits


def bits_to_bytes(bits, lsb_first=True):
    out = []
    for i in range(0, len(bits), 8):
        chunk = bits[i:i + 8]
        out.append(sum(b << k for k, b in enumerate(chunk)) if lsb_first else sum(b << (7 - k) for k, b in enumerate(chunk)))
    return bytes(out)


ETH_CFG = dict(ser=True, ser_en=True, manch=True, diff=True, end_marker=True, crc_append=True, crc_cpl=True, crc_ser=True,
               crc_skip=4, crcpoly=0xEDB88320, crcinit=0xFFFFFFFF)
TDP, TDM = 8, 9


def test_ethernet(serdiv):
    prog = assemble(open(os.path.join(ROOT, "programs", "eth_tx.asm")).read())
    cfg = Config.for_program(prog, out_base=TDP, out_count=2, set_base=TDP, set_count=2, out_right=True, serdiv=serdiv, **ETH_CFG)
    eng = Engine(prog, cfg)
    preamble = bytes([0x55] * 7 + [0xD5])
    header = bytes.fromhex("ffffffffffff" "020000000001" "88b5")
    payload = bytes(range(0x30, 0x30 + 46))
    body = header + payload
    frame_words = words_le(preamble + body)
    assert len(frame_words) == 34
    P = serdiv + 1
    gap = 200                                   # clocks between host pushes (a slow host: the fill wait is exercised)
    feed = {100 + gap * i: w for i, w in enumerate([len(frame_words)] + frame_words)}
    last_push = max(feed)
    nbits = 34 * 16 + 32
    frame_clocks = (2 * nbits + 6) * P
    trace = run(eng, last_push + frame_clocks + 400, TDP, TDM, feed)
    print(f"-- Ethernet frame, SERDIV {serdiv}: {eng.events}")
    own = spans(trace, lambda lv: lv[0] != lv[1])
    check("one owned span on the pair", len(own), 1)
    s, e = own[0]
    check("pair idle (both low) before the frame", set(trace[:s]), {(0, 0)})
    check("pair idle after the frame", set(trace[e:]), {(0, 0)})
    check("serialiser started only after the last word arrived", s > last_push, True)
    check("frame length in clocks", e - s, frame_clocks)
    check("TD- is the inverse of TD+ throughout", all(a != b for a, b in trace[s:e]), True)
    halves = slots([a for a, b in trace[s:e]], P)
    bits = decode(halves, True, True, nbits)
    got = bits_to_bytes(bits)
    check("preamble and SFD bytes", got[:8].hex(), preamble.hex())
    check("header and payload bytes", got[8:68].hex(), body.hex())
    fcs = zlib.crc32(body) & 0xFFFFFFFF
    check("FCS on the wire = zlib.crc32 (little-endian, complemented)", got[68:72].hex(), fcs.to_bytes(4, "little").hex())
    check("TP_IDL: the last 6 half-bits high", halves[-6:], [1] * 6)
    check("CRC register after the frame (not complemented)", eng.crc, fcs ^ 0xFFFFFFFF)
    check("busy off, no underrun", (eng.ser_busy, eng.ser_under), (False, False))
    if QUICK:
        return
    # the link pulse: TD+ high 2 ticks, 16.4 ms after the frame (65535 polls of 5 ticks + the gap and overheads), at 20 MHz
    t_end = e
    pulse = None
    for t in range(len(trace), len(trace) + 400_000):
        eng.clock(0)
        v = eng.pins_out
        if (v >> TDP) & 1:
            pulse = t
            width = 0
            while (eng.pins_out >> TDP) & 1:
                width += 1; eng.clock(0)
            break
    check("link pulse seen", pulse is not None, True)
    if pulse is not None:
        check("link pulse width (ticks of 50 ns)", width, 2)
        check("link pulse 16.4 ms after the frame (within 1 %)", abs((pulse - t_end) - 327_675) < 3_300, True)
        print(f"      pulse {pulse - t_end} clocks after the frame = {(pulse - t_end) * 50e-6:.2f} ms at 20 MHz")


def test_nrz_crc16():
    prog = assemble("pull block\n mov ser, osr\n wait 0, ser\n wait 1, ser\n")
    data = bytes.fromhex("0103000a0002")             # a Modbus request; CRC-16/MODBUS follows it
    cfg = Config.for_program(prog, out_base=3, out_count=1, set_base=3, set_count=1, out_right=True, serdiv=2,
                             ser=True, ser_en=True, crc_append=True, crc_ser=True, crcpoly=0xA001, crcinit=0xFFFF)
    eng = Engine(prog, cfg)
    w = words_le(data)
    feed = {5: len(w), **{6 + i: x for i, x in enumerate(w)}}
    nbits = len(w) * 16 + 32
    trace = run(eng, 20 + (2 * nbits) * 3 + 50, 3, None, feed)
    print(f"-- NRZ + CRC-16: {eng.events}")
    # NRZ idles at the program's level (0) and the first data bit is 1, so the span starts with the first 1; find it by length
    first = next(t for t, lv in enumerate(trace) if lv[0])
    levels = [a for a, b in trace[first:first + 2 * nbits * 3]]
    halves = slots(levels, 3)
    bits = decode(halves, False, True, nbits)
    got = bits_to_bytes(bits)
    check("NRZ data bytes", got[:6].hex(), data.hex())
    crc = crc16_modbus(data)
    check("appended CRC-16 in the low half, zeros above", got[6:10].hex(), crc.to_bytes(2, "little").hex() + "0000")
    check("line back to 0 after the last bit", trace[first + 2 * nbits * 3][0], 0)


def test_dali_msb():
    prog = assemble("pull block\n mov ser, osr\n wait 0, ser\n wait 1, ser\n")
    cfg = Config.for_program(prog, out_base=8, out_count=1, set_base=8, set_count=1, out_right=False, serdiv=4999,
                             ser=True, ser_en=True, manch=True)
    eng = Engine(prog, cfg)
    word = 0xFE51
    trace = run(eng, 10 + 32 * 5000 + 20, 8, None, {3: 1, 4: word})
    print(f"-- DALI-style MSB first at SERDIV 4999: {eng.events}")
    # Manchester: the first half of the first bit (1) is low; the frame starts where the line is first owned. The line is 0
    # when idle too, so locate the start from the busy flag instead: re-run tracking ser_own.
    eng = Engine(prog, cfg)
    levels, started = [], None
    for t in range(10 + 32 * 5000 + 20):
        if t == 3: eng.tx_put(1)
        if t == 4: eng.tx_put(word)
        eng.clock(0)
        if eng.ser_own:
            if started is None: started = t
            levels.append((eng.pins_out >> 8) & 1)
    check("owned for 32 half-bits of 5000 clocks", len(levels), 32 * 5000)
    halves = slots(levels, 5000)
    bits = decode(halves, True, False, 16)
    check("16 bits MSB first", sum(b << (15 - i) for i, b in enumerate(bits)), word)
    check("first half-bit of the first bit (a 1) is low", halves[0], 0)


def test_stream_and_underrun():
    prog = assemble(".wrap_target\n pull block\n mov ser, osr\n wait 0, ser\n.wrap\n")
    cfg = Config.for_program(prog, out_base=0, out_count=1, set_base=0, set_count=1, out_right=True, serdiv=3,
                             ser=True, ser_en=True)
    # 70 words: the serialiser starts when the FIFO is full (64) and the host keeps it topped up: no underrun
    eng = Engine(prog, cfg)
    words = [(i * 0x1357 + 11) & 0xFFFF for i in range(70)]
    eng.tx_put(70); eng.clock(0)
    sent = 0
    levels, t = [], 0
    while sent < 70 or eng.ser_busy:
        if sent < 70 and len(eng.txf) < SER_FIFO_DEPTH and eng._push is None:
            eng.tx_put(words[sent]); sent += 1
        eng.clock(0)
        if eng.ser_own:
            levels.append(eng.pins_out & 1)
        t += 1
        assert t < 70 * 32 * 4 + 1000, "frame never finished"
    print(f"-- 70 words streamed through a 64-word FIFO: {eng.events}")
    check("70 words sent without underrun", (len(levels), eng.ser_under), (70 * 32 * 4, False))
    got = bits_to_bytes(decode(slots(levels, 4), False, True, 70 * 16))
    check("every streamed word intact", words_le(got), words)
    # 66 words with 64 supplied: the 64 go out, then the line is released and the underrun flag set
    eng = Engine(prog, cfg)
    eng.tx_put(66); eng.clock(0)
    for w in words[:64]:
        eng.tx_put(w); eng.clock(0)
    levels = []
    for t in range(64 * 32 * 4 + 200):
        eng.clock(0)
        if eng.ser_own:
            levels.append(eng.pins_out & 1)
    print(f"-- 66 words, 64 supplied: {eng.events}")
    check("released after exactly 64 words", len(levels), 64 * 32 * 4)
    check("underrun flagged, not busy", (eng.ser_under, eng.ser_busy), (True, False))
    check("MOV status would show it: bit 9", eng.ser_under << 9, 0x200)
    # the next start clears the flag
    eng.tx_put(1); eng.clock(0); eng.tx_put(0x1234); eng.clock(0)
    for _ in range(16 * 2 * 4 + 20):
        eng.clock(0)
    check("flag cleared by the next frame, which completed", (eng.ser_under, eng.ser_busy, eng.events["done"]), (False, False, 1))


def test_abort():
    prog = assemble("pull block\n mov ser, osr\n set x, 10\nl: jmp x--, l\n mov ser, null\n wait 0, ser\n set pins, 1\nhalt: jmp halt\n")
    cfg = Config.for_program(prog, out_base=2, out_count=1, set_base=2, set_count=1, out_right=True, serdiv=7,
                             ser=True, ser_en=True, manch=True, end_marker=True)
    eng = Engine(prog, cfg)
    eng.tx_put(2); eng.clock(0); eng.tx_put(0xFFFF); eng.clock(0); eng.tx_put(0xFFFF); eng.clock(0)
    owned = 0
    for t in range(200):
        eng.clock(0)
        owned += eng.ser_own
    print(f"-- abort: {eng.events}")
    check("aborted mid-word: owned for fewer clocks than one word", 0 < owned < 16 * 2 * 8, True)
    check("after the abort: idle, no underrun, program past the wait (pin set high)", (eng.ser_busy, eng.ser_under, (eng.pins_out >> 2) & 1), (False, False, 1))
    check("one word left unsent in the FIFO", len(eng.txf), 1)


def test_crc_in_mode():
    # the UART-style receiver: one bit per IN, LSB first; after 16 bits read the CRC
    prog = assemble("time crc reset\n set y, 15\nbit: wait 1, pin 1\n in pins, 1\n wait 0, pin 1\n jmp y--, bit\n in crc, 16\n push block\nhalt: jmp halt\n")
    cfg = Config.for_program(prog, in_base=0, in_right=True, crcpoly=0xA001, crcinit=0xFFFF)
    eng = Engine(prog, cfg)
    data = bytes.fromhex("1103")
    bits = [(b >> k) & 1 for b in data for k in range(8)]
    for b in bits:                                    # pin 0 = the data bit, pin 1 = a strobe
        for lv in (b, b | 2, b | 2, b):
            for _ in range(3):
                eng.clock(lv)
    for _ in range(20):
        eng.clock(0)
    got = eng.rx_get()
    print(f"-- CRC unit, IN mode: {eng.events}")
    check("CRC-16/MODBUS of 11 03 via 16 single-bit INs", got, crc16_modbus(data))
    ref = crc16_modbus(data)
    check("the register itself has stepped once more: in crc, 16 is an IN, fed with its own bit 0", eng.crc, crc_step(ref, 0xA001, ref & 1))
    # a multi-bit IN feeds only its first bit: in x, 8 with x = 0x81 (bit 0 = 1) steps once with a 1
    prog2 = assemble("time crc reset\n set x, 1\n in x, 8\n in crc, 16\n push block\n")
    eng2 = Engine(prog2, Config.for_program(prog2, in_right=True, crcpoly=0xA001, crcinit=0xFFFF))
    for _ in range(10):
        eng2.clock(0)
    one = (0xFFFF >> 1) ^ 0xA001                      # one step with bit 1 from 0xFFFF: lsb of 0xFFFF ^ 1 = 0 -> plain shift
    check("in x, 8 steps the CRC once with bit 0 of the data", eng2.rx_get(), 0xFFFF >> 1)
    prog3 = assemble("time crc reset\n set x, 2\n in x, 8\n in crc, 16\n push block\n")
    eng3 = Engine(prog3, Config.for_program(prog3, in_right=True, crcpoly=0xA001, crcinit=0xFFFF))
    for _ in range(10):
        eng3.clock(0)
    check("... bit 0 = 0 with init 0xFFFF: the step takes the polynomial", eng3.rx_get(), one)


def test_plain_engine():
    hold = assemble("halt: jmp halt\n")
    eng = Engine(hold, Config.for_program(hold, ser=False))
    for w in (1, 2, 3, 4):
        check(f"push {w} into a 4-deep FIFO", eng.tx_put(w), True); eng.clock(0)
    check("fifth push refused (FIFO 4 deep)", eng.tx_put(5), False)
    prog = assemble("set x, 3\n mov ser, x\n wait 0, ser\n pull block\n mov ser, osr\n wait 1, ser\n")
    cfg = Config.for_program(prog, out_base=0, out_count=1, out_right=True, ser=False, ser_en=True, manch=True,
                             crcpoly=0xA001, crcinit=0xFFFF)
    eng = Engine(prog, cfg)
    eng.tx_put(0x1234)
    for _ in range(20):
        eng.clock(0)
    print(f"-- engine without the serialiser: {eng.events}")
    check("mov ser did nothing, wait 0, ser passed, pull took the word, stuck on wait 1, ser at pc 5",
          (eng.ser_busy, eng.pc, eng.osr, len(eng.txf), eng.pins_out), (False, 5, 0x1234, 0, 0))


if __name__ == "__main__":
    test_ethernet(0)
    test_ethernet(1)
    test_nrz_crc16()
    test_dali_msb()
    test_stream_and_underrun()
    test_abort()
    test_crc_in_mode()
    test_plain_engine()
    print("PASS" if not fails else f"FAIL: {len(fails)} checks: {fails}")
    sys.exit(1 if fails else 0)
