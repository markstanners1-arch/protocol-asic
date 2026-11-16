"""Why is IRQ high? Reads the IRQ pin, each engine's STATUS (RX level in bits 6:4) and engine A's receiver word count
(RXWORDS, 0x39), drains every RX FIFO, then reads them again.
Run:  pwsh D:/ProtocolASIC/pico/run.ps1 -Script irq_diag.py -Seconds 10 -Pre "CHIP_HZ=40_000_000" """
from chip_host import Chip, R_STATUS, R_RX
try:
    CHIP_HZ
except NameError:
    CHIP_HZ = 40_000_000
chip = Chip(CHIP_HZ, 4_000_000)
R_RXWORDS = 0x39


def show(when):
    st = [chip.read(e, R_STATUS) for e in range(4)]
    print("%-14s IRQ pin %d | STATUS %s | RX levels %s | A RXWORDS %d" % (
        when, chip.irq.value(), " ".join("%04X" % s for s in st), [(s >> 4) & 7 for s in st], chip.read(0, R_RXWORDS)))


show("as found")
for e in range(4):
    for _ in range(8):
        if not (chip.read(e, R_STATUS) & 0x70):
            break
        chip.read(e, R_RX)
show("RX drained")
print("PASS (diagnostic only)")
