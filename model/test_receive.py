"""Receive on engine 0 (private design 8 Nov 2026): the serialiser run backwards, tested on the model.

1. Loopback: programs/eth_tx.asm on a transmit engine sends a minimum Ethernet frame (FCS appended by the CRC unit); a
   second engine 0 in receive mode listens to TD+ and must hold the frame from the destination address to the FCS,
   word for word, with the status right. SERDIV 0 and 1.
2. Jitter: a frame generated in nanoseconds (10 Mbit/s, half-bit 50 ns, every edge moved by up to +-J ns at random),
   sampled as the 40 MHz chip does: on both clock edges (12.5 ns apart) or on the rising edge only (25 ns). For each J,
   20 frames at random clock phases; the largest J with every frame right is reported for both ways of sampling.
3. The direction switch and the interlocks: a change while a frame is coming in is refused and changes nothing; a change
   while idle empties the buffer; MOV ser in receive mode is refused; the host cannot fill the buffer in receive mode;
   PULL finds it empty; arm empties it; a lone link pulse never starts a frame; a frame longer than the buffer sets
   OVERRUN and keeps the first 64 words.
Run:  python model/test_receive.py
"""
import os, random, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config, RX_DATA, RX_HUNT, RX_IDLE

fails = []


def check(what, got, want):
    ok = got == want
    print(f"{'ok:  ' if ok else 'FAIL:'} {what} = {got!r}" + ("" if ok else f", expected {want!r}"))
    if not ok:
        fails.append(what)
    return ok


def words_le(data):
    data = bytes(data) + (b"\0" if len(data) % 2 else b"")
    return [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]


PREAMBLE = bytes([0x55] * 7 + [0xD5])
BODY = bytes.fromhex("ffffffffffff" "020000000001" "88b5") + bytes(range(0x30, 0x30 + 46))
FCS = zlib.crc32(BODY).to_bytes(4, "little")
WANT = words_le(BODY + FCS)                       # what the receiver must hold: destination address to FCS
TDP, TDM = 8, 9
IDLE_PROG = [0] * 32                              # jmp 0: the receiving engine's program does nothing


def receiver(rxgap, both=True, raw=False, pin=TDP):
    eng = Engine(IDLE_PROG, Config(ser=True, rx_pin=pin, rxgap=rxgap, rx_both=both, rx_raw=raw, in_right=True))
    eng.clock(0, mode_wr=1)                       # a keyed write: receive
    eng.clock(0, arm=True)                        # arm for one frame
    return eng


def drain(eng, limit=200):
    got = []
    for _ in range(limit):
        eng.clock(0, bpop=True)
        if eng.bpopped is not None:
            got.append(eng.bpopped)
    return got


# ---- 1. loopback from the serialiser
def test_loopback(serdiv):
    prog = assemble(open(os.path.join(ROOT, "programs", "eth_tx.asm")).read())
    tx = Engine(prog, Config.for_program(prog, out_base=TDP, out_count=2, set_base=TDP, set_count=2, out_right=True,
                                          serdiv=serdiv, ser=True, ser_en=True, manch=True, diff=True, end_marker=True,
                                          crc_append=True, crc_cpl=True, crc_ser=True, crc_skip=4, crcpoly=0xEDB88320,
                                          crcinit=0xFFFFFFFF))
    rx = receiver(rxgap=3 * (serdiv + 1))         # 3/4 of a bit in half-clocks: a bit is 4 (SERDIV + 1) half-clocks
    words = words_le(PREAMBLE + BODY)
    feed = [len(words)] + words
    for t in range(6000):
        if feed and t >= 10:
            if tx.tx_put(feed[0]):
                feed.pop(0)
        tx.clock(0)
        rx.clock(tx.pins_out)
    print(f"-- loopback, SERDIV {serdiv}")
    check(f"SERDIV {serdiv}: frame ready", rx.rx_ready, True)
    check(f"SERDIV {serdiv}: words written", rx.rx_words, len(WANT))
    check(f"SERDIV {serdiv}: no partial word, no overrun", (rx.rx_left, rx.rx_over), (0, False))
    check(f"SERDIV {serdiv}: the frame, destination address to FCS", drain(rx), WANT)


# ---- 2. jitter
def manchester_edges(data, half_ns, jitter, rng, start=400.0):
    """Edges (time ns, new level) of a Manchester frame (LSB first, a 1 is low-to-high at mid-bit), idle low before,
    then TP_IDL (6 half-bits high) and idle low. Every edge moved by up to +-jitter ns."""
    halves = []
    for byte in data:
        for k in range(8):
            b = (byte >> k) & 1
            halves += [1 - b, b]
    halves += [1] * 6 + [0]
    edges, level = [], 0
    for i, h in enumerate(halves):
        if h != level:
            edges.append((start + i * half_ns + rng.uniform(-jitter, jitter), h))
            level = h
    return edges


def level_at(edges, t):
    lv = 0
    for et, v in edges:
        if et > t:
            break
        lv = v
    return lv


def jitter_trial(jitter, both, rng):
    edges = manchester_edges(PREAMBLE + BODY + FCS, 50.0, jitter, rng)
    rx = receiver(rxgap=6, both=both, pin=0)
    phase = rng.uniform(0, 25.0)
    end = edges[-1][0] + 400
    k, i, lv = 0, 0, 0
    while True:
        t = 100.0 + phase + 25.0 * k
        if t > end:
            break
        tf = t - 12.5
        while i < len(edges) and edges[i][0] <= tf:
            lv = edges[i][1]; i += 1
        fall = lv
        j, lv2 = i, lv
        while j < len(edges) and edges[j][0] <= t:
            lv2 = edges[j][1]; j += 1
        rx.clock(lv2, pins_fall=fall)
        k += 1
    return rx.rx_ready and drain(rx) == WANT and not rx.rx_over


def test_jitter():
    rng = random.Random(8)
    best = {}
    for both in (True, False):
        good = -1
        for j in range(0, 21):
            ok = all(jitter_trial(float(j), both, rng) for _ in range(20))
            if ok and good == j - 1:
                good = j
        best[both] = good
        print(f"-- jitter, sampling on {'both clock edges' if both else 'the rising edge only'}: every frame right up "
              f"to +-{good} ns per edge")
    check("both edges tolerate at least +-6 ns per edge (12.5 ns sampling, 25 ns decision margin)", best[True] >= 6, True)
    check("both edges tolerate more than the rising edge alone", best[True] > best[False], True)
    return best


# ---- 3. the switch and the interlocks
def test_switch():
    print("-- the direction switch and the interlocks")
    prog = assemble(open(os.path.join(ROOT, "programs", "eth_tx.asm")).read())
    eng = Engine(prog, Config.for_program(prog, out_base=TDP, out_count=2, set_base=TDP, set_count=2, ser=True,
                                           ser_en=True, manch=True, diff=True, rx_pin=0, rxgap=6))
    check("reset: transmit mode", eng.rx_mode, False)
    eng.tx_put(0x1234); eng.clock(0); eng.clock(0)
    eng.clock(0, mode_wr=1)
    check("idle: the change to receive is accepted", (eng.rx_mode, eng.rx_refused), (True, False))
    check("... and the buffer emptied (the transmit word gone)", len(eng.txf), 0)
    eng.tx_put(0xBEEF); eng.clock(0)
    check("receive mode: a host push is refused", len(eng.txf), 0)
    eng.clock(0, arm=True)
    lv = 0
    for _ in range(20):                       # a preamble starts: 1010... at 8 half-clocks a bit
        for b in (1, 0):
            for half in (1 - b, b):
                eng.clock(half, pins_fall=half); eng.clock(half, pins_fall=half)
    check("a frame is coming in (hunting or locked)", eng.rx_state in (RX_HUNT, RX_DATA), True)
    eng.clock(0, mode_wr=0)
    check("mid-frame: the change back to transmit is refused", (eng.rx_mode, eng.rx_refused), (True, True))
    for _ in range(40):
        eng.clock(0)
    check("the line stops: the frame ends (no lock: back to idle)", eng.rx_state in (RX_IDLE,), True)
    eng.clock(0, mode_wr=0)
    check("idle again: the change to transmit is accepted", (eng.rx_mode, eng.rx_refused), (False, False))
    # MOV ser in receive mode: set x, 3 ; mov ser, x
    p = assemble("set x, 3\nmov ser, x\njmp 1\n")
    eng3 = Engine(p, Config.for_program(p, ser=True, ser_en=True))
    eng3.clock(0, mode_wr=1)
    for _ in range(6):
        eng3.clock(0)
    check("receive mode: MOV ser refused (serialiser idle, refused flag)", (eng3.ser_busy, eng3.rx_refused), (False, True))
    # MOV ser in the very clock the change to receive is taken (found by the random tests, 8 Nov): the change wins
    eng5 = Engine(p, Config.for_program(p, ser=True, ser_en=True))
    eng5.clock(0)                                    # set x, 3
    eng5.clock(0, mode_wr=1)                         # mov ser, x  and the keyed write, same clock
    for _ in range(4):
        eng5.clock(0)
    check("MOV ser and the change in one clock: receive mode, serialiser stopped", (eng5.rx_mode, eng5.ser_busy), (True, False))
    # PULL finds the buffer empty in receive mode: words received are not the program's
    p2 = assemble("pull noblock\nmov y, osr\njmp 0\n")
    eng4 = Engine(p2, Config.for_program(p2, ser=True, rx_pin=0, rxgap=6, rx_raw=True))
    eng4.clock(0, mode_wr=1); eng4.clock(0, arm=True)
    eng4.txf.append(0x5A5A); eng4.tx_hv = True       # as if a word had been received
    for _ in range(4):
        eng4.clock(0)
    check("receive mode: PULL finds the buffer empty (y stays 0)", eng4.y, 0)
    check("... and the received word is still there", list(eng4.txf), [0x5A5A])
    eng4.clock(0, arm=True)
    check("arm empties the buffer", len(eng4.txf), 0)
    # a lone link pulse (100 ns high) never starts a frame
    rx = receiver(rxgap=6, pin=0)
    for v in [0] * 10 + [1] * 4 + [0] * 200:
        rx.clock(v, pins_fall=v)
    check("a lone link pulse: no frame, no words", (rx.rx_ready, rx.rx_words, rx.rx_state), (False, 0, RX_IDLE))
    # a frame longer than the buffer: OVERRUN, the first 64 words kept
    long_body = bytes(range(256)) * 1
    edges = manchester_edges(PREAMBLE + long_body[:140], 50.0, 0.0, random.Random(1))
    rx = receiver(rxgap=6, pin=0)
    t, i, lv = 100.0, 0, 0
    while t < edges[-1][0] + 400:
        while i < len(edges) and edges[i][0] <= t:
            lv = edges[i][1]; i += 1
        rx.clock(lv, pins_fall=lv)
        t += 25.0
    got = drain(rx)
    check("140 bytes into a 128-byte buffer: overrun", (rx.rx_ready, rx.rx_over, len(got)), (True, True, 64))
    check("... the first 64 words kept", got, words_le(long_body[:128]))


# ---- 4. the 3/4-bit rule, exactly: an edge RXGAP half-clocks after the last taken one is taken, one earlier is not
def half_samples(rx, samples):
    """Feed the line half-clock by half-clock: pairs (falling-edge sample, rising-edge sample) per clock."""
    samples = list(samples) + [samples[-1]] * (len(samples) % 2)
    for k in range(0, len(samples), 2):
        rx.clock(samples[k + 1], pins_fall=samples[k])


def test_threshold():
    print("-- the 3/4-bit threshold, at the half-clock")
    for second_edge_at, want in ((6, (2, 1)), (5, (1, 1))):
        rx = receiver(rxgap=6, raw=True, pin=0)
        half_samples(rx, [0] * 4 + [1] * second_edge_at + [0] * 40)
        got = drain(rx)
        check(f"second edge {second_edge_at} half-clocks after the first (RXGAP 6): bits in the frame, word",
              (rx.rx_left, got[0] if got else None), want)


test_threshold()
test_loopback(1)
test_loopback(0)
best = test_jitter()
test_switch()
print("PASS" if not fails else "FAIL: " + "; ".join(fails))
sys.exit(1 if fails else 0)
