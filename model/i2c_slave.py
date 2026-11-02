"""A model I2C slave for testing the engine's I2C programs: a typical register-pointer device
(sensors, EEPROMs and port expanders all work like this).

  write: START, address+W, pointer byte, data bytes (into regs[pointer], pointer + 1 each) ..., STOP
  read:  START, address+R, data bytes from regs[pointer] (pointer + 1 each, until the master NAKs), STOP

Feed it the bus levels every clock with clock(scl, sda); it returns True while it is pulling SDA low.
It samples SDA on SCL's rising edge and changes SDA just after SCL's falling edge, as the standard says.
Everything it sees is logged (events) so a test can check the transaction byte by byte.
"""


class I2CSlave:
    def __init__(self, address=0x50, nregs=16):
        self.address = address
        self.regs = [0] * nregs
        self.pointer = 0
        self.scl = 1
        self.sda = 1
        self.state = "idle"          # idle, addr, ack_addr, write, ack_write, read, ack_read
        self.shift = 0
        self.nbits = 0
        self.drive_low = False
        self.selected = False
        self.reading = False
        self.master_ack = False
        self.first_write_byte = False
        self.events = []             # ("start", None), ("addr", byte), ("pointer", n), ("write", b), ("read", b), ("nak", None), ("stop", None)

    def _rising(self):
        if self.state in ("addr", "write"):
            self.shift = ((self.shift << 1) | self.sda) & 0xFF
            self.nbits += 1
        elif self.state == "read":
            self.nbits += 1
        elif self.state == "ack_read":
            self.master_ack = (self.sda == 0)

    def _falling(self):
        if self.state == "addr" and self.nbits == 8:
            self.events.append(("addr", self.shift))
            self.selected = (self.shift >> 1) == self.address
            self.reading = bool(self.shift & 1)
            self.state = "ack_addr"
            self.drive_low = self.selected
        elif self.state == "ack_addr":
            self.drive_low = False
            if not self.selected:
                self.state = "idle"
            elif self.reading:
                self.state = "read"
                self._load_read_byte()
            else:
                self.state = "write"
                self.first_write_byte = True
                self.shift, self.nbits = 0, 0
        elif self.state == "write" and self.nbits == 8:
            if self.first_write_byte:
                self.pointer = self.shift % len(self.regs)
                self.events.append(("pointer", self.shift))
                self.first_write_byte = False
            else:
                self.regs[self.pointer] = self.shift
                self.events.append(("write", self.shift))
                self.pointer = (self.pointer + 1) % len(self.regs)
            self.state = "ack_write"
            self.drive_low = True
        elif self.state == "ack_write":
            self.drive_low = False
            self.state = "write"
            self.shift, self.nbits = 0, 0
        elif self.state == "read":
            if self.nbits == 8:
                self.state = "ack_read"
                self.drive_low = False
            else:
                self.drive_low = not ((self.shift >> (7 - self.nbits)) & 1)
        elif self.state == "ack_read":
            if self.master_ack:
                self.state = "read"
                self._load_read_byte()
            else:
                self.events.append(("nak", None))
                self.state = "idle"
                self.drive_low = False

    def _load_read_byte(self):
        self.shift = self.regs[self.pointer]
        self.events.append(("read", self.shift))
        self.pointer = (self.pointer + 1) % len(self.regs)
        self.nbits = 0
        self.drive_low = not ((self.shift >> 7) & 1)      # first bit goes out now (SCL is low)

    def clock(self, scl, sda):
        """One system clock with the bus at these levels. Returns True while the slave pulls SDA low."""
        if self.scl and scl:                              # SDA moving while SCL is high: START or STOP
            if self.sda and not sda:
                self.events.append(("start", None))
                self.state, self.shift, self.nbits = "addr", 0, 0
                self.drive_low = False
            elif not self.sda and sda:
                self.events.append(("stop", None))
                self.state = "idle"
                self.drive_low = False
        if not self.scl and scl:
            self._rising()
        elif self.scl and not scl:
            self._falling()
        self.scl, self.sda = scl, sda
        return self.drive_low
