"""The smallest network conversation: the chip answers ARP and ping (11 Nov 2026).

The chip's engine 0 receives a frame into its buffer and sends one from its TX FIFO; this file is the host's part:
read the received words, check the frame, and build the reply. Plain MicroPython (no zlib, no struct), so the same file
runs on the Pico and in the model test (model/test_netstack.py).

    body = reply(frame)      # frame: the received bytes, destination address to FCS; body: the reply without its FCS,
                             # padded to 60 bytes, or None (not for us, a bad FCS, or nothing we answer)
Answers: ARP requests for MY_IP (an ARP reply with MY_MAC), and ICMP echo requests to MY_IP (an echo reply with the
same identifier, sequence and data). Frames on the wire are 16-bit words, low byte first (words_le, bytes_le).
"""

MY_MAC = bytes([0x02, 0x00, 0x00, 0x00, 0x00, 0x01])     # locally administered
MY_IP = bytes([192, 168, 77, 2])                          # the PC's adapter on 192.168.77.1 (set by hand)
ETH_ARP, ETH_IP = 0x0806, 0x0800


def crc32(data):
    """Ethernet's FCS: reflected polynomial 0xEDB88320, start all ones, complemented (zlib.crc32)."""
    c = 0xFFFFFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ (0xEDB88320 if c & 1 else 0)
    return c ^ 0xFFFFFFFF


def checksum(data):
    """The Internet checksum: the ones' complement of the ones' complement sum of 16-bit words, big-endian."""
    if len(data) % 2:
        data = bytes(data) + b"\0"
    s = 0
    for i in range(0, len(data), 2):
        s += data[i] << 8 | data[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def words_le(data):
    """Bytes to the chip's 16-bit words, low byte first (an odd last byte padded with 0)."""
    if len(data) % 2:
        data = bytes(data) + b"\0"
    return [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]


def bytes_le(words, nbytes=None):
    out = bytearray()
    for w in words:
        out.append(w & 0xFF)
        out.append(w >> 8 & 0xFF)
    return bytes(out if nbytes is None else out[:nbytes])


def u16(b, i):
    return b[i] << 8 | b[i + 1]


def fcs_ok(frame):
    return len(frame) >= 64 and crc32(frame[:-4]) == (frame[-4] | frame[-3] << 8 | frame[-2] << 16 | frame[-1] << 24)


def pad60(b):
    return bytes(b) + bytes(max(0, 60 - len(b)))


def reply(frame, mac=MY_MAC, ip=MY_IP):
    if not fcs_ok(frame):
        return None
    body = frame[:-4]
    kind = u16(body, 12)
    if kind == ETH_ARP and len(body) >= 42:
        a = body[14:42]
        if u16(a, 0) != 1 or u16(a, 2) != ETH_IP or a[4] != 6 or a[5] != 4 or u16(a, 6) != 1 or a[24:28] != ip:
            return None                                    # not an Ethernet/IPv4 ARP request for us
        sha, spa = a[8:14], a[14:18]
        return pad60(sha + mac + b"\x08\x06" + b"\x00\x01\x08\x00\x06\x04\x00\x02" + mac + ip + sha + spa)
    if kind == ETH_IP and len(body) >= 34:
        h = body[14:]
        ihl = (h[0] & 15) * 4
        total = u16(h, 2)
        if h[0] >> 4 != 4 or ihl < 20 or total < ihl + 8 or total > len(h) or h[9] != 1 or h[16:20] != ip:
            return None                                    # IPv4, ICMP, to us, whole
        if u16(h, 6) & 0x3FFF:
            return None                                    # a fragment: not answered
        if checksum(h[:ihl]) != 0:
            return None                                    # a damaged header
        icmp = h[ihl:total]
        if icmp[0] != 8 or icmp[1] != 0 or checksum(icmp) != 0:
            return None                                    # an echo request, undamaged
        rep = bytearray(b"\x00\x00\x00\x00") + icmp[4:]    # type 0 (echo reply), code 0, checksum below, id, seq, data
        c = checksum(rep)
        rep[2], rep[3] = c >> 8, c & 0xFF
        ih = bytearray(h[:ihl])
        ih[8] = 64                                         # TTL
        ih[10] = ih[11] = 0
        ih[12:16], ih[16:20] = ip, h[12:16]                # from us, to the sender
        c = checksum(ih)
        ih[10], ih[11] = c >> 8, c & 0xFF
        return pad60(body[6:12] + mac + b"\x08\x00" + ih + rep)
    return None
