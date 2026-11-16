# Input glitch filter, v0.1

Every chip input (engine pins 0-7 and 15-19) can ignore pulses shorter than a set time, from electrical spikes (tens
of ns) to mechanical switch bounce (milliseconds), with one design. One setting, register 0x29 (FILTER), applies to
every input. Engine 0's receiver bypasses the filter (`docs/isa.md`, "Receiver and full duplex").

## Settings

| Name | Bits | Meaning |
|---|---|---|
| `P` (prescale) | 0-15 | the filter counts **filter ticks**, one every 2^P chip clocks |
| `N` (length) | 0-15 | a new level must hold for N+1 consecutive filter ticks to get through |

Rough hold time needed: (N + 1) x 2^P clocks. At 50 MHz: N=0,P=0 is 20 ns (effectively off);
N=15,P=4 is about 5 us; N=15,P=14 is about 5 ms.

## Exact rule (per input, every chip clock)

The input arrives already synchronised (2 flip-flops). The filter keeps the output level `out`
and a 4-bit count `cnt`. A shared free-running 15-bit prescaler `pre` counts every clock;
a **filter tick** happens on a clock where the low P bits of `pre` are all ones (every clock when P = 0).

```
if in == out:            cnt = 0                       (no change pending: start again)
else if tick:
    if cnt == N:         out = in, cnt = 0             (held long enough: let it through)
    else:                cnt = cnt + 1
```

Reset: `out = 0`, `cnt = 0`, `pre = 0`. A pulse that goes away before getting through resets the count,
so any pulse shorter than about N+1 filter ticks never appears on the output.

The model (`model/glitch_filter.py`) and the Verilog (`src/glitch_filter.v`) follow this exactly and are
compared on every clock by `model/cosim_filter.py`.
