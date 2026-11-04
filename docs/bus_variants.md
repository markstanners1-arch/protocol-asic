# Bus wiring variants: what a third and fourth wire buy, and what the chip has to do

From the bench talk of 4 Nov 2026 (morning), written up that afternoon. The thread started with "how far can I2C
go?", went through fire-alarm loops, and ended with "is a three- or four-wire bus worth doing on our chip?". The
answer is yes, as a program file, after the identification demos and DALI.

## 1. Why I2C stops at a few metres

Volt drop is not the limit; almost no current flows. The limit is capacitance. The spec caps the bus at 400 pF
total, and every centimetre of wire, every device pin and every connector adds to it. Nobody ever drives an I2C line
high: a device pulls low hard through a transistor, then releases, and the pull-up resistor has to charge the whole
bus back to 3.3 V. That is an RC ramp. 5.1 k into 400 pF is a 2 us time constant and the line needs about two of
those for a solid high. At 100 kHz the high half-cycle is 5 us, so it just works; at 400 kHz it is 1.25 us and the
line never gets there. Hence the rule: the longer the bus, the stiffer the pull-ups, down to the devices' sink limit
(about 3 mA, so roughly 1 k at 3.3 V as the floor).

| Wiring | Capacitance per metre | Comfortable length |
|---|---|---|
| Breadboard and jumper leads | 50 to 100 pF | 1 to 2 m, less with lots of chips |
| Ribbon or unscreened pair | 50 pF | a few metres |
| Screened or Cat5 | 50 to 70 pF | 5 m or so at 100 kHz |

Each device adds about 10 pF. Other things that bite on a long run: noise and crosstalk (the lines float high
through a resistor; our glitch filter helps), ground offset between two boards on separate supplies, and no
termination (I2C is not a transmission-line scheme; the ramp is the problem, not reflections). The industry's
answers are bus extenders: the PCA9615 (differential pairs over Cat5, 30 m or more) and the P82B715 (more drive
current, pull-ups down to a few hundred ohms, 50 m of plain cable). Both are transparent to the master, so our chip
would drive either with no program change.

A fire loop is the same physics scaled up a thousand times: a kilometre of 1.5 mm2 cable is about 100 nF, so the
panels run at a few kbit/s with fat slow pulses (400 pF at 100 kHz and 100 nF at a few kHz are about the same
ratio). The screen is earthed at one end only so it drains interference without becoming a second return path;
earthed at both ends it is a loop antenna with current in it. A case from the trade: sheath bonded to the steel frame at
every box, the whole factory became the return path, the panel showed every fault in the book and the earth-fault
monitor saw a few hundred nanofarads instead of an open circuit. The 400 pF figure is that factory floor written
down small.

## 2. Three meanings of "three wire", all program changes

The engine does not care which pin it reads and which it drives, so none of these touches the Verilog.

1. **Split SDA into data-out and data-in.** This is the one that solves distance. If the master sends on one wire
   and listens on another, neither needs to be open drain: both can be driven push-pull, hard high and hard low, so
   the edges are sharp whatever the capacitance. Add a push-pull SCL and the I2C protocol, with its addressing and
   ACKs, runs over tens of metres. Isolator chips (ISO1540) do exactly this across their barrier and turn it back
   into normal I2C on the far side. For our master: `in pins` reads a different pin from the one the output drives.
   Clock stretching and multi-master arbitration go, since both rely on the shared wire; a point-to-point link does
   not miss them.
2. **Keep I2C as is and add an alert line.** That is SMBus, I2C's cousin in every PC. The third wire is a shared
   open-drain interrupt: a slave pulls it low when it has something to say and the master asks round who it was. It
   fixes I2C's biggest practical weakness, that a slave cannot speak until spoken to. For us an engine sits in a
   `wait 0 pin` on the alert line and pushes to its FIFO, which raises the host IRQ. About sixteen words.
3. **Three-wire SPI.** Half-duplex SPI with one shared data line instead of MOSI and MISO (small displays, some
   sensors). The master drives the line for the command, then flips it to input for the reply. The I2C program
   already does that direction flip mid-transfer, so the SPI master gains one `set pindirs`.

A screen as the third conductor is not a signal: it is the fire-loop rule again (earth one end only). It buys noise
immunity, not distance. The wall keeps the barbarians out and has nothing to say about the traffic inside; the
screen is EMC, the conductors are the protocol.

## 3. Four wires

- **Split both lines**: data out, data in, clock out, clock in. The clock return gives back the one thing the
  three-wire version lost: a slow device can hold the clock line it owns and the master sees it. That is the full
  isolator architecture (the ISO1540 is exactly four signals across its barrier). Our master gains one `wait` on
  the clock-return pin, the stretch check it already does, on a different pin.
- **Differential pairs**: SDA as a pair, SCL as a pair, the PCA9615 way over Cat5, or RS-485 full duplex for
  serial. Push-pull, two volts of swing between the wires, noise hits both equally and cancels. Hundreds of metres.
  The chip sees none of it: a transceiver turns each pair back into one logic pin at each end, so the plain I2C
  program runs unchanged.
- **Two data plus power**: signal pair, supply, ground. USB's layout and the fire loop's intent. For I2C it is the
  normal four-pin sensor header; over cable you want the split or differential data and a higher supply voltage
  with a regulator at the far end.
- **SPI as it stands**: clock, data out, data in, select. Goes further than I2C out of the box because everything
  is push-pull already. Its weakness is the select line, one per device, so it does not scale to a bus of twenty.

## 4. The ladder

Signal conductors plus one return:

| Wires | Bus | What the extra wire buys |
|---|---|---|
| 1 + return | 1-Wire, DALI, the fire loop | the device steals power and timing from the one line; slow, but anything hangs on it |
| 2 + return | I2C | a separate clock, so the data line carries no timing and devices need no clock accuracy |
| 3 + return | split-data I2C, SMBus with alert, three-wire SPI | push-pull edges, so distance; or a slave that can interrupt |
| 4 + return | SPI, fully split I2C, differential I2C | both directions independent, or two balanced pairs for noise rejection |

Each rung down removes one piece of cleverness the protocol had to do in software and gives it to copper. The
one-wire protocols pack clock and data into pulse timing, so the engine does the most work there, and that is where
a programmable engine looks best against a fixed peripheral. By four wires the electronics does the work and the
program is almost trivial. So the end of the table to show the judges is the single-wire end: DALI and 1-Wire more
than SPI. Every extra wire buys one of speed, distance or robustness; the chip only ever sees logic levels on pins,
and the medium (pull-up, differential driver, fibre, LED) is the front end's problem. That separation is the whole
reason a general engine beats a dedicated I2C block, and the submission should say so in those terms.

## 5. Split I2C on our chip: constraints and plan

Within constraints on all three counts:

- **Pins.** 20 pins; the I2C master uses two. The split lines need none of the scarce two-way pins: data out and
  clock out on the six output-only pins (8-13), data in and clock return on the five input-only pins (15-19). Those
  eleven pins are idle in every I2C demo today.
- **Program words.** The 19-word `programs/i2c_master.asm` changes by about two words: `out pindirs` becomes `out
  pins` on the data-out pin, `in pins` reads the data-in pin through the separate input base (INCFG `in_base`), and
  the clock-stretch `wait` moves to the clock-return pin. Start and stop routines unchanged; still well under 32.
- **Design.** No Verilog change, so no re-layout and no new proof run. It is a program file,
  `programs/i2c_master_split.asm` alongside the standard one, plus a model test with a planted bug.

The far end needs a thought, because no EEPROM speaks split I2C. The clean answer is the **P82B96** (about two
pounds): plain SDA/SCL on the slave side, separate Tx and Rx lines per signal on the other, made for long cable and
optocouplers. Demo: our engine, four wires and two metres of ribbon, a P82B96, the AT24C256, and the same read that
fails on plain I2C over that cable succeeds. The chip's role in the story is "same protocol, different wiring, two
words changed".

**Worth doing?** Yes, but not first: half a day, and a distinctive angle few entries will have because it comes from
the trade rather than the PIO playbook. It does not beat the identification demos or DALI for showing what the
engine can do that a fixed peripheral cannot. Order: keypad (done 4 Nov), the identify-the-board set as parts
arrive, DALI, then this. **Shopping:** one P82B96 (with the RFID fob module and 433 MHz receiver).
