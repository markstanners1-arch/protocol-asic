// Whole-chip bench test: ESP32 as host for the chip (src/chip.v) running on the MachXO3L Starter Kit.
// The board must be running the chip build: fpga/machxo3/build/chip.bit (12 MHz) or fpga/cyclone4 (50 MHz); set CHIP_HZ below.
//
// Wiring (kit header J4 -> ESP32):
//   J4-3  CS    -> GPIO 5        J4-5  MOSI -> GPIO 23       J4-7  MISO -> GPIO 19
//   J4-9  SCK   -> GPIO 18       J4-11 GND  -> GND
//   J4-6  engine pin 0 (engine A's UART out)  -> GPIO 16 (Serial2 RX)
//   J4-4  IRQ   -> GPIO 4        (J4-1 and J4-2 are 3.3 V: leave them alone)
//   J4-26 (G15) engine pin 15 <- GPIO 17   (glitch filter test: the ESP32 sends pulses into the chip)
//
// What it does, at three baud rates:
//   1. loads engine B with programs/measure_baud.asm and starts it (it watches engine pin 0)
//   2. loads engine A with programs/uart_tx.asm, sets its clock divider for the baud rate, starts it
//   3. sends a line of text through engine A, a word at a time over SPI, never overfilling its FIFO
//   4. reads what actually came out of the chip's pin on Serial2, and compares
//   5. reads engine B's measurement of engine A's bit time back over SPI
// Results on the Serial Monitor at 115200. Send 'r' to run again, 'i' for the I2C test (see i2cTest below).

#include <SPI.h>
#include "programs.h"

const int PIN_CS = 5, PIN_SCK = 18, PIN_MISO = 19, PIN_MOSI = 23, PIN_IRQ = 4, PIN_RX2 = 16, PIN_PULSE = 17;
// Which board the chip is running on: the chip clock sets the SPI limit (clk/8), the baud dividers and the filter hold.
//   MachXO3L kit (fpga/machxo3/build/chip.bit): 12 MHz.   Cyclone IV board (fpga/cyclone4): 50 MHz, the ASIC's own speed.
const float CHIP_HZ = 12e6;
const uint32_t SPI_HZ = (CHIP_HZ >= 50e6) ? 4000000 : 1000000;   // under clk/8 either way
const float CHIP_MHZ = CHIP_HZ / 1e6;
// Filter hold of about 5 us: N=15 with P chosen for the clock (hold = 16 x 2^P clocks; P=2 at 12 MHz, P=4 at 50 MHz)
const int FILTER_P = (CHIP_HZ >= 50e6) ? 4 : 2;
const uint16_t FILTER_ON = (FILTER_P << 4) | 0xF;
const float FILTER_HOLD_US = 16.0 * (1 << FILTER_P) / CHIP_MHZ;
const int PULSE_PIN = 15;                  // engine pin wired to GPIO 17: 17 = ball F15 (J4 hole 28); 15 = G15 (hole 26)

// registers (docs/host_port.md)
const int R_CTRL = 0x20, R_CLKDIV = 0x21, R_WRAP = 0x22, R_OUTCFG = 0x23, R_MISC = 0x24, R_INCFG = 0x25,
          R_TX = 0x26, R_RX = 0x27, R_STATUS = 0x28, R_FILTER = 0x29;
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

// Glitch filter on real hardware: engine B times low pulses on engine pin 15, which the ESP32 drives.
void pulseLow(int us) { noInterrupts(); digitalWrite(PIN_PULSE, LOW); delayMicroseconds(us); digitalWrite(PIN_PULSE, HIGH); interrupts(); delay(2); }
void filterTest() {
  Serial.println();
  Serial.printf("-- glitch filter: engine B times low pulses on engine pin %d (driven by the ESP32)\n", PULSE_PIN);
  // Serial2's default TX pin is GPIO 17: release the port and take the pin back (bench bug, 2 Nov 2026)
  Serial2.end();
  pinMode(PIN_PULSE, OUTPUT); digitalWrite(PIN_PULSE, HIGH); delay(5);
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  loadProgram(ENG_B, PROG_MEASURE_PULSE, PROG_MEASURE_PULSE_LEN);
  writeReg(ENG_B, R_CLKDIV, 0);
  writeReg(ENG_B, R_WRAP, wrapReg(0, PROG_MEASURE_PULSE_WRAP_BOTTOM, PROG_MEASURE_PULSE_WRAP_TOP));
  writeReg(ENG_B, R_OUTCFG, 0); writeReg(ENG_B, R_MISC, 0);
  writeReg(ENG_B, R_INCFG, PULSE_PIN);                            // in_base = the engine pin the lead is on
  for (int on = 0; on < 2; on++) {
    writeReg(ENG_A, R_FILTER, on ? FILTER_ON : 0x00);
    if (on) Serial.printf("  filter on: N=15 P=%d, hold %.1f us\n", FILTER_P, FILTER_HOLD_US);
    check(on ? "FILTER read back (on)" : "FILTER read back (off)", readReg(ENG_B, R_FILTER), on ? FILTER_ON : 0);
    writeReg(ENG_B, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 1);       // restart B, empty FIFO
    delay(2);
    for (int k = 0; k < 2; k++) {
      int us = k ? 20 : 2;
      while ((readReg(ENG_B, R_STATUS) >> 4) & 7) readReg(ENG_B, R_RX);   // drain
      pulseLow(us);
      int lvl = (readReg(ENG_B, R_STATUS) >> 4) & 7;
      int clocks = lvl ? readReg(ENG_B, R_RX) : 0;
      Serial.printf("  filter %-3s %2d us pulse: engine B saw %s", on ? "on" : "off", us, lvl ? "it, " : "nothing");
      if (lvl) Serial.printf("%d clocks = %.1f us", clocks, clocks / CHIP_MHZ);
      bool expectSeen = !(on && us == 2);
      bool ok = expectSeen ? (lvl == 1 && fabs(clocks / CHIP_MHZ - us) < 1.5 + 0.1 * us) : (lvl == 0);
      if (!ok) errors++;
      Serial.println(ok ? "   ok" : "   WRONG");
    }
  }
  writeReg(ENG_A, R_FILTER, 0);
}

// Diagnostic: what level does the chip see on engine pin 15 when the ESP32 holds GPIO 17 low, then high?
void pinDiag() {
  Serial.println();
  Serial.printf("-- pin diagnostic: engine B reads the raw level of engine pin %d while GPIO 17 is held\n", PULSE_PIN);
  Serial2.end();
  pinMode(PIN_PULSE, OUTPUT);
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  writeReg(ENG_A, 0x29, 0);                                        // filter shortest
  loadProgram(ENG_B, PROG_READ_PINS, PROG_READ_PINS_LEN);
  writeReg(ENG_B, R_CLKDIV, 0);
  writeReg(ENG_B, R_WRAP, wrapReg(0, PROG_READ_PINS_WRAP_BOTTOM, PROG_READ_PINS_WRAP_TOP));
  writeReg(ENG_B, R_MISC, 0); writeReg(ENG_B, R_INCFG, PULSE_PIN);
  writeReg(ENG_B, R_CTRL, 1);
  for (int lvl = 0; lvl < 2; lvl++) {
    digitalWrite(PIN_PULSE, lvl); delay(5);
    // the engine refills the FIFO as fast as it is read, so read past the 4 stale entries and keep the last
    uint16_t v = 0;
    for (int i = 0; i < 8; i++) v = readReg(ENG_B, R_RX);
    Serial.printf("  GPIO 17 held %s -> chip sees pins %d..: 0x%04X (that pin = %d)  %s", lvl ? "HIGH" : "LOW ", PULSE_PIN, v, v & 1,
                  ((v & 1) == lvl) ? "ok" : "WRONG");
    Serial.println();
    if ((v & 1) != lvl) errors++;
  }
  digitalWrite(PIN_PULSE, HIGH);
  writeReg(ENG_B, R_CTRL, 0);
}

// ---- I2C on real wires: engine A is the master, engine B watches the bus, the ESP32 is the slave (Wire slave
//      mode, address 0x50, a register-pointer device like model/i2c_slave.py). The ESP32 stretches SCL while its
//      interrupt handler runs on the S2/S3/C3 parts; the original ESP32's slave hardware cannot stretch, so its reply
//      must be loaded before the master asks (slaveWrite in onReceive when the pointer arrives), and the read is done
//      as pointer-write, STOP, then a fresh START: a repeated START gives the ESP32 no time to load the reply.
// Wiring: J4-10 (M16, engine pin 2) = SCL -> GPIO 22;  J4-13 (L15, engine pin 3) = SDA -> GPIO 21;
//         and 4.7 k pull-ups from each line to 3.3 V (the FPGA's and ESP32's internal pull-ups are too weak above ~10 kHz).
// Send 'i' on the Serial Monitor to run it (it needs those two leads; the normal run does not).
#include <Wire.h>
const int I2C_SCL_ENG = 2, I2C_SDA_ENG = 3, ESP_SDA = 21, ESP_SCL = 22, I2C_ADDR = 0x50;
volatile uint8_t slaveRegs[16]; volatile int slavePtr = 0, slaveWrites = 0, slaveRequests = 0;
void onSlaveReceive(int n) {
  bool first = true;
  while (Wire.available()) {
    int b = Wire.read();
    if (first) { slavePtr = b & 15; first = false; }
    else { slaveRegs[slavePtr] = b; slavePtr = (slavePtr + 1) & 15; slaveWrites++; }
  }
  if (n == 1) {                                                   // pointer only: a read is coming, load 4 bytes now
    uint8_t out[4];
    for (int i = 0; i < 4; i++) out[i] = slaveRegs[(slavePtr + i) & 15];
    Wire.slaveWrite(out, 4);
  }
}
void onSlaveRequest() { slaveRequests++; }                        // the reply was loaded in onSlaveReceive
uint16_t i2cWord(int routine, int data = 0) { return (routine << 11) | data; }
int drainB(int *buf, int max) {                                   // what engine B (the watcher) has reported so far
  int n = 0;
  while (n < max && ((readReg(ENG_B, R_STATUS) >> 4) & 7)) buf[n++] = readReg(ENG_B, R_RX);
  return n;
}
// run one command on the master; returns what it pushed back (ACK bit for send, the byte for recv), -1 if nothing
int i2cCmd(uint16_t word, bool expectReply) {
  writeReg(ENG_A, R_TX, word);
  for (int t = 0; t < 200; t++) {                                 // a byte takes ~1 ms at 10 kHz, more if stretched
    delayMicroseconds(100);
    if (!expectReply) { if (((readReg(ENG_A, R_STATUS) & 7) == 0)) return -1; continue; }
    if ((readReg(ENG_A, R_STATUS) >> 4) & 7) return readReg(ENG_A, R_RX);
  }
  return -1;
}
void i2cTest() {
  errors = 0;
  Serial.println("\n==== I2C: engine A master, engine B watching, ESP32 as the slave at 0x50 ====");
  Wire.begin((uint8_t)I2C_ADDR, ESP_SDA, ESP_SCL, 100000);
  Wire.onReceive(onSlaveReceive); Wire.onRequest(onSlaveRequest);
  for (int i = 0; i < 16; i++) slaveRegs[i] = 0;
  slaveWrites = slaveRequests = 0;
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  writeReg(ENG_A, R_FILTER, 0);                                   // the shortest filter: an I2C edge must get through
  int clkdiv = (int)(CHIP_HZ / (10.0 * 10000) + 0.5) - 1;         // 10 kHz SCL: kind to weak pull-ups
  loadProgram(ENG_A, PROG_I2C_MASTER, PROG_I2C_MASTER_LEN);
  writeReg(ENG_A, R_CLKDIV, clkdiv);
  writeReg(ENG_A, R_WRAP, wrapReg(0, PROG_I2C_MASTER_WRAP_BOTTOM, PROG_I2C_MASTER_WRAP_TOP));
  writeReg(ENG_A, R_OUTCFG, I2C_SDA_ENG | (1 << 5) | (I2C_SDA_ENG << 10));          // out/set = SDA
  writeReg(ENG_A, R_MISC, 1 | (I2C_SCL_ENG << 3) | (1 << 8) | (1 << 10) | (1 << 13)); // set_count 1, side = SCL, 1 bit, opt, side_dir
  writeReg(ENG_A, R_INCFG, I2C_SDA_ENG);                                              // in = SDA (SCL = the pin below)
  loadProgram(ENG_B, PROG_I2C_SNIFF, PROG_I2C_SNIFF_LEN);
  writeReg(ENG_B, R_CLKDIV, 0);
  writeReg(ENG_B, R_WRAP, wrapReg(0, PROG_I2C_SNIFF_WRAP_BOTTOM, PROG_I2C_SNIFF_WRAP_TOP));
  writeReg(ENG_B, R_OUTCFG, 0); writeReg(ENG_B, R_MISC, 1 << 11);                      // out_right
  writeReg(ENG_B, R_INCFG, I2C_SCL_ENG | (I2C_SDA_ENG << 5));                          // in_base = SCL, jmp_pin = SDA
  check("A MISC read back", readReg(ENG_A, R_MISC), 1 | (I2C_SCL_ENG << 3) | (1 << 8) | (1 << 10) | (1 << 13));
  writeReg(ENG_B, R_CTRL, 1); writeReg(ENG_A, R_CTRL, 1); delay(5);
  Serial.printf("  SCL %.1f kHz nominal (clkdiv %d)\n", CHIP_HZ / (10.0 * (clkdiv + 1)) / 1000, clkdiv);

  const uint8_t data[4] = {0xA5, 0x3C, 0x00, 0xFF};
  int seen[16], nseen = 0;
  // write 4 bytes to register 3
  i2cCmd(i2cWord(I2C_MASTER_START), false);
  check("address 0xA0 acked", i2cCmd(i2cWord(I2C_MASTER_SEND, 0xA0 << 3), true), 0);
  check("pointer 3 acked", i2cCmd(i2cWord(I2C_MASTER_SEND, 3 << 3), true), 0);
  nseen += drainB(seen + nseen, 16 - nseen);
  for (int i = 0; i < 4; i++) { check("data byte acked", i2cCmd(i2cWord(I2C_MASTER_SEND, data[i] << 3), true), 0); nseen += drainB(seen + nseen, 16 - nseen); }
  i2cCmd(i2cWord(I2C_MASTER_STOP), false); delay(5);
  check("ESP32 slave received 4 data bytes", slaveWrites, 4);
  bool same = true; for (int i = 0; i < 4; i++) same &= (slaveRegs[3 + i] == data[i]);
  Serial.printf("  %-44s %02X %02X %02X %02X  %s\n", "ESP32 slave registers 3..6", slaveRegs[3], slaveRegs[4], slaveRegs[5], slaveRegs[6], same ? "ok" : "WRONG");
  if (!same) errors++;
  check("engine B saw 6 bytes", nseen, 6);
  const int want[6] = {0xA0, 3, 0xA5, 0x3C, 0x00, 0xFF};
  for (int i = 0; i < 6 && i < nseen; i++) check("  B: byte + ACK bit", seen[i], want[i] << 1);
  // read them back: pointer write, STOP, a moment for the ESP32 to load its reply, then a fresh START
  nseen = 0;
  i2cCmd(i2cWord(I2C_MASTER_START), false);
  check("address 0xA0 acked", i2cCmd(i2cWord(I2C_MASTER_SEND, 0xA0 << 3), true), 0);
  check("pointer 3 acked", i2cCmd(i2cWord(I2C_MASTER_SEND, 3 << 3), true), 0);
  i2cCmd(i2cWord(I2C_MASTER_STOP), false); delay(10);
  i2cCmd(i2cWord(I2C_MASTER_START), false);
  check("address 0xA1 (read) acked", i2cCmd(i2cWord(I2C_MASTER_SEND, 0xA1 << 3), true), 0);
  nseen += drainB(seen + nseen, 16 - nseen);
  for (int i = 0; i < 4; i++) { check("byte read back", i2cCmd(i2cWord(I2C_MASTER_RECV, (i < 3) << 10), true), data[i]); nseen += drainB(seen + nseen, 16 - nseen); }
  i2cCmd(i2cWord(I2C_MASTER_STOP), false); delay(5);
  check("ESP32 slave answered one read request", slaveRequests, 1);
  check("engine B saw 7 bytes", nseen, 7);
  const int want2[7] = {0xA0 << 1, 3 << 1, 0xA1 << 1, 0xA5 << 1, 0x3C << 1, 0x00 << 1, (0xFF << 1) | 1};
  for (int i = 0; i < 7 && i < nseen; i++) check("  B: byte + ACK bit (last NAKed)", seen[i], want2[i]);
  // nobody home
  i2cCmd(i2cWord(I2C_MASTER_START), false);
  check("address 0x23 (no such device) NAKed", i2cCmd(i2cWord(I2C_MASTER_SEND, (0x23 << 1) << 3), true), 1);
  i2cCmd(i2cWord(I2C_MASTER_STOP), false);
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  Wire.end();
  Serial.printf("\n==== I2C %s (%d problems) ====\n", errors ? "FAIL" : "PASS", errors);
}

void runAll() {
  errors = 0;
  Serial.println("\n==== Whole chip on the MachXO3L kit: two engines + SPI host port ====");
  runAt(115200);
  runAt(57600);
  runAt(19200);
  pinDiag();
  filterTest();
  Serial.printf("\n==== %s (%d problems) ====\nSend 'r' to run again.\n", errors ? "FAIL" : "PASS", errors);
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  pinMode(PIN_CS, OUTPUT); digitalWrite(PIN_CS, HIGH);
  pinMode(PIN_IRQ, INPUT);
  pinMode(PIN_PULSE, OUTPUT); digitalWrite(PIN_PULSE, HIGH);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, -1);
  runAll();
}

void loop() {
  if (Serial.available()) { int c = Serial.read(); if (c == 'r') runAll(); else if (c == 'i') i2cTest(); }
}
