"""Run a Pico host script (pico/*.py) on the PC against the engine model, before it goes near the bench (11 Nov 2026).

A stand-in for pico/chip_host.Chip drives engine A of the model (model/engine.py) through the host registers the
script uses, and a stand-in for MicroPython's time module keeps the model's clock: each host transaction costs SPI_US
of chip time, and sleep_ms / ticks_ms run on the same clock. Pins: engine pin 1 (TD+) is wired to engine pin 19, the
loopback jumper of fdx_loop.py, eth_loop_rate.py and net_loop.py.
Covered: engine A's CTRL, CLKDIV, WRAP, OUTCFG, MISC, INCFG, TX, STATUS, ID, SERCFG (the keyed mode change), SERDIV,
SERSTAT, RXCFG, RXGAP, RXSTAT, RXDATA, and load_program. Anything else stops the run, so a script cannot pass on a
register the stand-in ignores. Engine B: stop only. The 64-word build (ser_depth 64), no CRC unit.
Run:  python model/pico_sim.py pico/net_loop.py [NAME=value ...]     (each NAME=value is set before the script runs)
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from engine import Engine, Config  # noqa: E402

CHIP_HZ = 40_000_000
SPI_US = 30                      # one host register access in MicroPython (call, two SPI transfers, CS gaps)
LOOP_FROM, LOOP_TO = 1, 18


class Sim:
    def __init__(self):
        self.t = 0                                   # chip clocks since the start
        self.cfg = Config(ser=True, ser_depth=64, crc_unit=False)
        self.prog = [0] * 32
        self.eng = None                              # None while engine A is stopped (held in reset)

    def run(self, n, **last):
        """n clocks; the host's action (push, mode_wr, arm, bpop) on the last of them."""
        e = self.eng
        for i in range(n):
            if e is not None:
                pins = ((e.pins_out >> LOOP_FROM) & 1) << LOOP_TO
                e.clock(pins, **(last if i == n - 1 else {}))
        self.t += n

    def access(self):
        self.run(SPI_US * CHIP_HZ // 1_000_000 - 1)


SIM = Sim()


class FakeTime(types.ModuleType):
    def __init__(self):
        super().__init__("time")

    @staticmethod
    def sleep_ms(n):
        SIM.run(n * CHIP_HZ // 1000)

    @staticmethod
    def sleep_us(n):
        SIM.run(max(1, n * CHIP_HZ // 1_000_000))

    @staticmethod
    def ticks_ms():
        return SIM.t * 1000 // CHIP_HZ

    @staticmethod
    def ticks_diff(a, b):
        return a - b


class Chip:
    def __init__(self, chip_hz=CHIP_HZ, spi_hz=1_000_000):
        assert chip_hz == CHIP_HZ, "the stand-in runs at 40 MHz"

    @staticmethod
    def cmd(rd, eng, reg):
        return (0x8000 if rd else 0) | ((eng & 7) << 12) | (reg & 0x3F)

    def write(self, eng, reg, v):
        c, s = SIM.cfg, SIM
        s.access()
        if eng != 0:
            if reg == 0x20 and v == 0:
                return s.run(1)
            raise NotImplementedError("engine %d register 0x%02X" % (eng, reg))
        act = {}
        if reg == 0x20:                                          # CTRL
            if v & 1 and s.eng is None:
                s.eng = Engine(s.prog, c)
            elif not v & 1:
                s.eng = None
        elif reg == 0x21:
            c.clkdiv = v
        elif reg == 0x22:
            c.start, c.wrap_bottom, c.wrap_top = v & 31, (v >> 5) & 31, (v >> 10) & 31
        elif reg == 0x23:
            c.out_base, c.out_count, c.set_base = v & 31, (v >> 5) & 31, (v >> 10) & 31
        elif reg == 0x24:
            c.set_count, c.side_base, c.side_count = v & 7, (v >> 3) & 31, (v >> 8) & 3
            c.side_opt, c.out_right, c.in_right, c.side_dir = bool(v >> 10 & 1), bool(v >> 11 & 1), bool(v >> 12 & 1), bool(v >> 13 & 1)
        elif reg == 0x25:
            c.in_base, c.jmp_pin, c.fault_addr = v & 31, (v >> 5) & 31, (v >> 10) & 31
        elif reg == 0x26:
            act["push"] = v
        elif reg == 0x2B:                                        # SERCFG: the mode changes only with the key
            c.set_sercfg_word(v)
            if v >> 13 == 5:
                act["mode_wr"] = 2 if v & 0x100 else (v >> 7) & 1
        elif reg == 0x2C:
            c.serdiv = v
        elif reg == 0x34:                                        # RXCFG
            c.rx_pin, c.rx_raw, c.rx_both = v & 31, bool(v & 32), bool(v & 64)
            act["arm"] = bool(v & 128)
        elif reg == 0x35:
            c.rxgap = v
        else:
            raise NotImplementedError("write to register 0x%02X" % reg)
        if act and s.eng is None:
            raise RuntimeError("register 0x%02X written while engine A is stopped" % reg)
        s.run(1, **act)

    def read(self, eng, reg):
        s = SIM
        s.access()
        e = s.eng
        if eng != 0:
            raise NotImplementedError("engine %d read" % eng)
        if reg == 0x37:                                          # RXDATA
            if e is None:
                s.run(1)
                return 0
            s.run(1, bpop=True)
            return e.bpopped or 0
        s.run(1)
        if reg == 0x2A:
            return 0x0022                                        # the Mojo's ser build, two engines
        if e is None:
            return {0x2B: s.cfg.sercfg_word(), 0x28: 0, 0x33: 0, 0x36: 0}[reg]
        if reg == 0x28:                                          # STATUS
            return (min(7, len(e.txf)) | 1 << 8 | (e.pc & 31) << 9 | int(e.ser_busy) << 14
                    | int(e.ser_under) << 15)
        if reg == 0x2B:
            return s.cfg.sercfg_word() | e.mode << 7
        if reg == 0x33:
            return min(127, len(e.txf)) | int(e.ser_busy) << 8 | int(e.ser_under) << 9
        if reg == 0x36:
            return e.rxstat
        raise NotImplementedError("read of register 0x%02X" % reg)

    def load_program(self, eng, words):
        assert SIM.eng is None, "load_program while the engine runs"
        SIM.access()
        SIM.prog = (list(words) + [0] * 32)[:32]
        SIM.run(1)

    def chip_id(self):
        return self.read(0, 0x2A)

    def stop(self, eng):
        self.write(eng, 0x20, 0)

    def start(self, eng):
        self.write(eng, 0x20, 1)


def main():
    script = sys.argv[1]
    g = {"__name__": "__main__"}
    for a in sys.argv[2:]:
        k, v = a.split("=", 1)
        g[k] = int(v.replace("_", ""), 0)
    sys.path.insert(0, os.path.join(ROOT, "pico"))
    machine = types.ModuleType("machine")                        # enough of it for chip_host to import
    machine.Pin = machine.SPI = lambda *a, **k: None
    sys.modules["machine"] = machine
    sys.modules["time"] = FakeTime()
    import chip_host                                             # the real register names and wrap_reg
    chip_host.Chip = Chip
    src = open(script, encoding="utf-8").read()
    exec(compile(src, script, "exec"), g)
    print("(model: %.1f ms of chip time)" % (SIM.t * 1000 / CHIP_HZ))


if __name__ == "__main__":
    main()
