"""First contact: read the chip's ID register (0x2A: [7:4] host port spec 2, [3:0] engines) through the Pico's SPI."""
from chip_host import Chip

chip = Chip()
ids = [chip.chip_id() for _ in range(5)]
print("ID register, five reads:", ["0x%04X" % i for i in ids])
ok = len(set(ids)) == 1 and (ids[0] >> 4) == 2 and (ids[0] & 15) >= 2
print("spec version", ids[0] >> 4, "| engines", ids[0] & 15)
print("PASS" if ok else "FAIL: the lines are wrong or the kit has no build loaded (a dead MISO reads 0x0000 or 0xFFFF)")
