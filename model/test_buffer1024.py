"""Engine 0's 1024-word buffer (the Tiny Tapeout chip, 8x4 tiles, 10 Nov 2026), tested on the model.

The host here is as slow as the real one: a word every 128 clocks (the SPI port's 16 bits at 1/8 of the chip clock).
At 10 Mbit/s and 40 MHz (SERDIV 1) the line takes a word every 64 clocks, so a frame longer than the buffer cannot be
fed while it goes out, and the buffer has to hold it.

1. Transmit: a full-size Ethernet frame (1514 bytes and the FCS: 1518 bytes, 759 words on the line) through
   programs/eth_tx.asm with the hardware preamble, looped into a second engine 0 in receive mode. With 1024 words it
   goes out whole, no underrun; the 64-word build underruns.
2. Receive: the frame above is received whole in receive mode (759 words, RXSTAT's count saturating at 127, the exact
   count in RXWORDS); a 1100-word frame overruns and keeps the first 1024.
3. Full duplex, 512 + 512: the same frame sent through the 512-word transmit ring while the engine's own receiver
   catches it into the 512-word receive ring, the host reading a word every 128 clocks: both whole. The 64-word build's
   16 + 48 rings lose it.
Run:  python model/test_buffer1024.py
"""
import os, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config, fdx_split, MODE_FDX, MODE_RX, ASIC_SER_DEPTH

fails = []
HOST_GAP = 128                                    # clocks per host word (SPI at 1/8 of the chip clock, 16 bits)
TDP = 8


def check(what, got, want):
    ok = got == want
    show = (lambda v: f"[{len(v)} words]" if isinstance(v, list) and len(v) > 8 else repr(v))
    print(f"{'ok:  ' if ok else 'FAIL:'} {what} = {show(got)}" + ("" if ok else f", expected {show(want)}"))
    if not ok:
        fails.append(what)
    return ok


def words_le(data):
    data = bytes(data) + (b"\0" if len(data) % 2 else b"")
    return [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]


BODY = bytes.fromhex("ffffffffffff" "020000000001" "88b5") + bytes((i * 7 + 3) & 255 for i in range(1500))
FCS = zlib.crc32(BODY).to_bytes(4, "little")
WANT = words_le(BODY + FCS)                       # 759 words: destination address to FCS
PROG = assemble(open(os.path.join(ROOT, "programs", "eth_tx.asm")).read())


def eth_cfg(depth, **kw):
    return Config.for_program(PROG, out_base=TDP, out_count=2, set_base=TDP, set_count=2, out_right=True, in_right=True,
                              serdiv=1, ser=True, ser_depth=depth, ser_en=True, manch=True, diff=True, end_marker=True,
                              crc_append=True, crc_cpl=True, crc_ser=True, crc_skip=0, pre=True, crcpoly=0xEDB88320,
                              crcinit=0xFFFFFFFF, rx_pin=TDP, rxgap=6, **kw)


def receiver(depth):
    eng = Engine([0] * 32, Config(ser=True, ser_depth=depth, rx_pin=TDP, rxgap=6, in_right=True))
    eng.clock(0, mode_wr=MODE_RX)
    eng.clock(0, arm=True)
    return eng


def drain(eng, limit=4000):
    got = []
    for _ in range(limit):
        eng.clock(0, bpop=True)
        if eng.bpopped is not None:
            got.append(eng.bpopped)
    return got


def send(depth, clocks=200_000):
    """The frame from a transmit engine, the host feeding a word every HOST_GAP clocks, into a receiving engine."""
    tx, rx = Engine(PROG, eth_cfg(depth)), receiver(depth)
    feed = [len(WANT) - 2] + words_le(BODY)       # the count (data words; the CRC unit appends the FCS), then the data
    peak = 0
    for t in range(clocks):
        if feed and t % HOST_GAP == 0 and tx.tx_put(feed[0]):
            feed.pop(0)
        tx.clock(0)
        rx.clock(tx.pins_out)
        peak = max(peak, tx.serlevel)
        if not feed and not tx.ser_busy and rx.rx_ready:
            break
    return tx, rx, peak, feed


print(f"-- full duplex split: 64 words {fdx_split(64)}, {ASIC_SER_DEPTH} words {fdx_split(ASIC_SER_DEPTH)}")
check("1024 words: 512 transmit + 512 receive", fdx_split(1024), (512, 512))
check("64 words: unchanged, 16 + 48", fdx_split(64), (16, 48))

# ---- 1 and 2: transmit a full-size frame, receive it
tx, rx, peak, feed = send(1024)
print(f"-- 1024 words: a {len(BODY) + 4}-byte frame, host a word every {HOST_GAP} clocks: buffer peak {peak} words")
check("1024: the frame went out whole (no underrun, nothing left to feed)", (tx.ser_under, len(feed)), (False, 0))
check("1024: the serialiser waited for the whole frame (peak = every data word; the program took the count)", peak,
      len(WANT) - 2)
check("1024: received in receive mode (ready, no overrun, whole words)", (rx.rx_ready, rx.rx_over, rx.rx_left),
      (True, False, 0))
check("1024: RXWORDS (0x39) holds the exact count", rx.rxwords, len(WANT))
check("1024: RXSTAT [14:8] saturates at 127", (rx.rxstat >> 8) & 127, 127)
check("1024: the received frame, destination address to FCS", drain(rx), WANT)

tx, rx, peak, feed = send(64)
print(f"-- 64 words, the same frame and host: buffer peak {peak} words")
check("64: the serialiser starts when the buffer is full and runs dry: underrun", tx.ser_under, True)

# a frame longer than the buffer in receive mode: overrun, the first 1024 words kept
rx = receiver(1024)
long_words = [(i * 2654435761) & 0xFFFF for i in range(1100)]
data = b"".join(w.to_bytes(2, "little") for w in long_words)
src = Engine(PROG, eth_cfg(1024))
feed = [1100 - 2] + long_words[:1098]             # 1098 data words + the 2-word FCS = 1100 words on the line
for t in range(200_000):
    if feed and src.tx_put(feed[0]):              # a fast host here: only the receiver is under test
        feed.pop(0)
    src.clock(0)
    rx.clock(src.pins_out)
    if not feed and not src.ser_busy and rx.rx_ready:
        break
got = drain(rx)
print(f"-- receive mode, an 1100-word frame into 1024 words: {len(got)} kept")
check("1100 words into 1024: overrun, ready", (rx.rx_over, rx.rx_ready), (True, True))
check("... RXWORDS counts the words written (1024)", rx.rxwords, 1024)
check("... the first 1024 words kept", got, long_words[:1024])


# ---- 3. full duplex: the frame out of the 512-word transmit ring and back into the 512-word receive ring
def full_duplex(depth, clocks=300_000):
    eng = Engine(PROG, eth_cfg(depth))
    eng.clock(0, mode_wr=MODE_FDX)
    eng.clock(0, arm=True)
    feed = [len(WANT) - 2] + words_le(BODY)
    got, pins, tpeak, rpeak = [], 0, 0, 0
    for t in range(clocks):
        if feed and t % HOST_GAP == 0 and eng.tx_put(feed[0]):
            feed.pop(0)
        eng.clock(pins, bpop=(t % HOST_GAP == HOST_GAP // 2))     # the host reads a word every HOST_GAP clocks too
        if eng.bpopped is not None:
            got.append(eng.bpopped)
        tpeak, rpeak = max(tpeak, len(eng.txf)), max(rpeak, len(eng.rxb))
        pins = eng.pins_out                       # TD+ straight back into the receive pin
        if not feed and not eng.ser_busy and eng.rx_ready:
            break
    return eng, got + drain(eng), tpeak, rpeak, feed


eng, got, tpeak, rpeak, feed = full_duplex(1024)
print(f"-- full duplex, 1024 words: transmit ring peak {tpeak}, receive ring peak {rpeak}")
check("full duplex 1024: transmit ring within 512, receive ring within 512", (tpeak <= 512, rpeak <= 512), (True, True))
check("full duplex 1024: frame sent whole (no underrun)", (eng.ser_under, len(feed)), (False, 0))
check("full duplex 1024: frame received whole (no overrun)", (eng.rx_ready, eng.rx_over), (True, False))
check("full duplex 1024: received = destination address to FCS", got, WANT)

eng, got, tpeak, rpeak, feed = full_duplex(64)
print(f"-- full duplex, 64 words, the same frame and host: transmit ring peak {tpeak}, receive ring peak {rpeak}")
check("full duplex 64: the 16-word ring runs dry: underrun", eng.ser_under, True)

print("PASS" if not fails else "FAIL: " + "; ".join(fails))
sys.exit(1 if fails else 0)
