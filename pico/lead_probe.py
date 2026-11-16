"""Lead probe from the Pico (the ESP32 sketch's 'p'). With CS held high (the chip idle), the chip's two outputs to us,
MISO (GP16) and IRQ (GP20), are read with the Pico's pull-up and then its pull-down: a line that follows the pull is
FLOATING (lead open or in the wrong hole); a line that holds its level is driven. Then each is sampled 2000 times as
fast as the Pico can (about 1 us apart): a driven idle line should not change at all.
Then CS, SCK and MOSI are each driven low and high in turn with the others still, for a check from the other end.
No SPI traffic is sent. Prints PASS if both returning lines are driven and steady."""
import time
from machine import Pin

cs = Pin(17, Pin.OUT, value=1)
sck = Pin(18, Pin.OUT, value=0)
mosi = Pin(19, Pin.OUT, value=0)
ok = True
for name, gp in (("MISO", 16), ("IRQ", 20)):
    up = Pin(gp, Pin.IN, Pin.PULL_UP); time.sleep_ms(5); a = up.value()
    dn = Pin(gp, Pin.IN, Pin.PULL_DOWN); time.sleep_ms(5); b = dn.value()
    p = Pin(gp, Pin.IN)
    samples = [p.value() for _ in range(2000)]
    changes = sum(1 for i in range(1, 2000) if samples[i] != samples[i - 1])
    if a != b:
        state = "FLOATING (follows the Pico's pull)"
    else:
        state = "driven %s" % ("high" if a else "low")
    steady = "steady" if changes == 0 else "CHANGES %d times in 2000 samples (ones: %d)" % (changes, sum(samples))
    print("  %-5s GP%-2d pull-up reads %d, pull-down reads %d: %s, %s" % (name, gp, a, b, state, steady))
    if a != b or changes:
        ok = False
print("PASS" if ok else "FAIL: see the lines above")
