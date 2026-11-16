#pragma once
#include <stdint.h>
// One test run's tally.
struct Result { uint32_t checks = 0, errors = 0; uint16_t firstGot = 0, firstWant = 0; const char *firstWhat = ""; };
