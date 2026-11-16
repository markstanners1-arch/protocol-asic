"""The chip answers ARP and ping, wire to wire on the model (11 Nov 2026).

A "PC" (an engine running programs/eth_tx.asm) sends Windows-style requests at 10 Mbit/s, 40 MHz; the chip's engine 0
receives them in receive mode; the host's pico/netstack.py builds the replies; the chip sends them back through its own
serialiser (eth_tx.asm, hardware preamble, the FCS computed by the host as the Tiny Tapeout chip has no CRC unit); a
second receiver (the PC's side) catches them. Each reply is checked byte for byte against one built independently here
with struct and zlib, the way Windows would check it.
1. ARP: "who has 192.168.77.2?" answered with the chip's MAC.
2. Ping, Windows' default 32 bytes ("abcdefghijklmnopqrstuvwabcdefghi"): echo reply, same id, sequence and data,
   checksums right. Fits the Mojo build's 64-word buffer.
3. Ping with 1472 bytes (the largest unfragmented): needs the 1024-word buffer; the 64-word build overruns.
4. Not answered: an ARP for another address, a ping to another address, a damaged frame (bad FCS), an IPv6 frame.
Run:  python model/test_netstack.py
"""
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "pico"))
from asm import assemble  # noqa: E402
from engine import Engine, Config, MODE_RX  # noqa: E402
import netstack  # noqa: E402

PROG = assemble(open(os.path.join(ROOT, "programs", "eth_tx.asm")).read())
TDP = 8
HOST_GAP = 128                         # clocks per host word (SPI at 1/8 of the chip clock, 16 bits)
PC_MAC = bytes.fromhex("d83add123456")
PC_IP = bytes([192, 168, 77, 1])
fails = []


def check(what, got, want):
    ok = got == want
    print(f"{'ok:  ' if ok else 'FAIL:'} {what}" + ("" if ok else f": got {got!r}, expected {want!r}"))
    if not ok:
        fails.append(what)


def tx_cfg(depth):
    return Config.for_program(PROG, out_base=TDP, out_count=2, set_base=TDP, set_count=2, out_right=True, in_right=True,
                              serdiv=1, ser=True, ser_depth=depth, ser_en=True, manch=True, diff=True, end_marker=True,
                              pre=True, crc_unit=False)


def wire(body, depth):
    """body (without FCS) out of a transmit engine, the host appending the FCS and feeding a word every HOST_GAP
    clocks, into an engine 0 in receive mode; returns the received bytes (destination address to FCS) and the
    receiver."""
    words = netstack.words_le(body + zlib.crc32(body).to_bytes(4, "little"))
    tx = Engine(PROG, tx_cfg(depth))
    rx = Engine([0] * 32, Config(ser=True, ser_depth=depth, rx_pin=TDP, rxgap=6, in_right=True))
    rx.clock(0, mode_wr=MODE_RX)
    rx.clock(0, arm=True)
    feed = [len(words)] + words
    for t in range(400_000):
        if feed and t % HOST_GAP == 0 and tx.tx_put(feed[0]):
            feed.pop(0)
        tx.clock(0)
        rx.clock(tx.pins_out)
        if not feed and not tx.ser_busy and rx.rx_ready:
            break
    got = []
    for _ in range(4000):
        rx.clock(0, bpop=True)
        if rx.bpopped is not None:
            got.append(rx.bpopped)
    return netstack.bytes_le(got), rx


def converse(request, depth=64):
    """PC -> chip, the host's reply, chip -> PC. Returns (the reply as the PC received it, the chip's receiver)."""
    frame, rx = wire(request, depth)
    body = netstack.reply(frame)
    if body is None:
        return None, rx
    back, _ = wire(body, depth)
    return back, rx


def csum(b):                           # an independent Internet checksum, for the expected replies
    if len(b) % 2:
        b += b"\0"
    s = sum(struct.unpack(f"!{len(b) // 2}H", b))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def with_fcs(body):
    body = body + bytes(max(0, 60 - len(body)))
    return body + zlib.crc32(body).to_bytes(4, "little")


def arp(op, sha, spa, tha, tpa, dst):
    return dst + sha + b"\x08\x06" + struct.pack("!HHBBH", 1, 0x0800, 6, 4, op) + sha + spa + tha + tpa


def ipv4(src, dst, payload, ttl, ident=0x1234):
    h = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), ident, 0, ttl, 1, 0, src, dst)
    return h[:10] + struct.pack("!H", csum(h)) + h[12:] + payload


def icmp(typ, ident, seq, data):
    m = struct.pack("!BBHHH", typ, 0, 0, ident, seq) + data
    return m[:2] + struct.pack("!H", csum(m)) + m[4:]


def ping(data, to=netstack.MY_IP, seq=5):
    return netstack.MY_MAC + PC_MAC + b"\x08\x00" + ipv4(PC_IP, to, icmp(8, 1, seq, data), 128)


def pong(data, seq=5):
    return PC_MAC + netstack.MY_MAC + b"\x08\x00" + ipv4(netstack.MY_IP, PC_IP, icmp(0, 1, seq, data), 64)


# 1. ARP
req = arp(1, PC_MAC, PC_IP, bytes(6), netstack.MY_IP, b"\xff" * 6) + bytes(18)
got, rx = converse(req)
check("ARP request received whole (32 words in the 64-word buffer)", (rx.rxwords, rx.rx_over), (32, False))
check("ARP reply on the wire = the expected reply, FCS right",
      got, with_fcs(arp(2, netstack.MY_MAC, netstack.MY_IP, PC_MAC, PC_IP, PC_MAC)))

# 2. Ping, Windows' default
data = b"abcdefghijklmnopqrstuvwabcdefghi"
got, rx = converse(ping(data))
check("ping (32 bytes) received whole in the 64-word buffer", (rx.rxwords, rx.rx_over), (39, False))
check("echo reply on the wire = the expected reply (same id, sequence, data; checksums right)", got, with_fcs(pong(data)))
if got:
    check("... its IP header checksums to 0, as Windows checks it", csum(got[14:34]), 0)
    check("... its ICMP message checksums to 0", csum(got[34:34 + 8 + len(data)]), 0)

# 3. Ping, 1472 bytes
big = bytes((i * 13 + 7) & 255 for i in range(1472))
got, rx = converse(ping(big, seq=9), depth=1024)
check("ping (1472 bytes, a 1518-byte frame) in the 1024-word buffer: echo reply right", got, with_fcs(pong(big, seq=9)))
got, rx = converse(ping(big, seq=9), depth=64)
check("... the 64-word build overruns and does not answer", (rx.rx_over, got), (True, None))

# 4. Not answered
check("ARP for another address: no reply",
      converse(arp(1, PC_MAC, PC_IP, bytes(6), bytes([192, 168, 77, 9]), b"\xff" * 6) + bytes(18))[0], None)
check("ping to another address: no reply", converse(ping(data, to=bytes([192, 168, 77, 9])))[0], None)
frame = with_fcs(ping(data))
damaged = frame[:-1] + bytes([frame[-1] ^ 1])            # only the FCS can catch this: every other check passes
check("a damaged frame (bad FCS): no reply", netstack.reply(damaged), None)
damaged = frame[:40] + bytes([frame[40] ^ 4]) + frame[41:]
check("a damaged ICMP sequence number with a good FCS (the ICMP checksum catches it): no reply",
      netstack.reply(damaged[:-4] + zlib.crc32(damaged[:-4]).to_bytes(4, "little")), None)
check("an IPv6 frame: no reply", netstack.reply(with_fcs(netstack.MY_MAC + PC_MAC + b"\x86\xdd" + bytes(60))), None)

print("PASS" if not fails else "FAIL: " + "; ".join(fails))
sys.exit(1 if fails else 0)
