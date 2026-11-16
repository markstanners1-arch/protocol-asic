"""Writes test/build/chip_init.hex for tb_chip.v: both programs and both engines' setting registers,
packed exactly as docs/host_port.md says (so this also checks the register packing)."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
from asm import assemble

def regs(clkdiv=0, start=0, wb=0, wt=31, out_base=0, out_count=0, set_base=0, set_count=0, side_base=0,
         side_count=0, side_opt=0, out_right=0, in_right=0, side_dir=0, in_base=0, jmp_pin=0, fault_addr=0):
    return [clkdiv,
            start | wb << 5 | wt << 10,
            out_base | out_count << 5 | set_base << 10,
            set_count | side_base << 3 | side_count << 8 | side_opt << 10 | out_right << 11 | in_right << 12 | side_dir << 13,
            in_base | jmp_pin << 5 | fault_addr << 10]

ua = assemble(open(os.path.join(ROOT, "programs", "uart_tx.asm")).read())
mb = assemble(open(os.path.join(ROOT, "programs", "measure_baud.asm")).read())
words = (ua.words + [0] * 32)[:32] + (mb.words + [0] * 32)[:32]
words += regs(clkdiv=4, wb=ua.wrap_bottom, wt=ua.wrap_top, out_base=0, out_count=1, set_base=0, set_count=1,
              side_base=0, side_count=1, side_opt=1, out_right=1)                  # engine A: UART, 40 clocks/bit
words += regs(clkdiv=0, wb=mb.wrap_bottom, wt=mb.wrap_top, in_base=0, in_right=1)    # engine B: measure pin 0
p3 = assemble(open(os.path.join(ROOT, "programs", "push_789.asm")).read())
words += (p3.words + [0] * 32)[:32]                                                   # B's second program
for name in ("drive_low", "drive_high"):                                              # pin-conflict test
    words += (assemble(open(os.path.join(ROOT, "programs", name + ".asm")).read()).words + [0] * 32)[:32]
words += (assemble(open(os.path.join(ROOT, "programs", "measure_pulse.asm")).read()).words + [0] * 32)[:32]   # filter test
for name in ("i2c_master", "i2c_sniff"):                                              # I2C: A master, B watching
    words += (assemble(open(os.path.join(ROOT, "programs", name + ".asm")).read()).words + [0] * 32)[:32]
et = assemble(open(os.path.join(ROOT, "programs", "eth_tx.asm")).read())                                     # serialiser: init[266..297]
words += (et.words + [0] * 32)[:32] + [et.wrap_bottom << 5 | et.wrap_top << 10]                                 # its WRAP word: init[298]
os.makedirs(os.path.join(ROOT, "test", "build"), exist_ok=True)
open(os.path.join(ROOT, "test", "build", "chip_init.hex"), "w").write("\n".join(f"{w:04x}" for w in words) + "\n")
print(f"programs: A {len(ua.words)} words, B {len(mb.words)} words")
