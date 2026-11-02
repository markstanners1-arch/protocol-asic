// Whole-chip bench test: ESP32 as host for the chip (src/chip.v) running on the MachXO3L Starter Kit.
// The kit must be running fpga/machxo3/build/chip.bit (12 MHz chip clock -> SPI at most 1.5 MHz).
//
// Wiring (kit header J4 -> ESP32):
//   J4-3  CS    -> GPIO 5        J4-5  MOSI -> GPIO 23       J4-7  MISO -> GPIO 19
//   J4-9  SCK   -> GPIO 18       J4-11 GND  -> GND
//   J4-6  engine pin 0 (engine A's UART out)  -> GPIO 16 (Serial2 RX)
//   J4-4  IRQ   -> GPIO 4        (J4-1 and J4-2 are 3.3 V: leave them alone)
//
// What it does, at three baud rates:
//   1. loads engine B with programs/measure_baud.asm and starts it (it watches engine pin 0)
//   2. loads engine A with programs/uart_tx.asm, sets its clock divider for the baud rate, starts it
//   3. sends a line of text through engine A, a word at a time over SPI, never overfilling its FIFO
//   4. reads what actually came out of the chip's pin on Serial2, and compares
//   5. reads engine B's measurement of engine A's bit time back over SPI
// Results on the Serial Monitor at 115200. Send 'r' to run again.

#include <SPI.h>
#include "programs.h"

const int PIN_CS = 5, PIN_SCK = 18, PIN_MISO = 19, PIN_MOSI = 23, PIN_IRQ = 4, PIN_RX2 = 16;
const uint32_t SPI_HZ = 1000000;           // chip clock 12 MHz / 8 = 1.5 MHz limit
const float CHIP_HZ = 12e6;

// registers (docs/host_port.md)
const int R_CTRL = 0x20, R_CLKDIV = 0x21, R_WRAP = 0x22, R_OUTCFG = 0x23, R_MISC = 0x24, R_INCFG = 0x25,
          R_TX = 0x26, R_RX = 0x27, R_STATUS = 0x28;
const int ENG_A = 0, ENG_B = 1;

uint8_t cmd(bool rd, int eng, int reg) { return (rd ? 0x80 : 0) | (eng ? 0x40 : 0) | (reg & 0x3F); }
void begin_(uint8_t c) { SPI.beginTransaction(SPISettings(SPI_HZ, MSBFIRST, SPI_MODE0)); digitalWrite(PIN_CS, LOW); delayMicroseconds(2); SPI.transfer(c); }
void end_()            { delayMicroseconds(2); digitalWrite(PIN_CS, HIGH); SPI.endTransaction(); delayMicroseconds(5); }
void writeReg(int eng, int reg, uint16_t v) { begin_(cmd(false, eng, reg)); SPI.transfer16(v); end_(); }
uint16_t readReg(int eng, int reg)          { begin_(cmd(true, eng, reg)); uint16_t v = SPI.transfer16(0); end_(); return v; }

void loadProgram(int eng, const uint16_t *words, int n) {
  begin_(cmd(false, eng, 0x00));                       // one burst: 32 words, unused ones zero
  for (int i = 0; i < 32; i++) SPI.transfer16(i < n ? words[i] : 0);
  end_();
}
uint16_t wrapReg(int start, int wb, int wt) { return start | (wb << 5) | (wt << 10); }

int errors = 0;
void check(const char *what, long got, long want) {
  bool ok = (got == want);
  if (!ok) errors++;
  Serial.printf("  %-44s %8ld  %s\n", what, got, ok ? "ok" : "WRONG");
  if (!ok) Serial.printf("  %-44s %8ld\n", "   expected", want);
}

void runAt(uint32_t baud) {
  int clkdiv = (int)(CHIP_HZ / (8.0 * baud) + 0.5) - 1;         // engine UART: one bit = 8 ticks
  float actual = CHIP_HZ / (8.0 * (clkdiv + 1));
  Serial.printf("\n-- %lu baud: engine A clock divider %d -> %.0f baud (%.2f %% off)\n",
                (unsigned long)baud, clkdiv, actual, 100.0 * (actual - baud) / baud);

  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);        // stop both (held in reset)

  // engine B: measure the bit time on engine pin 0
  loadProgram(ENG_B, PROG_MEASURE_BAUD, PROG_MEASURE_BAUD_LEN);
  writeReg(ENG_B, R_CLKDIV, 0);
  writeReg(ENG_B, R_WRAP, wrapReg(0, PROG_MEASURE_BAUD_WRAP_BOTTOM, PROG_MEASURE_BAUD_WRAP_TOP));
  writeReg(ENG_B, R_OUTCFG, 0);
  writeReg(ENG_B, R_MISC, 1 << 12);                               // in_right
  writeReg(ENG_B, R_INCFG, 0);                                    // in_base 0
  writeReg(ENG_B, R_CTRL, 1);

  // engine A: UART transmitter on engine pin 0
  loadProgram(ENG_A, PROG_UART_TX, PROG_UART_TX_LEN);
  writeReg(ENG_A, R_CLKDIV, clkdiv);
  writeReg(ENG_A, R_WRAP, wrapReg(0, PROG_UART_TX_WRAP_BOTTOM, PROG_UART_TX_WRAP_TOP));
  writeReg(ENG_A, R_OUTCFG, 0 | (1 << 5) | (0 << 10));            // out_base 0, out_count 1, set_base 0
  writeReg(ENG_A, R_MISC, 1 | (0 << 3) | (1 << 8) | (1 << 10) | (1 << 11));   // set_count 1, side_base 0, side_count 1, side_opt, out_right
  writeReg(ENG_A, R_INCFG, 0);
  check("A clock divider read back", readReg(ENG_A, R_CLKDIV), clkdiv);
  writeReg(ENG_A, R_CTRL, 1);
  check("A running (STATUS bit 8)", (readReg(ENG_A, R_STATUS) >> 8) & 1, 1);

  Serial2.end();
  Serial2.begin(baud, SERIAL_8N1, PIN_RX2, -1);
  delay(20);
  while (Serial2.available()) Serial2.read();

  const char *msg = "UHello from the chip!";
  for (const char *p = msg; *p; p++) {
    uint32_t t0 = millis();
    while ((readReg(ENG_A, R_STATUS) & 7) >= 4 && millis() - t0 < 200) { }   // wait for FIFO room
    writeReg(ENG_A, R_TX, (uint8_t)*p);
  }
  delay(20 + strlen(msg) * 12000 / baud);
  char got[64] = {0}; int n = 0;
  while (Serial2.available() && n < 63) got[n++] = Serial2.read();
  bool same = (strcmp(got, msg) == 0);
  if (!same) errors++;
  Serial.printf("  %-44s \"%s\"  %s\n", "ESP32 received from the chip's pin", got, same ? "ok" : "WRONG");

  check("IRQ pin (engine B has a result)", digitalRead(PIN_IRQ), 1);
  check("B RX FIFO level", (readReg(ENG_B, R_STATUS) >> 4) & 7, 1);
  int expectClocks = 8 * (clkdiv + 1);
  int measured = readReg(ENG_B, R_RX);
  check("B measured A's bit time (chip clocks)", measured, expectClocks);
  if (measured) Serial.printf("  %-44s %8.0f baud\n", "   = engine B's estimate of the baud rate", CHIP_HZ / measured);
  check("IRQ pin after reading", digitalRead(PIN_IRQ), 0);
}

void runAll() {
  errors = 0;
  Serial.println("\n==== Whole chip on the MachXO3L kit: two engines + SPI host port ====");
  runAt(115200);
  runAt(57600);
  runAt(19200);
  Serial.printf("\n==== %s (%d problems) ====\nSend 'r' to run again.\n", errors ? "FAIL" : "PASS", errors);
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  pinMode(PIN_CS, OUTPUT); digitalWrite(PIN_CS, HIGH);
  pinMode(PIN_IRQ, INPUT);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, -1);
  runAll();
}

void loop() {
  if (Serial.available() && Serial.read() == 'r') runAll();
}
