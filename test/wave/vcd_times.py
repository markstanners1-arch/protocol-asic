"""First time (ns) each listed signal takes each listed value in a VCD. Usage: python vcd_times.py file.vcd"""
import sys

ids, vals, first, t = {}, {}, {}, 0
scale = 1.0
lines = open(sys.argv[1]).read().split("\n")
for i, line in enumerate(lines):
    s = line.strip()
    if s.startswith("$timescale"):
        unit = lines[i + 1].strip()
        scale = {"1ps": 1e-3, "1ns": 1.0}.get(unit, 1.0)
    if s.startswith("$var"):
        p = s.split()
        ids[p[3]] = p[4]
        continue
    if s.startswith("#"):
        t = int(s[1:]) * scale
        continue
    if not s or s[0] == "$":
        continue
    if s[0] in "01xz":
        v, k = s[0], s[1:]
    elif s[0] == "b":
        v, k = s[1:].split()
    else:
        continue
    n = ids.get(k)
    if n and vals.get(n) != v:
        vals[n] = v
        first.setdefault((n, v), t)
for k in [("cs_n", "0"), ("busy", "1"), ("phase", "1"), ("phase", "10"), ("phase", "11"), ("busy", "0"),
          ("td_plus", "1"), ("fifo_pop", "1")]:
    print(k, first.get(k))
print("last", t)
