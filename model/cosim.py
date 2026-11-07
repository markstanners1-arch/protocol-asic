"""Side-by-side test: the Verilog engine (src/engine.v) against the Python model (model/engine.py).

Generates random programs, random configurations, random pin activity and random host traffic,
runs them through both, and compares the complete engine state after every system clock.
The first disagreement is reported with the program listing and the clocks around it.

    python model/cosim.py [tests] [cycles] [seed]      (defaults 500 300 1)

Environment: USE_SRAM=1 uses IHP's SRAM block model for the memories; CRC=0 builds both engines without the CRC
unit (the ASIC build, 7 Nov 2026) and the model to match.
"""
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from engine import Engine, Config  # noqa: E402

SUITE = r"D:\Tools\oss-cad-suite"
BUILD = os.path.join(ROOT, "test", "build")
CRC_UNIT = os.environ.get("CRC", "1") != "0"
ENV = dict(os.environ, PATH=os.pathsep.join([os.path.join(SUITE, "bin"), os.path.join(SUITE, "lib"), os.environ["PATH"]]))
CFG_FIELDS = ["clkdiv", "start", "wrap_bottom", "wrap_top", "out_base", "out_count", "set_base", "set_count",
              "side_base", "side_count", "side_opt", "side_dir", "in_base", "jmp_pin", "out_right", "in_right", "fault_addr",
              "kind", "sercfg", "serdiv", "crcpoly", "crcinit"]     # kind 0 = the serialiser engine (0), 1 = a plain one
BOOLS = ("side_opt", "side_dir", "out_right", "in_right")
EVENTS = ["start", "abort", "done", "underrun", "crc_sent", "end_sent", "in_crc", "time_crc", "wait_ser", "pull_busy",
          "refill_blocked", "pull_not_ready", "under_not_ready"]
OPNAMES = ["jmp", "wait", "in", "out", "push/pull", "mov", "set", "time"]


def disasm(w):
    op, mid, a = (w >> 13) & 7, (w >> 8) & 31, w & 0xFF
    return f"{w:04x}  {OPNAMES[op]:9s} mid={mid:2d} a7:5={a >> 5} a4:0={a & 31:2d}"


def random_word(rnd):
    """Half fully random (exercises every encoding, reserved ones too), half biased towards useful code."""
    if rnd.random() < 0.5:
        return rnd.getrandbits(16)
    op = rnd.choice([0, 0, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7])
    mid = rnd.choice([0, 0, 0, rnd.getrandbits(5)])
    a = rnd.getrandbits(8)
    if op == 1 and rnd.random() < 0.7:          # WAIT: keep pins near the active ones, timeouts often
        a = (a & 0xE0) | rnd.randrange(8)
    if op == 1 and rnd.random() < 0.15:         # WAIT on the serialiser (index 24), either level
        a = (a & 0xC0) | 24
    if op == 5 and rnd.random() < 0.3:          # MOV ser, from x / y / null / osr: frames and aborts
        a = (3 << 5) | (rnd.choice([0, 0, 1, 2]) << 3) | rnd.choice([1, 1, 2, 2, 3, 7])
    if op == 6 and rnd.random() < 0.5:          # SET x/y to a small count, so MOV ser frames finish in time
        a = (rnd.choice([1, 2]) << 5) | rnd.choice([0, 1, 1, 2, 2, 3, 4, 5])
    if op == 7 and rnd.random() < 0.6:          # TIME: mostly start and capture, so measurements get exercised
        a = (rnd.choice([0, 0, 2, 3, 4, 5]) << 5) | (a & 31)
    return (op << 13) | (mid << 8) | a


def random_test(rnd, ncycles):
    prog = [random_word(rnd) for _ in range(32)]
    for i in range(1, 31):                       # around a MOV ser: often "set x, n" before (a short frame) and a
        w = prog[i]                              # "wait 0, ser" after, so frames start and finish inside the test
        if w >> 13 == 5 and (w >> 5) & 7 == 3:
            if w & 7 in (1, 2) and rnd.random() < 0.6:
                prog[i] = w & ~0x18
                prog[i - 1] = (6 << 13) | ((w & 7) << 5) | rnd.choice([1, 1, 2, 2, 3, 5, 8])
            if rnd.random() < 0.6:
                prog[i + 1] = (1 << 13) | (rnd.choice([0, 0, 0, 0x40]) | 24)
    wb, wt = sorted(rnd.randrange(32) for _ in range(2))
    cfg = dict(clkdiv=rnd.choice([0, 0, 0, 1, 2, 3]), start=rnd.randrange(32), wrap_bottom=wb, wrap_top=wt,
               out_base=rnd.randrange(32), out_count=rnd.randrange(17), set_base=rnd.randrange(32),
               set_count=rnd.randrange(6), side_base=rnd.randrange(32), side_count=rnd.randrange(3),
               side_opt=rnd.randrange(2), side_dir=rnd.randrange(2), in_base=rnd.randrange(32), jmp_pin=rnd.randrange(32),
               out_right=rnd.randrange(2), in_right=rnd.randrange(2), fault_addr=rnd.randrange(32),
               kind=rnd.choice([0, 0, 0, 1, 1]), serdiv=rnd.choice([0, 0, 0, 1, 2, 3, rnd.randrange(24)]),
               crcpoly=rnd.choice([0xEDB88320, 0xA001, 0x8C, rnd.getrandbits(32), rnd.getrandbits(16)]),
               crcinit=rnd.choice([0, 0xFFFFFFFF, 0xFFFF, rnd.getrandbits(32)]))
    sercfg = rnd.getrandbits(7) | (rnd.choice([0, 0, 1, 2, 4, rnd.randrange(8)]) << 10)
    if rnd.random() < 0.75:
        sercfg |= 1                                              # enabled three times in four
    cfg["sercfg"] = sercfg
    pins = rnd.getrandbits(32)
    stim = []
    flip = rnd.choice([0.02, 0.1, 0.3])
    push_rate = rnd.choice([0.05, 0.3, 0.3, 0.7])
    push_stop = rnd.choice([ncycles, ncycles, ncycles // 2, 300])   # a host that stops feeding: underruns in long runs
    for t in range(ncycles):
        if t >= push_stop:
            push_rate = 0
        for b in range(32):
            if rnd.random() < flip / 8:
                pins ^= 1 << b
        push = (1 << 16) | rnd.getrandbits(16) if rnd.random() < push_rate else 0
        pop = 1 if rnd.random() < 0.3 else 0
        stim.append((pins, push, pop))
    return prog, cfg, stim


def run_model(prog, cfg, stim, events=None):
    c = Config(**{k: (bool(v) if k in BOOLS else v) for k, v in cfg.items() if k not in ("kind", "sercfg")})
    c.ser = (cfg["kind"] == 0)
    c.crc_unit = CRC_UNIT
    c.set_sercfg_word(cfg["sercfg"])
    eng = Engine(prog, c)
    lines = []
    for pins, push, pop in stim:
        popped = eng.clock(pins, push=(push & 0xFFFF) if push >> 16 else None, pop=bool(pop))
        lines.append(f"{eng.pc} {eng.x:04x} {eng.y:04x} {eng.osr:04x} {eng.osr_count} {eng.isr:04x} "
                     f"{eng.isr_count} {eng.delay} {eng.sw:04x} {int(eng.sw_run)} {eng.pins_out:08x} "
                     f"{eng.out_dir:08x} {len(eng.txf)} {len(eng.rxf)} "
                     f"{'-' if popped is None else format(popped, '04x')} "
                     f"{int(eng.ser_busy)} {int(eng.ser_under)} {eng.crc:08x}")
    if events is not None:
        for k in EVENTS:
            events[k] += 1 if eng.events[k] else 0
    return lines


def run_verilog(tests):
    os.makedirs(BUILD, exist_ok=True)
    words = [len(tests)]
    for prog, cfg, stim in tests:
        words += [len(stim)] + prog + [cfg[k] for k in CFG_FIELDS]
        for s in stim:
            words += list(s)
    with open(os.path.join(BUILD, "cosim_in.hex"), "w") as f:
        f.write("\n".join(f"{w:08x}" for w in words) + "\n")
    vvp = os.path.join(BUILD, "tb_cosim.vvp")
    srcs = [os.environ.get("ENGINE_V", os.path.join(ROOT, "src", "engine.v")),
            os.environ.get("SER_V", os.path.join(ROOT, "src", "serialiser.v")),
            os.environ.get("CRC_V", os.path.join(ROOT, "src", "crc32.v")),
            os.path.join(ROOT, "src", "prog_mem.v"), os.path.join(ROOT, "src", "fifo_mem.v"),
            os.path.join(ROOT, "test", "tb_cosim.v")]
    flags = [] if CRC_UNIT else ["-Ptb_cosim.CRC=0"]
    if os.environ.get("USE_SRAM"):          # the real IHP SRAM block, with IHP's own simulation model
        flags += ["-DUSE_SRAM", "-DFUNCTIONAL"]
        srcs += [os.path.join(ROOT, "pdk", "RM_IHPSG13_1P_64x16_c2.v"),
                 os.path.join(ROOT, "pdk", "RM_IHPSG13_1P_core_behavioral.v")]
    subprocess.run([os.path.join(SUITE, "bin", "iverilog.exe"), "-g2012", *flags, "-o", vvp, *srcs],
                   check=True, env=ENV)
    subprocess.run([os.path.join(SUITE, "bin", "vvp.exe"), "-n", vvp], check=True, cwd=BUILD, env=ENV,
                   stdout=subprocess.DEVNULL)
    out, cur = [], None
    for line in open(os.path.join(BUILD, "cosim_out.txt")):
        line = line.strip()
        if line.startswith("T "):
            cur = []
            out.append(cur)
        elif line:
            cur.append(line)
    return out


HEAD = "pc x    y    osr  oc isr  ic dl sw   r pins_out out_dir  tx rx pop  busy under crc"


def main():
    ntests = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    ncycles = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    rnd = random.Random(seed)
    tests = [random_test(rnd, ncycles) for _ in range(ntests)]
    t0 = time.time()
    vlines = run_verilog(tests)
    t1 = time.time()
    fails = 0
    events = {k: 0 for k in EVENTS}             # tests in which the model saw each serialiser / CRC event
    for i, (prog, cfg, stim) in enumerate(tests):
        mlines = run_model(prog, cfg, stim, events)
        if i >= len(vlines):
            print(f"test {i}: no Verilog output"); fails += 1; break
        if len(vlines[i]) != len(mlines):
            print(f"test {i}: Verilog gave {len(vlines[i])} clocks, model {len(mlines)}"); fails += 1; continue
        for cyc, (m, v) in enumerate(zip(mlines, vlines[i])):
            if m != v:
                fails += 1
                if fails == 1:
                    print(f"FIRST DISAGREEMENT: test {i}, clock {cyc}")
                    print("config:", cfg)
                    print("         " + HEAD)
                    for k in range(max(0, cyc - 4), cyc + 1):
                        print(f"  model  {mlines[k]}")
                        print(f"  verilog{' ' if mlines[k] == vlines[i][k] else '*'}{vlines[i][k]}")
                    pc_before = int(mlines[cyc - 1].split()[0]) if cyc else cfg["start"]
                    print(f"instruction at pc {pc_before}: {disasm(prog[pc_before])}")
                    print("pins / push / pop this clock:", [hex(v) for v in stim[cyc]])
                break
    total = ntests * ncycles
    print("tests reaching: " + ", ".join(f"{k} {v}" for k, v in events.items()))
    print(f"{ntests} random programs x {ncycles} clocks = {total:,} clocks compared "
          f"(Verilog {t1 - t0:.0f} s, model {time.time() - t1:.0f} s): "
          + ("PASS, every clock identical" if fails == 0 else f"FAIL in {fails} tests")
          + ("  [IHP SRAM]" if os.environ.get("USE_SRAM") else "  [flip-flop memory]")
          + ("" if CRC_UNIT else "  [no CRC unit]"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
