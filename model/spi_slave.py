"""A model SPI slave (mode 0) for testing the engine's SPI programs: a register device of the usual kind.
While CS is low: first byte = command (bit 7: 1 = read, 0 = write; bits 6:0 = register address),
then data bytes to or from consecutive registers. While shifting the command in it answers 0x00;
a read then returns regs[addr], regs[addr+1], ...; a write stores them.

Feed it the pin levels every clock with clock(cs, sck, mosi); it returns the MISO level it drives
(1 while deselected, as if pulled up). It samples MOSI on SCK's rising edge and changes MISO on the falling edge,
and puts its first bit out as soon as CS falls, as the standard says.
"""


class SPISlave:
    def __init__(self, nregs=16):
        self.regs = [0] * nregs
        self.cs = 1
        self.sck = 0
        self.miso = 1
        self.events = []             # ("select",), ("cmd", byte), ("write", addr, byte), ("read", addr, byte), ("deselect",)
        self.reset_frame()

    def reset_frame(self):
        self.shift_in = 0
        self.nbits = 0
        self.out_byte = 0
        self.addr = 0
        self.have_cmd = False
        self.reading = False

    def _rising(self, mosi):
        self.shift_in = ((self.shift_in << 1) | mosi) & 0xFF
        self.nbits += 1
        if self.nbits == 8:
            byte, self.shift_in, self.nbits = self.shift_in, 0, 0
            if not self.have_cmd:
                self.have_cmd = True
                self.reading = bool(byte & 0x80)
                self.addr = byte & 0x7F
                self.events.append(("cmd", byte))
                self.out_byte = self.regs[self.addr % len(self.regs)] if self.reading else 0
            elif self.reading:
                self.events.append(("read", self.addr, self.out_byte))
                self.addr += 1
                self.out_byte = self.regs[self.addr % len(self.regs)]
            else:
                self.regs[self.addr % len(self.regs)] = byte
                self.events.append(("write", self.addr, byte))
                self.addr += 1

    def clock(self, cs, sck, mosi):
        """One system clock with the pins at these levels. Returns the MISO level the slave drives."""
        if cs:
            if not self.cs:
                self.events.append(("deselect",))
            self.cs, self.sck, self.miso = 1, sck, 1
            self.reset_frame()
            return 1
        if self.cs:                                       # CS just fell: first bit out now
            self.events.append(("select",))
            self.miso = (self.out_byte >> 7) & 1
        elif sck and not self.sck:
            self._rising(mosi)
        elif not sck and self.sck:
            self.miso = (self.out_byte >> (7 - self.nbits)) & 1
        self.cs, self.sck = 0, sck
        return self.miso
