// Segment 1 bench test: ESP32 as the host, talking to the chip's real SPI host port on the Go Board.
// Wiring (Go Board PMOD -> ESP32 WROOM-32 dev board):
//   PMOD 1 CS   -> GPIO 5      PMOD 2 MOSI -> GPIO 23     PMOD 3 MISO -> GPIO 19
//   PMOD 4 SCK  -> GPIO 18     PMOD 5 GND  -> GND         (PMOD 6, 3.3 V: leave unconnected)
// Go Board must be running fpga/go_board/build/spi_test.bin.
// Open the Serial Monitor at 115200. It runs the test at rising SPI speeds and prints a table.
// Send 'r' to run again.

#include <SPI.h>
#include "result.h"   // kept in its own file so the Arduino IDE sees it before its auto-made prototypes

const int PIN_CS = 5, PIN_SCK = 18, PIN_MISO = 19, PIN_MOSI = 23;
uint32_t spiHz = 1000000;

void csLow()  { digitalWrite(PIN_CS, LOW);  delayMicroseconds(1); }
void csHigh() { delayMicroseconds(1); digitalWrite(PIN_CS, HIGH); delayMicroseconds(2); }

void begin_(uint8_t cmd) { SPI.beginTransaction(SPISettings(spiHz, MSBFIRST, SPI_MODE0)); csLow(); SPI.transfer(cmd); }
void end_()              { csHigh(); SPI.endTransaction(); }

// command byte: [7] read, [6] engine, [5:0] register
uint8_t cmd(bool rd, int eng, int reg) { return (rd ? 0x80 : 0) | (eng ? 0x40 : 0) | (reg & 0x3F); }

void writeReg(int eng, int reg, uint16_t v) { begin_(cmd(false, eng, reg)); SPI.transfer16(v); end_(); }
uint16_t readReg(int eng, int reg)          { begin_(cmd(true, eng, reg)); uint16_t v = SPI.transfer16(0); end_(); return v; }


void check(Result &r, const char *what, uint16_t got, uint16_t want) {
  r.checks++;
  if (got != want) {
    if (r.errors == 0) { r.firstGot = got; r.firstWant = want; r.firstWhat = what; }
    r.errors++;
  }
}

Result runAt(uint32_t hz, int rounds) {
  spiHz = hz;
  Result r;
  uint16_t shadow[16] = {0};
  check(r, "ID", readReg(0, 0x29), 0xA5C3);
  // start from known values
  for (int i = 0; i < 16; i++) { writeReg(i >> 3, i & 7, 0); }

  for (int n = 0; n < rounds; n++) {
    // single write then read back
    int eng = random(2), reg = random(8);
    uint16_t v = random(0x10000);
    writeReg(eng, reg, v); shadow[eng * 8 + reg] = v;
    check(r, "write/read", readReg(eng, reg), v);

    // occasionally: a burst of 8, read back as a burst
    if (n % 50 == 0) {
      int e = random(2);
      begin_(cmd(false, e, 0));
      for (int i = 0; i < 8; i++) { uint16_t w = random(0x10000); SPI.transfer16(w); shadow[e * 8 + i] = w; }
      end_();
      begin_(cmd(true, e, 0));
      for (int i = 0; i < 8; i++) check(r, "burst", SPI.transfer16(0), shadow[e * 8 + i]);
      end_();
    }
    // occasionally: fill the FIFO, check its level, empty it in one burst
    if (n % 50 == 25) {
      uint16_t f[4];
      begin_(cmd(false, 0, 0x26));
      for (int i = 0; i < 4; i++) { f[i] = random(0x10000); SPI.transfer16(f[i]); }
      end_();
      check(r, "FIFO level 4", readReg(0, 0x28), 4);
      begin_(cmd(true, 0, 0x27));
      for (int i = 0; i < 4; i++) check(r, "FIFO data", SPI.transfer16(0), f[i]);
      end_();
      check(r, "FIFO level 0", readReg(0, 0x28), 0);
    }
  }
  return r;
}

void runAll() {
  const uint32_t speeds[] = {250000, 500000, 1000000, 2000000, 3000000, 4000000, 5000000, 6000000, 8000000, 10000000};
  Serial.println();
  Serial.println("Go Board SPI host port test  (design limit 25 MHz / 8 = 3.1 MHz)");
  Serial.println("  SPI speed    checks   errors   first error");
  for (uint32_t hz : speeds) {
    Result r = runAt(hz, 1000);
    Serial.printf("  %5.2f MHz  %7lu  %7lu", hz / 1e6, (unsigned long)r.checks, (unsigned long)r.errors);
    if (r.errors) Serial.printf("   %s: got 0x%04X, wanted 0x%04X", r.firstWhat, r.firstGot, r.firstWant);
    Serial.println(r.errors ? "" : "   ok");
  }
  Serial.printf("Words written (Go Board counter): %u\n", readRegSafe());
  Serial.println("Send 'r' to run again.");
}

uint16_t readRegSafe() { spiHz = 500000; return readReg(0, 0x2A); }

void setup() {
  Serial.begin(115200);
  delay(1500);
  pinMode(PIN_CS, OUTPUT);
  digitalWrite(PIN_CS, HIGH);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, -1);
  randomSeed(esp_random());
  runAll();
}

void loop() {
  if (Serial.available() && Serial.read() == 'r') runAll();
}
