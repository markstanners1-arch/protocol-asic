"""The low-speed USB reference (model/usb_line.py) against known values.

1. CRCs against packets whose bytes are known: SETUP to address 0 endpoint 0 is 2D 00 10 (every bus capture of an
   enumeration starts so); the three token examples of USB's CRC paper (address 15 endpoint E: 10111, 3A/A: 11100,
   70/4: 01110, written MSB first); GET_DESCRIPTOR (device, 64 bytes) 80 06 00 01 00 00 40 00 with CRC bytes DD 94,
   and with 18 bytes E0 F4; a zero-length data packet's CRC is 00 00. The residues (01100 and 0x800D, unreflected).
2. The line: SYNC is KJKJKJKK, an ACK is SYNC then KJJKJJKK... checked symbol by symbol; the EOP is SE0 SE0 J.
3. Stuffing: six 1s get a 0 (also when they end the packet, before the EOP), seven 1s decode as a stuff error; random
   packets go through encode and decode unchanged; a corrupted CRC or PID is reported.
Run:  python model/test_usb_line.py
"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb_line as U

fails = []


def check(what, got, want):
    ok = got == want
    print(f"{'ok:  ' if ok else 'FAIL:'} {what} = {got!r}" + ("" if ok else f", expected {want!r}"))
    if not ok:
        fails.append(what)
    return ok


def msb5(v):
    return f"{v:05b}"[::-1]


def run():
    print("-- 1. CRCs")
    check("SETUP addr 0 ep 0", U.token(U.PID_SETUP, 0, 0).hex(" "), "2d 00 10")
    check("CRC5 addr 15 ep E (MSB first)", msb5(U.crc5(0x15 | 0xE << 7)), "10111")
    check("CRC5 addr 3A ep A (MSB first)", msb5(U.crc5(0x3A | 0xA << 7)), "11100")
    check("CRC5 addr 70 ep 4 (MSB first)", msb5(U.crc5(0x70 | 0x4 << 7)), "01110")
    check("GET_DESCRIPTOR 64: CRC16 bytes", U.data(U.PID_DATA0, bytes.fromhex("8006000100004000"))[-2:].hex(" "), "dd 94")
    check("GET_DESCRIPTOR 18: CRC16 bytes", U.data(U.PID_DATA0, bytes.fromhex("8006000100001200"))[-2:].hex(" "), "e0 f4")
    check("zero-length DATA1", U.data(U.PID_DATA1).hex(" "), "4b 00 00")
    check("PID bytes IN, ACK, NAK, DATA0", [U.pid_byte(p) for p in (U.PID_IN, U.PID_ACK, U.PID_NAK, U.PID_DATA0)],
          [0x69, 0xD2, 0x5A, 0xC3])
    rnd = random.Random(5)
    res16 = {U.crc16_reg(U.data(U.PID_DATA0, bytes(rnd.getrandbits(8) for _ in range(rnd.randrange(9))))[1:])
             for _ in range(200)}
    check("CRC16 residue over 200 random packets", res16, {U.CRC16_RESIDUE})
    check("CRC16 residue unreflected", int(f"{U.CRC16_RESIDUE:016b}"[::-1], 2), 0x800D)
    res5 = {U.crc5_reg(t[1] | t[2] << 8, 16) for t in (U.token(U.PID_IN, a, e) for a in range(128) for e in range(16))}
    check("CRC5 residue over every address and endpoint", res5, {U.CRC5_RESIDUE})
    check("CRC5 residue unreflected", msb5(U.CRC5_RESIDUE), "01100")

    print("-- 2. the line")
    s = U.encode(U.handshake(U.PID_ACK))
    check("SYNC", "".join(s[:8]), "KJKJKJKK")
    # ACK 0xD2 LSB first 0 1 0 0 1 0 1 1 from K: J J K J J K K K  (0 changes, 1 keeps)
    check("ACK after SYNC", "".join(s[8:16]), "JJKJJKKK")
    check("EOP", s[-3:], [U.SE0, U.SE0, U.J])
    check("keep-alive", U.keepalive(), [U.SE0, U.SE0, U.J])
    check("levels J K SE0 (D+, D-)", [U.LEVELS[x] for x in (U.J, U.K, U.SE0)], [(0, 1), (1, 0), (0, 0)])
    check("chip words of an IN token to 1/1", [f"{w:04x}" for w in U.words_of(U.token(U.PID_IN, 1, 1))],
          ["6980", "5881"])
    check("chip words of an ACK", [f"{w:04x}" for w in U.words_of(U.handshake(U.PID_ACK))], ["d280"])

    print("-- 3. stuffing and round trips")
    check("six 1s get a 0", U.stuff([1] * 6 + [1]), [1] * 6 + [0, 1])
    check("unstuff", U.unstuff([1] * 6 + [0, 1]), ([1] * 7, []))
    check("seven 1s: stuff error", U.unstuff([1] * 7)[1], ["stuff error at bit 6"])
    tail = U.data(U.PID_DATA0, b"\xff")             # FF then its CRC: 1s across the byte ends
    sym = U.encode(tail)
    pkt, errs = U.decode(sym)
    check("FF data round trip", (pkt, errs), (tail, []))
    six_end = bytes([0xFC])                          # ends ...111111: a stuff bit before the EOP
    bits = U.stuff(U.bits_lsb(bytes([U.SYNC]) + six_end))
    check("six 1s at the end: stuffed before the EOP", bits[-7:], [1] * 6 + [0])
    check("... and decoded", U.decode(U.nrzi(bits) + U.EOP), (six_end, []))
    bad_round = 0
    for i in range(500):
        kind = rnd.randrange(3)
        if kind == 0:
            p = U.token(rnd.choice([U.PID_IN, U.PID_OUT, U.PID_SETUP]), rnd.randrange(128), rnd.randrange(16))
        elif kind == 1:
            p = U.data(rnd.choice([U.PID_DATA0, U.PID_DATA1]),
                       bytes(rnd.choice([0, 0xFF, rnd.getrandbits(8)]) for _ in range(rnd.randrange(9))))
        else:
            p = U.handshake(rnd.choice([U.PID_ACK, U.PID_NAK, U.PID_STALL]))
        got, errs = U.decode(U.encode(p))
        pid, perrs = U.check_packet(got)
        bad_round += (got != p) or bool(errs) or bool(perrs) or pid != p[0] & 15
    check("500 random packets: encode, decode, checks clean", bad_round, 0)
    p = bytearray(U.data(U.PID_DATA1, b"\x01\x02\x03")); p[2] ^= 4
    check("one data bit flipped: CRC16 error", U.check_packet(bytes(p))[1], ["CRC16"])
    p = bytearray(U.token(U.PID_IN, 5, 1)); p[1] ^= 1
    check("one address bit flipped: CRC5 error", U.check_packet(bytes(p))[1], ["CRC5"])
    check("bad PID check", U.check_packet(bytes([0x6A]))[1], ["PID check", "handshake length"][:1])
    return len(fails)


if __name__ == "__main__":
    bad = run()
    print("\n==== %s (%d problems) ====" % ("FAIL" if bad else "PASS", bad))
    sys.exit(1 if bad else 0)
