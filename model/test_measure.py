"""The TIME instruction measuring a real-looking UART line: send 'U' at various bit times
(including a sloppy sender running a few % off), check the engine reports the bit time exactly."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm import assemble
from engine import Engine, Config

def uart_wave(byte, bitlen, lead=37):
    bits = [0] + [(byte >> k) & 1 for k in range(8)] + [1]
    return [1] * lead + [b for b in bits for _ in range(bitlen)] + [1] * 50

prog = assemble(open(os.path.join(ROOT, "programs", "measure_baud.asm")).read())
ok = True
for bitlen in (8, 87, 100, 217, 223, 1000):   # 223 = 217 running 2.8% slow
    eng = Engine(prog, Config.for_program(prog))
    for level in uart_wave(0x55, bitlen):
        eng.clock(level)
    got = eng.rx_get()
    good = got == bitlen
    ok &= good
    print(f"bit time {bitlen:5d} clocks -> engine measured {got}  {'ok' if good else 'WRONG'}")
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
