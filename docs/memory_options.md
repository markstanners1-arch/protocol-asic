# Program memory: flip-flops or SRAM? (2 Nov 2026)

Jane Street: "For instruction memory, SRAM can be more area-efficient than flip-flops.
Tiny Tapeout has examples of SRAM running on this process node you can reference."

## What exists

IHP's open process kit (`IHP-Open-PDK`, `ihp-sg13g2/libs.ref/sg13g2_sram`) has single- and dual-port
SRAM blocks from 64 x 16 up to 8192 x 32. Tiny Tapeout examples: `urish/ttihp-sram-test` (1024 x 8, the
earlier IHP process). Several other entrants to this competition use the 512 x 16 block for programs.

The one that matches us: **`RM_IHPSG13_1P_64x16_c2`**: 64 words x 16 bits, single port.
The Verilog model, LEF and the IHP cell library are copied into `pdk/`.

## Real areas (IHP sg13g2 standard cells, Yosys synthesis, typical corner, before place and route)

| Item | Area |
|---|---|
| One engine as it stands (32 x 16 program memory in flip-flops) | **99,091 um2** |
| The same engine with the program memory taken out | 64,933 um2 |
| so the flip-flop program memory costs | **~34,000 um2 per engine** |
| SRAM block 64 x 16 (236.8 x 64.36 um) | **15,240 um2** |
| One Tiny Tapeout tile (about 202 x 155 um) | ~31,300 um2 |
| Our 6 x 4 allocation | ~750,000 um2 (realistically 60-70 % usable after routing: ~450-525K) |

Full chip estimate with flip-flop memory: 2 engines (~198K) + host port + input filters, about **230K um2**,
roughly a third of the allocation. It fits either way.

## What SRAM would change

- **Saving**: about 19K um2 per engine (34K of flip-flops -> one 15K block each), about 38K for the chip: ~5 %.
  One block can't serve both engines: it reads one word per clock and each engine needs one every tick.
- **Timing**: the block reads on the clock edge (address in, word out after the edge). Our flip-flop memory
  answers at once. The engine would feed the block the *next* program counter so the instruction arrives
  just in time; the host's program writes would share the same port. The model comparison would re-prove it.
- **Layout**: the block is 236.8 um wide, wider than one tile (~202 um), so it spans two tile columns.
- **Check needed**: that the 64 x 16 block is accepted on the CMOS5L shuttle (it was generated in July 2026).

## Decision (2 Nov 2026, Mark): flip-flops for now

Revisit at the layout stage (weeks 6-7). The reasoning, as leaned:

Keep flip-flops for now: simpler, already proven on 4M random clocks, and the chip fits with room to spare.
Switch to SRAM if the layout stage (roadmap weeks 6-7) shows area or routing getting tight, or if a
bigger program memory (e.g. 64 words per engine) becomes worth having. The 64 x 16 block would give each
engine 64 words for less area than today's 32.
