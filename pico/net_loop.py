"""ARP and ping over the chip's own loopback: a jumper from TD+ (engine pin 1, Mojo hole 34) to engine pin 19 (hole 74).
Engine A, in full duplex with the hardware preamble, sends a frame as Windows would (an ARP request, a ping); its own
receiver catches it; the host checks it arrived whole, builds the answer with netstack.py and sends that the same way;
the answer is caught again and checked field by field, as the PC would read it.
  1. ARP "who has 192.168.77.2?": the reply carries the chip's MAC to the PC's.
  2. Ping, Windows' default 32 bytes: echo reply, same identifier, sequence and data, both checksums right.
  3. Not answered: an ARP for another address.
The FCS is computed by the host (SERCFG without CRC append), as on the Tiny Tapeout chip, which has no CRC unit. The
transmit ring holds 16 words, so the host tops it up at a slow rate (SERDIV 999, 20 kbit/s, as fdx_loop.py part B);
the receive ring's 48 words hold either frame whole. This checks the host's side of the conversation on hardware; the
10 Mbit/s line and a PC come with the receive front end.
Needs the Mojo build with receive and full duplex (build.sh ser clk40). Prints PASS or FAIL.
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script net_loop.py -Seconds 60 -Pre "CHIP_HZ=40_000_000"
Model check (no hardware):  python model/pico_sim.py pico/net_loop.py
"""
import time
from chip_host import Chip, wrap_reg, ENG_A, ENG_B, R_CLKDIV, R_WRAP, R_OUTCFG, R_MISC, R_INCFG, R_STATUS
from programs import PROGRAMS
import netstack

R_TX, R_SERCFG, R_SERDIV, R_SERSTAT = 0x26, 0x2B, 0x2C, 0x33
R_RXCFG, R_RXGAP, R_RXSTAT, R_RXDATA = 0x34, 0x35, 0x36, 0x37
TDP, RXPIN, KEY, FDX = 1, 19, 0xA000, 0x0100
SERCFG = 0x020F                       # enable, Manchester, differential, end marker, hardware preamble; no CRC unit
RING = 16                             # full duplex on the 64-word build: 16 words to send, 48 to receive
try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 40_000_000
try:
    SERDIV
except NameError:
    SERDIV = 999

FRAME_MS = 832 * 2 * (SERDIV + 1) * 1000 // CHIP_HZ + 5   # the longest frame here, 104 bytes with the preamble

PC_MAC = bytes([0xD8, 0x3A, 0xDD, 0x12, 0x34, 0x56])
PC_IP = bytes([192, 168, 77, 1])
errors = 0


def check(what, ok, detail=""):
    global errors
    if not ok:
        errors += 1
    print("  %-66s %s" % (what, "ok" if ok else "WRONG " + detail))


def u16(b, i):
    return b[i] << 8 | b[i + 1]


chip = Chip(CHIP_HZ, 4_000_000 if CHIP_HZ >= 32e6 else 1_000_000)
print("\n==== ARP and ping over the loopback, TD+ (hole 34) -> engine pin 19 (hole 74), SERDIV %d ====" % SERDIV)
print("  chip ID 0x%04X" % chip.chip_id())
pw, wb, wt = PROGRAMS["eth_tx"]
chip.stop(ENG_A)
chip.stop(ENG_B)
chip.load_program(ENG_A, pw)
chip.write(ENG_A, R_CLKDIV, 0)
chip.write(ENG_A, R_WRAP, wrap_reg(0, wb, wt))
chip.write(ENG_A, R_OUTCFG, TDP | (2 << 5) | (TDP << 10))
chip.write(ENG_A, R_MISC, 2 | (1 << 11) | (1 << 12))           # set_count 2, out_right, in_right (LSB first both ways)
chip.write(ENG_A, R_INCFG, 0)
chip.write(ENG_A, R_SERCFG, SERCFG)
chip.write(ENG_A, R_SERDIV, SERDIV)
chip.write(ENG_A, R_RXGAP, 3 * (SERDIV + 1))                   # 3/4 bit in half-clocks
chip.start(ENG_A)
time.sleep_ms(2)
chip.write(ENG_A, R_SERCFG, SERCFG | KEY | FDX)                # keyed: full duplex (the engine must be running)
check("SERCFG [9:7]: hardware preamble, full duplex in force", ((chip.read(ENG_A, R_SERCFG) >> 7) & 7) == 0b110)


def send(body):
    """One frame out: the word count, then the body and the host's FCS, low byte first, topping up the ring."""
    words = netstack.words_le(body + netstack.crc32(body).to_bytes(4, "little"))
    feed = [len(words)] + words
    t0 = time.ticks_ms()
    while feed and time.ticks_diff(time.ticks_ms(), t0) < 3 * FRAME_MS:
        if chip.read(ENG_A, R_SERSTAT) & 0x7F < RING:
            chip.write(ENG_A, R_TX, feed.pop(0))
    while chip.read(ENG_A, R_STATUS) & 0x4000 and time.ticks_diff(time.ticks_ms(), t0) < 3 * FRAME_MS:
        time.sleep_ms(1)
    st = chip.read(ENG_A, R_STATUS)
    return len(feed) == 0 and not st & 0xC000


def receive():
    """The frame the receiver caught (destination address to FCS), or None."""
    t0 = time.ticks_ms()
    st = chip.read(ENG_A, R_RXSTAT)
    while not st & 1 and time.ticks_diff(time.ticks_ms(), t0) < FRAME_MS:
        time.sleep_ms(1)
        st = chip.read(ENG_A, R_RXSTAT)
    if not st & 1 or st & 2:
        return None
    n = (st >> 8) & 0x7F
    return netstack.bytes_le([chip.read(ENG_A, R_RXDATA) for _ in range(n)])


def over_the_wire(body):
    """Arm, send, catch. Returns the frame caught; checks it is the one sent."""
    chip.write(ENG_A, R_RXCFG, RXPIN | 0x40 | 0x80)            # pin 19, both clock edges, arm (empties the buffer)
    sent = send(body)
    got = receive()
    want = body + netstack.crc32(body).to_bytes(4, "little")
    check("  sent whole, no underrun; caught whole (%d bytes)" % len(want), sent and got == want,
          "sent %s, caught %s" % (sent, None if got is None else len(got)))
    return got


# 1. ARP
print("\n-- 1. ARP: who has 192.168.77.2? (from the PC, 192.168.77.1)")
req = netstack.pad60(b"\xff" * 6 + PC_MAC + b"\x08\x06" + b"\x00\x01\x08\x00\x06\x04\x00\x01"
                     + PC_MAC + PC_IP + bytes(6) + netstack.MY_IP)
frame = over_the_wire(req)
body = netstack.reply(frame) if frame else None
check("the host builds an ARP reply", body is not None)
if body:
    back = over_the_wire(body)
    if back:
        a = back[14:42]
        check("reply to the PC's MAC, from the chip's, type 0x0806",
              back[0:6] == PC_MAC and back[6:12] == netstack.MY_MAC and u16(back, 12) == 0x0806)
        check("ARP: Ethernet/IPv4, opcode 2 (reply)", a[0:8] == b"\x00\x01\x08\x00\x06\x04\x00\x02")
        check("ARP: sender = the chip's MAC and IP; target = the PC's",
              a[8:14] == netstack.MY_MAC and a[14:18] == netstack.MY_IP and a[18:24] == PC_MAC and a[24:28] == PC_IP)
        check("FCS right, as the PC's adapter checks it", netstack.fcs_ok(back))

# 2. Ping
print("\n-- 2. ping 192.168.77.2, Windows' default 32 bytes")
data = b"abcdefghijklmnopqrstuvwabcdefghi"
icmp = bytearray(b"\x08\x00\x00\x00\x00\x01\x00\x05" + data)    # echo request, identifier 1, sequence 5
c = netstack.checksum(icmp)
icmp[2], icmp[3] = c >> 8, c & 0xFF
ip = bytearray(b"\x45\x00" + (20 + len(icmp)).to_bytes(2, "big") + b"\x12\x34\x00\x00\x80\x01\x00\x00" + PC_IP
               + netstack.MY_IP)
c = netstack.checksum(ip)
ip[10], ip[11] = c >> 8, c & 0xFF
req = netstack.MY_MAC + PC_MAC + b"\x08\x00" + bytes(ip) + bytes(icmp)
frame = over_the_wire(req)
body = netstack.reply(frame) if frame else None
check("the host builds an echo reply", body is not None)
if body:
    back = over_the_wire(body)
    if back:
        h, m = back[14:34], back[34:34 + len(icmp)]
        check("reply to the PC's MAC, from the chip's, type 0x0800",
              back[0:6] == PC_MAC and back[6:12] == netstack.MY_MAC and u16(back, 12) == 0x0800)
        check("IP: from 192.168.77.2 to 192.168.77.1, ICMP, header checksums to 0",
              h[12:16] == netstack.MY_IP and h[16:20] == PC_IP and h[9] == 1 and netstack.checksum(h) == 0)
        check("ICMP: type 0 (echo reply), identifier 1, sequence 5, the same 32 bytes",
              m[0] == 0 and m[1] == 0 and m[4:8] == b"\x00\x01\x00\x05" and m[8:] == data)
        check("ICMP message checksums to 0", netstack.checksum(m) == 0)
        check("FCS right", netstack.fcs_ok(back))

# 3. Not answered
print("\n-- 3. not answered: an ARP for 192.168.77.9")
req = netstack.pad60(b"\xff" * 6 + PC_MAC + b"\x08\x06" + b"\x00\x01\x08\x00\x06\x04\x00\x01"
                     + PC_MAC + PC_IP + bytes(6) + bytes([192, 168, 77, 9]))
frame = over_the_wire(req)
check("no reply", frame is not None and netstack.reply(frame) is None)

chip.write(ENG_A, R_SERCFG, SERCFG | KEY)                     # idle: back to transmit
chip.stop(ENG_A)
print("\n==== %s (%d problems) ====" % ("FAIL" if errors else "PASS", errors))
