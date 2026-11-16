"""Week-2 check: the UART program running on the engine model must match uart_tx.v bit for bit.

For several baud settings it:
  1. sends the same bytes through the Verilog uart_tx (Icarus) and through the model running programs/uart_tx.asm
  2. decodes both serial lines like a receiver would, and checks every byte arrived
  3. compares each frame (start bit to end of stop bit) sample by sample, every system clock
  4. reports the spacing between frames (back-to-back throughput) for both

Run from the project folder:  python model/compare_uart.py
"""
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble          # noqa: E402
from engine import Engine, Config  # noqa: E402

SUITE = r"D:\Tools\oss-cad-suite"
ENV = dict(os.environ, PATH=os.pathsep.join([os.path.join(SUITE, "bin"), os.path.join(SUITE, "lib"), os.environ["PATH"]]))
BUILD = os.path.join(ROOT, "test", "build")


def verilog_trace(data, bitlen):
    os.makedirs(BUILD, exist_ok=True)
    with open(os.path.join(BUILD, "bytes.hex"), "w") as f:
        f.write("\n".join(f"{b:02x}" for b in data) + "\n")
    vvp = os.path.join(BUILD, "tb_uart_dump.vvp")
    subprocess.run([os.path.join(SUITE, "bin", "iverilog.exe"), "-g2012", "-o", vvp, os.path.join(ROOT, "src", "uart_tx.v"),
                    os.path.join(ROOT, "test", "tb_uart_dump.v")], check=True, env=ENV)
    subprocess.run([os.path.join(SUITE, "bin", "vvp.exe"), "-n", vvp, f"+divisor={bitlen - 1}", f"+n={len(data)}"], check=True, env=ENV,
                   cwd=BUILD, stdout=subprocess.DEVNULL)
    with open(os.path.join(BUILD, "tx_trace.txt")) as f:
        return [0 if ch == "0" else 1 for ch in f.read().strip()]   # x before reset = idle high


def model_trace(data, clkdiv):
    prog = assemble(open(os.path.join(ROOT, "programs", "uart_tx.asm")).read())
    eng = Engine(prog, Config.for_program(prog, clkdiv=clkdiv, out_base=0, out_count=1,
                                          set_base=0, set_count=1, side_base=0, out_right=True))
    queue = list(data)
    trace = []
    idle = 0
    while idle < 40 * (clkdiv + 1):
        while queue and eng.tx_put(queue[0]):
            queue.pop(0)
        eng.clock(0)
        driven = eng.out_dir & 1
        trace.append(eng.out_val & 1 if driven else 1)      # undriven line: pull-up -> 1
        finished = not queue and not eng.txf and eng.stalled
        idle = idle + 1 if finished else 0
    return trace


def decode(trace, bitlen):
    """Receiver: falling edge, sample each bit in its middle. Returns (bytes, start indices, errors)."""
    out, starts, errs = [], [], []
    i = 1
    while i < len(trace):
        if trace[i - 1] == 1 and trace[i] == 0:
            mid = i + bitlen // 2
            if mid + 9 * bitlen >= len(trace):
                errs.append(f"frame at {i} cut short"); break
            if trace[mid] != 0:
                errs.append(f"glitch at {i}"); i += 1; continue
            b = sum(trace[mid + (k + 1) * bitlen] << k for k in range(8))
            if trace[mid + 9 * bitlen] != 1:
                errs.append(f"bad stop bit in frame at {i}")
            out.append(b); starts.append(i)
            i = mid + 9 * bitlen
        else:
            i += 1
    return out, starts, errs


def main():
    rnd = random.Random(2026_11_02)
    data = [0x55, 0x00, 0xFF, 0xA5, 0x5A, 0x01, 0x80] + [rnd.randrange(256) for _ in range(57)]
    all_ok = True
    for clkdiv in (0, 1, 3, 10):
        bitlen = 8 * (clkdiv + 1)
        vt = verilog_trace(data, bitlen)
        mt = model_trace(data, clkdiv)
        vb, vs, ve = decode(vt, bitlen)
        mb, ms, me = decode(mt, bitlen)
        ok_bytes = vb == data and mb == data and not ve and not me
        mism = 0
        for a, b in zip(vs, ms):
            if vt[a:a + 10 * bitlen] != mt[b:b + 10 * bitlen]:
                mism += 1
        vgap = sorted(set(b - a for a, b in zip(vs, vs[1:])))
        mgap = sorted(set(b - a for a, b in zip(ms, ms[1:])))
        ok = ok_bytes and mism == 0 and len(vs) == len(ms) == len(data)
        all_ok &= ok
        print(f"clkdiv {clkdiv:2d} ({bitlen:3d} clocks/bit): "
              f"bytes Verilog {len(vb)}/{len(data)} model {len(mb)}/{len(data)}, "
              f"frames differing: {mism}, frame spacing Verilog {vgap} model {mgap} (ideal {10 * bitlen})"
              + ("" if ok else f"  <-- FAIL {ve[:2]} {me[:2]}"))
    print("PASS: model matches uart_tx.v on every frame" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
