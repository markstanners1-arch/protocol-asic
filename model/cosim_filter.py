"""Glitch filter: Verilog (src/glitch_filter.v) vs model (model/glitch_filter.py), every clock,
on random pulse trains; plus checks of the spec's promise (short pulses never pass, long levels always do).
    python model/cosim_filter.py [tests] [seed]"""
import os, random, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from glitch_filter import GlitchFilter, Prescaler
SUITE = r"D:\Tools\oss-cad-suite"
ENV = dict(os.environ, PATH=os.pathsep.join([SUITE + r"\bin", SUITE + r"\lib", os.environ["PATH"]]))
BUILD = os.path.join(ROOT, "test", "build")

def make_test(rnd):
    p, n = rnd.choice([0, 0, 1, 2, 3, rnd.randrange(16)]), rnd.randrange(16)
    hold = (n + 1) << p                      # nominal hold time in clocks
    nc = min(4000, max(200, hold * 12))
    lanes = []
    for _ in range(4):
        lvl, seq = rnd.randrange(2), []
        while len(seq) < nc:
            L = max(1, int(hold * rnd.choice([0.1, 0.3, 0.6, 0.9, 1.0, 1.1, 1.5, 3])) + rnd.randrange(-2, 3))
            seq += [lvl] * L; lvl ^= 1
        lanes.append(seq[:nc])
    stim = [sum(lanes[b][c] << b for b in range(4)) for c in range(nc)]
    return p, n, stim

def run_model(p, n, stim):
    pre, fs, out = Prescaler(), [GlitchFilter() for _ in range(4)], []
    for w in stim:
        tick = pre.tick(p)
        o = sum(fs[b].clock((w >> b) & 1, tick, n) << b for b in range(4))
        pre.clock()
        out.append(o)
    return out

def promise_ok(p, n, stim, out):
    """Pulses shorter than the hold time never reach the output; a level held 2x the hold time always does."""
    hold = (n + 1) << p
    for b in range(4):
        x = [(w >> b) & 1 for w in stim]; y = [(o >> b) & 1 for o in out]
        i = 0
        while i < len(x):
            j = i
            while j < len(x) and x[j] == x[i]: j += 1
            L = j - i
            if L >= 2 * hold + 3 and j < len(x) and y[j - 1] != x[i]:
                return f"lane {b}: level held {L} clocks (hold {hold}) did not get through"
            i = j
        # output may only ever change to a value the input held for >= hold - 2^p clocks just before
        for k in range(1, len(y)):
            if y[k] != y[k - 1]:
                back = 0
                while k - 1 - back >= 0 and x[k - 1 - back] == y[k]: back += 1
                if back < hold - (1 << p):
                    return f"lane {b}: output changed after only {back} clocks of input (hold {hold})"
    return None

def main():
    nt = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rnd = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    tests = [make_test(rnd) for _ in range(nt)]
    words = [nt]
    for p, n, stim in tests: words += [p, n, len(stim)] + stim
    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "filter_in.hex"), "w").write("\n".join(f"{w:x}" for w in words) + "\n")
    vvp = os.path.join(BUILD, "tb_filter.vvp")
    subprocess.run([SUITE + r"\bin\iverilog.exe", "-g2012", "-o", vvp, os.environ.get("FILTER_V", os.path.join(ROOT, "src", "glitch_filter.v")),
                    os.path.join(ROOT, "test", "tb_filter.v")], check=True, env=ENV)
    subprocess.run([SUITE + r"\bin\vvp.exe", "-n", vvp], check=True, env=ENV, cwd=BUILD, stdout=subprocess.DEVNULL)
    vout, cur = [], None
    for line in open(os.path.join(BUILD, "filter_out.txt")):
        line = line.strip()
        if line == "T": cur = []; vout.append(cur)
        elif line: cur.append(int(line, 16))
    mism = broken = 0; clocks = 0
    for i, (p, n, stim) in enumerate(tests):
        m = run_model(p, n, stim); clocks += len(stim)
        if m != vout[i]:
            mism += 1
            if mism == 1:
                k = next(k for k in range(len(m)) if m[k] != vout[i][k])
                print(f"FIRST DISAGREEMENT test {i} (p={p} n={n}) clock {k}: model {m[k]:x} verilog {vout[i][k]:x}")
        why = promise_ok(p, n, stim, m)
        if why:
            broken += 1
            if broken == 1: print(f"SPEC PROMISE BROKEN test {i} (p={p} n={n}): {why}")
    print(f"{nt} random pulse-train tests, {clocks:,} clocks x 4 inputs: model vs Verilog "
          f"{'identical' if not mism else f'{mism} differ'}; spec promise {'kept' if not broken else f'broken in {broken}'}"
          f" -> {'PASS' if not (mism or broken) else 'FAIL'}")
    return 1 if (mism or broken) else 0

if __name__ == "__main__":
    sys.exit(main())
