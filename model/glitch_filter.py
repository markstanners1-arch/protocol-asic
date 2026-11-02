"""Clock-by-clock model of the input glitch filter (docs/input_filter.md)."""


class Prescaler:
    def __init__(self):
        self.pre = 0

    def tick(self, p):
        """Is this clock a filter tick for prescale p? (decided before the counter moves on)"""
        mask = (1 << p) - 1
        return (self.pre & mask) == mask

    def clock(self):
        self.pre = (self.pre + 1) & 0x7FFF


class GlitchFilter:
    def __init__(self):
        self.out = 0
        self.cnt = 0

    def clock(self, inp, tick, n):
        """One chip clock. inp: the synchronised input (0/1). Returns the output after this clock."""
        if inp == self.out:
            self.cnt = 0
        elif tick:
            if self.cnt == n:
                self.out, self.cnt = inp, 0
            else:
                self.cnt += 1
        assert 0 <= self.cnt <= 15
        return self.out
