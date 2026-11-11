"""Low-speed USB line reference (USB 2.0 chapters 7 and 8): the calculated values the engine's USB mode
and the model keyboard (model/usb_kbd.py) are checked against. Plain and literal.

Line states, low speed (the device's 1.5 k pull-up is on D-):  J = (D+ 0, D- 1)  idle;  K = (1, 0);  SE0 = (0, 0).
A packet on the wire: SYNC (the byte 0x80, LSB first: KJKJKJKK from idle), the PID byte, any data, all LSB first, with
bit stuffing (a 0 after every six 1s in a row, counted from SYNC on) and NRZI (a 0 changes the level, a 1 keeps it);
then the EOP: SE0 for two bit times and J for one.

    encode(packet)          -> symbols, SYNC to EOP:  e.g. encode(handshake(ACK))
    decode(symbols)         -> (packet bytes, [errors])
    token(PID_IN, 1, 1), data(PID_DATA0, b"..."), handshake(PID_ACK)
    crc5(addr | ep << 7), crc16(payload), and the residues a receiver checks
"""
J, K, SE0, SE1 = "J", "K", "0", "1"
LEVELS = {J: (0, 1), K: (1, 0), SE0: (0, 0), SE1: (1, 1)}     # (D+, D-)


def sym_of(dp, dm):
    return {(0, 1): J, (1, 0): K, (0, 0): SE0, (1, 1): SE1}[(dp & 1, dm & 1)]


# PIDs (the low nibble; the byte on the wire carries its complement in the high nibble)
PID_OUT, PID_IN, PID_SOF, PID_SETUP = 0x1, 0x9, 0x5, 0xD
PID_DATA0, PID_DATA1 = 0x3, 0xB
PID_ACK, PID_NAK, PID_STALL = 0x2, 0xA, 0xE
PID_NAMES = {PID_OUT: "OUT", PID_IN: "IN", PID_SOF: "SOF", PID_SETUP: "SETUP", PID_DATA0: "DATA0",
             PID_DATA1: "DATA1", PID_ACK: "ACK", PID_NAK: "NAK", PID_STALL: "STALL"}
SYNC = 0x80


def pid_byte(pid):
    return (pid & 15) | ((pid & 15) ^ 15) << 4


def pid_ok(b):
    return (b >> 4) == ((b & 15) ^ 15)


# CRCs: the reflected (right-shifting) form, as the chip's CRC unit and the fixed checker hold them.
CRC5_POLY, CRC16_POLY = 0x14, 0xA001            # x^5 + x^2 + 1 and x^16 + x^15 + x^2 + 1, reflected
CRC5_RESIDUE, CRC16_RESIDUE = 0b00110, 0xB001   # the register after the data and its CRC (01100 and 0x800D unreflected)


def crc_bit(reg, poly, bit):
    return (reg >> 1) ^ poly if (reg ^ bit) & 1 else reg >> 1


def crc5_reg(value, nbits, reg=0x1F):
    for i in range(nbits):
        reg = crc_bit(reg, CRC5_POLY, (value >> i) & 1)
    return reg


def crc5(value11):
    """The CRC5 field of a token: over the 7 address and 4 endpoint bits, start all ones, sent complemented."""
    return crc5_reg(value11, 11) ^ 0x1F


def crc16_reg(data, reg=0xFFFF):
    for byte in data:
        for i in range(8):
            reg = crc_bit(reg, CRC16_POLY, (byte >> i) & 1)
    return reg


def crc16(data):
    """The CRC16 field of a data packet: over the data bytes, start all ones, sent complemented, low byte first."""
    return crc16_reg(data) ^ 0xFFFF


# ---- packets (without SYNC; encode() adds it)
def token(pid, addr, ep):
    v = (addr & 0x7F) | (ep & 15) << 7
    v |= crc5(v) << 11
    return bytes([pid_byte(pid), v & 0xFF, v >> 8])


def data(pid, payload=b""):
    payload = bytes(payload)
    return bytes([pid_byte(pid)]) + payload + crc16(payload).to_bytes(2, "little")


def handshake(pid):
    return bytes([pid_byte(pid)])


def check_packet(pkt):
    """What a receiver concludes about a packet's bytes: (pid nibble, [errors])."""
    errs = []
    if not pkt:
        return None, ["empty"]
    if not pid_ok(pkt[0]):
        errs.append("PID check")
    pid = pkt[0] & 15
    if pid in (PID_OUT, PID_IN, PID_SETUP, PID_SOF):
        if len(pkt) != 3:
            errs.append("token length")
        elif crc5_reg(pkt[1] | pkt[2] << 8, 16) != CRC5_RESIDUE:
            errs.append("CRC5")
    elif pid in (PID_DATA0, PID_DATA1):
        if len(pkt) < 3:
            errs.append("data length")
        elif crc16_reg(pkt[1:]) != CRC16_RESIDUE:
            errs.append("CRC16")
    elif len(pkt) != 1:
        errs.append("handshake length")
    return pid, errs


# ---- bits, stuffing, NRZI
def bits_lsb(data):
    return [(b >> i) & 1 for b in data for i in range(8)]


def bytes_lsb(bits):
    return bytes(sum(bits[i + j] << j for j in range(8)) for i in range(0, len(bits) - len(bits) % 8, 8))


def stuff(bits):
    out, ones = [], 0
    for b in bits:
        out.append(b)
        ones = ones + 1 if b else 0
        if ones == 6:
            out.append(0)
            ones = 0
    return out


def unstuff(bits):
    """Drop the 0 after each six 1s. Returns (bits, errors): a 1 there (seven 1s) is a stuff error."""
    out, ones, errs = [], 0, []
    for i, b in enumerate(bits):
        if ones == 6:
            if b:
                errs.append(f"stuff error at bit {i}")
            ones = 0
            continue
        out.append(b)
        ones = ones + 1 if b else 0
    return out, errs


def nrzi(bits, level=J):
    out = []
    for b in bits:
        if b == 0:
            level = K if level == J else J
        out.append(level)
    return out


def unnrzi(symbols, level=J):
    out = []
    for s in symbols:
        out.append(1 if s == level else 0)
        level = s
    return out


EOP = [SE0, SE0, J]


def encode(packet):
    """SYNC, the packet, stuffed and NRZI-coded from idle J, then the EOP: one symbol per bit time."""
    return nrzi(stuff(bits_lsb(bytes([SYNC]) + bytes(packet)))) + list(EOP)


def keepalive():
    return list(EOP)


def decode(symbols):
    """Symbols from the first K to the EOP (idle J before it). Returns (packet bytes after SYNC, [errors])."""
    errs = []
    try:
        end = symbols.index(SE0)
    except ValueError:
        return b"", ["no EOP"]
    if SE1 in symbols[:end]:
        errs.append("SE1")
    bits, e = unstuff(unnrzi(symbols[:end]))
    errs += e
    if bits[:8] != [0] * 7 + [1]:
        errs.append("SYNC")
    body = bits[8:]
    if len(body) % 8:
        errs.append(f"{len(body)} bits: not whole bytes")
    return bytes_lsb(body), errs


def words_of(packet):
    """The chip's transmit words for one packet: SYNC | PID << 8, then the bytes two to a word, low byte first (an odd
    count leaves the last word's high byte 0; MOV ser's byte count says how much of it is sent)."""
    b = bytes([SYNC]) + bytes(packet)
    b += b"\0" * (len(b) % 2)
    return [b[i] | b[i + 1] << 8 for i in range(0, len(b), 2)]
