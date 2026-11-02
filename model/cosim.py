"""Side-by-side test: the Verilog engine (src/engine.v) against the Python model (model/engine.py).

Generates random programs, random configurations, random pin activity and random host traffic,
runs them through both, and compares the complete engine state after every system clock.
The first disagreement is reported with the program listing and the clocks around it.

    python model/cosim.py [tests] [cycles] [seed]      (defaults 500 300 1)
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
ENV = dict(os.environ, PATH=os.pathsep.join([os.path.join(SUITE, "bin"), os.path.join(SUITE, "lib"), os.environ["PATH"]]))
CFG_FIELDS = ["clkdiv", "start", "wrap_bottom", "wrap_top", "out_base", "out_count", "set_base", "set_count",
              "side_base", "side_count", "side_opt", "side_dir", "in_base", "jmp_pin", "out_right", "in_right", "fault_addr"]
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
    if op == 7 and rnd.random() < 0.6:          # TIME: mostly start and capture, so measurements get exercised
        a = (rnd.choice([0, 0, 2, 3, 4]) << 5) | (a & 31)
    return (op << 13) | (mid << 8) | a


def random_test(rnd, ncycles):
    prog = [random_word(rnd) for _ in range(32)]
    wb, wt = sorted(rnd.randrange(32) for _ in range(2))
    cfg = dict(clkdiv=rnd.choice([0, 0, 0, 1, 2, 3]), start=rnd.randrange(32), wrap_bottom=wb, wrap_top=wt,
               out_base=rnd.randrange(32), out_count=rnd.randrange(17), set_base=rnd.randrange(32),
               set_count=rnd.randrange(6), side_base=rnd.randrange(32), side_count=rnd.randrange(3),
               side_opt=rnd.randrange(2), side_dir=rnd.randrange(2), in_base=rnd.randrange(32), jmp_pin=rnd.randrange(32),
               out_right=rnd.randrange(2), in_right=rnd.randrange(2), fault_addr=rnd.randrange(32))
    pins = rnd.getrandbits(32)
    stim = []
    flip = rnd.choice([0.02, 0.1, 0.3])
    for _ in range(ncycles):
        for b in range(32):
            if rnd.random() < flip / 8:
                pins ^= 1 << b
        push = (1 << 16) | rnd.getrandbits(16) if rnd.random() < 0.3 else 0
        pop = 1 if rnd.random() < 0.3 else 0
        stim.append((pins, push, pop))
    return prog, cfg, stim


def run_model(prog, cfg, stim):
    c = Config(**{k: (bool(v) if k in ("side_opt", "side_dir", "out_right", "in_right") else v) for k, v in cfg.items()})
    eng = Engine(prog, c)
    lines = []
    for pins, push, pop in stim:
        popped = eng.clock(pins, push=(push & 0xFFFF) if push >> 16 else None, pop=bool(pop))
        lines.append(f"{eng.pc} {eng.x:04x} {eng.y:04x} {eng.osr:04x} {eng.osr_count} {eng.isr:04x} "
                     f"{eng.isr_count} {eng.delay} {eng.sw:04x} {int(eng.sw_run)} {eng.out_val:08x} "
                     f"{eng.out_dir:08x} {len(eng.txf)} {len(eng.rxf)} "
                     f"{'-' if popped is None else format(popped, '04x')}")
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
            os.path.join(ROOT, "src", "prog_mem.v"), os.path.join(ROOT, "test", "tb_cosim.v")]
    flags = []
    if os.environ.get("USE_SRAM"):          # the real IHP SRAM block, with IHP's own simulation model
        flags = ["-DUSE_SRAM", "-DFUNCTIONAL"]
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


HEAD = "pc x    y    osr  oc isr  ic dl sw   r out_val  out_dir  tx rx pop"


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
    for i, (prog, cfg, stim) in enumerate(tests):
        mlines = run_model(prog, cfg, stim)
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
    print(f"{ntests} random programs x {ncycles} clocks = {total:,} clocks compared "
          f"(Verilog {t1 - t0:.0f} s, model {time.time() - t1:.0f} s): "
          + ("PASS, every clock identical" if fails == 0 else f"FAIL in {fails} tests")
          + ("  [IHP SRAM]" if os.environ.get("USE_SRAM") else "  [flip-flop memory]"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
