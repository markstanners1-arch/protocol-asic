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
// Results on the Serial Monitor at 115200. Send 'r' to run again, 'i' / 'n' for the I2C test (ESP32 / external slave),
// 's' for SPI to the 74HC595, and the bench helpers: 'p' lead probe, 'q' hold the IRQ high for 15 s, 'l' repeating ID
// reads for 30 s (a signal for the oscilloscope). From the PC: esp32\rerun.ps1 -Cmd <letter>.

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
          R_TX = 0x26, R_RX = 0x27, R_STATUS = 0x28, R_FILTER = 0x29, R_ID = 0x2A;
const int ENG_A = 0, ENG_B = 1, ENG_C = 2;   // C is on the ASIC and the Cyclone board, not the kit; the ID register says how many

// the 16-bit command (host_port.md v0.2): [15] read, [14:12] engine, [5:0] register
uint16_t cmd(bool rd, int eng, int reg) { return (rd ? 0x8000 : 0) | ((eng & 7) << 12) | (reg & 0x3F); }
void begin_(uint16_t c) { SPI.beginTransaction(SPISettings(SPI_HZ, MSBFIRST, SPI_MODE0)); digitalWrite(PIN_CS, LOW); delayMicroseconds(2); SPI.transfer16(c); }
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
// Send 'i' on the Serial Monitor to run it (it needs those two leads; the normal run does not), or 'n' with another
// board as the slave on the same wires (arduino/i2c_slave_nano, which stretches the clock): then the read-back is also
// done with a repeated START. Not both at once: the ESP32 and the UNO both answer at 0x50, so unplug the UNO before 'i'.
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
// the master's one transfer routine: nine SDA levels out (byte, then the ACK slot), nine levels seen back
// as byte << 1 | ACK bit. Send: ACK slot released, reply = byte as it went on the wire, ACK bit 0 if the slave acked.
// Read: SDA released for the byte, our ACK (0) or NAK (1) in the slot; reply = the slave's byte << 1 | our ACK bit.
int i2cSend(uint8_t b);
int i2cRecv(bool ack);
int sent(uint8_t b) { return b << 1; }                           // the reply for a byte sent and acked
int drainB(int *buf, int max) {                                   // what engine B (the watcher) has reported so far
  int n = 0;
  while (n < max && ((readReg(ENG_B, R_STATUS) >> 4) & 7)) buf[n++] = readReg(ENG_B, R_RX);
  return n;
}
// run one command on the master; returns what it pushed back (byte on the wire << 1 | ACK bit), -1 if nothing
int i2cCmd(uint16_t word, bool expectReply) {
  writeReg(ENG_A, R_TX, word);
  for (int t = 0; t < 200; t++) {                                 // a byte takes ~1 ms at 10 kHz, more if stretched
    delayMicroseconds(100);
    if (!expectReply) { if (((readReg(ENG_A, R_STATUS) & 7) == 0)) return -1; continue; }
    if ((readReg(ENG_A, R_STATUS) >> 4) & 7) return readReg(ENG_A, R_RX);
  }
  return -1;
}
int i2cSend(uint8_t b) { return i2cCmd(i2cWord(I2C_MASTER_XFER, (b << 3) | (1 << 2)), true); }
int i2cRecv(bool ack)  { return i2cCmd(i2cWord(I2C_MASTER_XFER, (0xFF << 3) | ((ack ? 0 : 1) << 2)), true); }
// external = true: the slave is another board on the same two wires (e.g. arduino/i2c_slave_nano, which stretches the
// clock); the ESP32's own I2C stays off, and the read-back is also done with a repeated START.
void i2cTest(bool external = false) {
  errors = 0;
  Serial.printf("\n==== I2C: engine A master, engine B watching, %s as the slave at 0x50 ====\n", external ? "an external board" : "the ESP32");
  if (!external) {
    Wire.begin((uint8_t)I2C_ADDR, ESP_SDA, ESP_SCL, 100000);
    Wire.onReceive(onSlaveReceive); Wire.onRequest(onSlaveRequest);
  }
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

  const uint8_t data[4] = {0xA5, 0x3C, 0x00, 0x7E};              // last byte not 0xFF: an unanswered read must fail
  int seen[16], nseen = 0;
  // write 4 bytes to register 3
  i2cCmd(i2cWord(I2C_MASTER_START), false);
  check("address 0xA0 sent and acked", i2cSend(0xA0), sent(0xA0));
  check("pointer 3 sent and acked", i2cSend(3), sent(3));
  nseen += drainB(seen + nseen, 16 - nseen);
  for (int i = 0; i < 4; i++) { check("data byte sent and acked", i2cSend(data[i]), sent(data[i])); nseen += drainB(seen + nseen, 16 - nseen); }
  i2cCmd(i2cWord(I2C_MASTER_STOP), false); delay(5);
  if (!external) {
    check("ESP32 slave received 4 data bytes", slaveWrites, 4);
    bool same = true; for (int i = 0; i < 4; i++) same &= (slaveRegs[3 + i] == data[i]);
    Serial.printf("  %-44s %02X %02X %02X %02X  %s\n", "ESP32 slave registers 3..6", slaveRegs[3], slaveRegs[4], slaveRegs[5], slaveRegs[6], same ? "ok" : "WRONG");
    if (!same) errors++;
  }
  check("engine B saw 6 bytes", nseen, 6);
  const int want[6] = {0xA0, 3, 0xA5, 0x3C, 0x00, 0x7E};
  for (int i = 0; i < 6 && i < nseen; i++) check("  B: byte + ACK bit", seen[i], want[i] << 1);
  // read them back: pointer write, STOP, a moment for the ESP32 to load its reply, then a fresh START
  nseen = 0;
  i2cCmd(i2cWord(I2C_MASTER_START), false);
  check("address 0xA0 sent and acked", i2cSend(0xA0), sent(0xA0));
  check("pointer 3 sent and acked", i2cSend(3), sent(3));
  i2cCmd(i2cWord(I2C_MASTER_STOP), false); delay(10);
  i2cCmd(i2cWord(I2C_MASTER_START), false);
  check("address 0xA1 (read) sent and acked", i2cSend(0xA1), sent(0xA1));
  nseen += drainB(seen + nseen, 16 - nseen);
  for (int i = 0; i < 4; i++) { check("byte read back (+ our ACK bit)", i2cRecv(i < 3), (data[i] << 1) | (i < 3 ? 0 : 1)); nseen += drainB(seen + nseen, 16 - nseen); }
  i2cCmd(i2cWord(I2C_MASTER_STOP), false); delay(5);
  if (!external) check("ESP32 slave answered one read request", slaveRequests, 1);
  check("engine B saw 7 bytes", nseen, 7);
  const int want2[7] = {0xA0 << 1, 3 << 1, 0xA1 << 1, 0xA5 << 1, 0x3C << 1, 0x00 << 1, (0x7E << 1) | 1};
  for (int i = 0; i < 7 && i < nseen; i++) check("  B: byte + ACK bit (last NAKed)", seen[i], want2[i]);
  if (external) {                                                 // once more with a repeated START: the slave must stretch
    Serial.println("  read back again, this time with a repeated START:");
    nseen = 0;
    i2cCmd(i2cWord(I2C_MASTER_START), false);
    check("address 0xA0 sent and acked", i2cSend(0xA0), sent(0xA0));
    check("pointer 3 sent and acked", i2cSend(3), sent(3));
    i2cCmd(i2cWord(I2C_MASTER_START), false);
    check("address 0xA1 (read) sent and acked", i2cSend(0xA1), sent(0xA1));
    nseen += drainB(seen + nseen, 16 - nseen);
    for (int i = 0; i < 4; i++) { check("byte read back (+ our ACK bit)", i2cRecv(i < 3), (data[i] << 1) | (i < 3 ? 0 : 1)); nseen += drainB(seen + nseen, 16 - nseen); }
    i2cCmd(i2cWord(I2C_MASTER_STOP), false); delay(5);
    check("engine B saw 7 bytes", nseen, 7);
    for (int i = 0; i < 7 && i < nseen; i++) check("  B: byte + ACK bit (last NAKed)", seen[i], want2[i]);
  }
  // nobody home
  i2cCmd(i2cWord(I2C_MASTER_START), false);
  check("address 0x23 (no such device) NAKed", i2cSend(0x23 << 1), ((0x23 << 1) << 1) | 1);
  i2cCmd(i2cWord(I2C_MASTER_STOP), false);
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  if (!external) Wire.end();
  Serial.printf("\n==== I2C %s (%d problems) ====\n", errors ? "FAIL" : "PASS", errors);
}

// ---- SPI on real wires: engine A is the master (programs/spi_master.asm) driving a 74HC595 shift register; its
//      serial output QH' comes back on MISO, so each transfer returns the byte sent the transfer before. Engine B
//      measures the SCK low time. Send 's' on the Serial Monitor.
// Engine pins 4-7:  J4-14 (L16) pin 4 = SCK  -> 595 SRCLK (11)      J4-15 (K14) pin 5 = MOSI -> 595 SER (14)
//                   J4-16 (K16) pin 6 = MISO <- 595 QH' (9)         J4-17 (K15) pin 7 = CS   -> 595 RCLK (12), latches on deselect
// 595: VCC (16) and SRCLR (10) to 3.3 V, OE (13) and GND (8) to ground, QA..QH (15, 1..7) to LEDs via 220 R to ground.
const int SPI_SCK_ENG = 4, SPI_MOSI_ENG = 5, SPI_MISO_ENG = 6, SPI_CS_ENG = 7;
int spiXfer(uint8_t b) { return i2cCmd((SPI_MASTER_XFER << 11) | (b << 3), true); }
void spiSelect()       { i2cCmd(SPI_MASTER_SELECT << 11, false); }
void spiDeselect()     { i2cCmd(SPI_MASTER_DESELECT << 11, false); }
void spiTest() {
  errors = 0;
  Serial.println("\n==== SPI: engine A master -> 74HC595 (QH' back on MISO), engine B timing SCK ====");
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  writeReg(ENG_A, R_FILTER, 0);
  int clkdiv = (int)(CHIP_HZ / (6.0 * 100000) + 0.5) - 1;          // 100 kHz SCK: 6 ticks per bit
  loadProgram(ENG_A, PROG_SPI_MASTER, PROG_SPI_MASTER_LEN);
  writeReg(ENG_A, R_CLKDIV, clkdiv);
  writeReg(ENG_A, R_WRAP, wrapReg(0, PROG_SPI_MASTER_WRAP_BOTTOM, PROG_SPI_MASTER_WRAP_TOP));
  writeReg(ENG_A, R_OUTCFG, SPI_MOSI_ENG | (1 << 5) | (SPI_SCK_ENG << 10));          // out = MOSI, set_base = SCK (4 pins)
  writeReg(ENG_A, R_MISC, 4 | (SPI_SCK_ENG << 3) | (1 << 8) | (1 << 10));           // set_count 4, side = SCK, 1 bit, opt
  writeReg(ENG_A, R_INCFG, SPI_MISO_ENG);
  loadProgram(ENG_B, PROG_MEASURE_PULSE, PROG_MEASURE_PULSE_LEN);                   // B times low pulses on SCK
  writeReg(ENG_B, R_CLKDIV, 0);
  writeReg(ENG_B, R_WRAP, wrapReg(0, PROG_MEASURE_PULSE_WRAP_BOTTOM, PROG_MEASURE_PULSE_WRAP_TOP));
  writeReg(ENG_B, R_OUTCFG, 0); writeReg(ENG_B, R_MISC, 0); writeReg(ENG_B, R_INCFG, SPI_SCK_ENG);
  check("A MISC read back", readReg(ENG_A, R_MISC), 4 | (SPI_SCK_ENG << 3) | (1 << 8) | (1 << 10));
  writeReg(ENG_B, R_CTRL, 1); writeReg(ENG_A, R_CTRL, 1); delay(5);
  while ((readReg(ENG_B, R_STATUS) >> 4) & 7) readReg(ENG_B, R_RX);              // B saw SCK go from floating to driven low
  Serial.printf("  SCK %.0f kHz nominal (clkdiv %d)\n", CHIP_HZ / (6.0 * (clkdiv + 1)) / 1000, clkdiv);
  const uint8_t seq[4] = {0xA5, 0x3C, 0x81, 0x55};
  int got[4];
  for (int i = 0; i < 4; i++) {
    spiSelect(); got[i] = spiXfer(seq[i]); spiDeselect();                           // deselect = RCLK rises: LEDs update
    bool firstReading = (i == 0);                                                   // B's first value is the idle gap
    while ((readReg(ENG_B, R_STATUS) >> 4) & 7) {                                   // before transfer 1: not a bit
      int clocks = readReg(ENG_B, R_RX);
      if (i == 0 && !firstReading) check("B: SCK low time (chip clocks)", clocks, 3 * (clkdiv + 1));
      firstReading = false;
    }
    delay(300);                                                                     // so the LEDs can be watched
  }
  Serial.printf("  %-44s %02X (whatever the 595 held before)\n", "first transfer returned", got[0]);
  for (int i = 1; i < 4; i++) check("transfer returned the previous byte", got[i], seq[i - 1]);
  Serial.printf("  %-44s %s\n", "LEDs should now show 0x55", "0 1 0 1 0 1 0 1 (QH..QA)");
  // a little show: walk a single lit LED along, then leave the pattern
  for (int k = 0; k < 16; k++) { spiSelect(); spiXfer(1 << (k & 7)); spiDeselect(); delay(120); }
  spiSelect(); spiXfer(0x55); spiDeselect();
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  Serial.printf("\n==== SPI %s (%d problems) ====\n", errors ? "FAIL" : "PASS", errors);
}

void runAll() {
  errors = 0;
  uint16_t id = readReg(ENG_A, R_ID);
  Serial.printf("\n==== Whole chip: %d engines + SPI host port (ID 0x%04X) ====\n", id & 15, id);
  check("ID: host port spec version 2", (id >> 4) & 15, 2);
  check("ID: at least two engines", (id & 15) >= 2, 1);
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

// 'q': hold the IRQ high for 15 s so the lead (J4-4 / K13 -> GPIO 4) and the kit's IRQ LED (P16) can be checked:
// engine B runs read_pins, which pushes for ever, so its RX FIFO fills and stays non-empty.
void irqHold() {
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  loadProgram(ENG_B, PROG_READ_PINS, PROG_READ_PINS_LEN);
  writeReg(ENG_B, R_WRAP, wrapReg(0, PROG_READ_PINS_WRAP_BOTTOM, PROG_READ_PINS_WRAP_TOP));
  writeReg(ENG_B, R_CTRL, 1); delay(5);
  Serial.println();
  Serial.println("==== IRQ hold: engine B keeps data waiting for 15 s; the kit's IRQ LED should be lit; GPIO 4 polled ====");
  for (int i = 0; i < 15; i++) {
    Serial.printf("  t=%2d s   GPIO 4 = %d   B RX level %d", i, digitalRead(PIN_IRQ), (readReg(ENG_B, R_STATUS) >> 4) & 7);
    Serial.println();
    delay(1000);
  }
  writeReg(ENG_B, R_CTRL, 0);
  Serial.println("==== IRQ hold done ====");
}

// 'p': lead probe. The chip's two outputs to us (MISO, IRQ) are read with the ESP32's pull-up and then its pull-down:
// a driven pin reads the same both ways, an open lead follows the pull. Then one raw ID read.
void leadProbe() {
  const int pins[2] = {PIN_MISO, PIN_IRQ}; const char *names[2] = {"MISO (J4-7, L14 -> GPIO 19)", "IRQ  (J4-4, K13 -> GPIO 4)"};
  Serial.println();
  Serial.println("==== lead probe ====");
  for (int i = 0; i < 2; i++) {
    pinMode(pins[i], INPUT_PULLUP); delay(2); int up = digitalRead(pins[i]);
    pinMode(pins[i], INPUT_PULLDOWN); delay(2); int dn = digitalRead(pins[i]);
    pinMode(pins[i], INPUT);
    Serial.printf("  %s: with pull-up %d, with pull-down %d -> %s", names[i], up, dn,
                  up == dn ? (up ? "driven HIGH by something" : "driven LOW by something") : "FLOATING: lead open or in the wrong hole");
    Serial.println();
  }
  SPI.end(); SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, -1);   // end first: a second begin() leaves GPIO 19 as a plain input (found 3 Nov, late)
  uint16_t id = readReg(ENG_A, R_ID);
  Serial.printf("  raw ID read: 0x%04X (0x0022 = two engines answering; 0x0000 = chip not seeing the command, check MOSI J4-5/M14 -> GPIO 23, CS J4-3/K12 -> GPIO 5, SCK J4-9/M15 -> GPIO 18; 0xFFFF = MISO open)", id);
  Serial.println();
  Serial.println("==== lead probe done ====");
}

// 'l': scope loop. Reads the ID register over and over for 30 s (one 16-bit command + one 16-bit word, SPI_HZ), so SCK,
// MOSI, CS and MISO carry a repeating burst to put a probe on; MISO should show 0x0022 = 0000 0000 0010 0010 after the command.
void scopeLoop() {
  Serial.println();
  Serial.println("==== scope loop: ID reads for 30 s (probe J4-7 / L14 for MISO, J4-9 / M15 for SCK, J4-3 / K12 for CS) ====");
  for (int t = 0; t < 30; t++) {
    uint16_t id = 0; int same = 0;
    for (int i = 0; i < 1000; i++) { uint16_t v = readReg(ENG_A, R_ID); if (i == 0) id = v; same += (v == id); }
    if (t % 5 == 0) { Serial.printf("  t=%2d s  ID read 0x%04X, %d of 1000 reads identical", t, id, same); Serial.println(); }
  }
  Serial.println("==== scope loop done ====");
}

// 'b': I2C wire check. Engine B reads engine pins 0-15 raw while the ESP32 (I2C off, pins as plain GPIO) leaves both
// lines alone, then pulls its SDA pin (GPIO 21) low, then its SCL pin (GPIO 22) low. Shows which chip pin each one reaches.
void i2cWireCheck() {
  Wire.end();
  pinMode(ESP_SDA, INPUT); pinMode(ESP_SCL, INPUT);
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  writeReg(ENG_A, R_FILTER, 0);
  loadProgram(ENG_B, PROG_READ_PINS, PROG_READ_PINS_LEN);
  writeReg(ENG_B, R_CLKDIV, 0);
  writeReg(ENG_B, R_WRAP, wrapReg(0, PROG_READ_PINS_WRAP_BOTTOM, PROG_READ_PINS_WRAP_TOP));
  writeReg(ENG_B, R_MISC, 0); writeReg(ENG_B, R_INCFG, 0);
  writeReg(ENG_B, R_CTRL, 1);
  Serial.println();
  Serial.println("==== I2C wire check: engine pins 0-7 as the chip sees them (bit 2 = SCL J4-10/M16, bit 3 = SDA J4-13/L15) ====");
  const char *what[3] = {"both lines released (expect pins 2 and 3 high: pull-ups present)",
                         "ESP32 GPIO 21 (its SDA) pulled low (expect pin 3 low)",
                         "ESP32 GPIO 22 (its SCL) pulled low (expect pin 2 low)"};
  for (int step = 0; step < 3; step++) {
    if (step == 1) { pinMode(ESP_SDA, OUTPUT); digitalWrite(ESP_SDA, LOW); }
    if (step == 2) { pinMode(ESP_SDA, INPUT); pinMode(ESP_SCL, OUTPUT); digitalWrite(ESP_SCL, LOW); }
    delay(5);
    uint32_t v20 = 0;                                                // all 20 engine pins: in_base 0 gives 0-15, in_base 4 gives 4-19
    for (int base = 0; base <= 4; base += 4) {
      writeReg(ENG_B, R_CTRL, 0); writeReg(ENG_B, R_INCFG, base); writeReg(ENG_B, R_CTRL, 1); delay(2);
      uint16_t v = 0;
      for (int i = 0; i < 8; i++) v = readReg(ENG_B, R_RX);
      v20 = base ? (v20 & 0xF) | ((uint32_t)v << 4) : v;
    }
    Serial.printf("  %-66s pins 19..0 = ", what[step]);
    for (int b = 19; b >= 0; b--) { Serial.print((v20 >> b) & 1); if (b == 16 || b == 8) Serial.print(' '); }
    Serial.printf("   (SCL pin 2 = %d, SDA pin 3 = %d)", (v20 >> 2) & 1, (v20 >> 3) & 1);
    Serial.println();
  }
  pinMode(ESP_SCL, INPUT); pinMode(ESP_SDA, INPUT);
  writeReg(ENG_B, R_CTRL, 0);
  Serial.println("==== wire check done ====");
}

// 'k': hold the ESP32's SCL pin (GPIO 22) low for 30 s, engine B reporting chip pin 2 each second: meter both ends
// of the lead meanwhile (GPIO 22 and J4-10 / M16 should both read 0 V).
void sclHoldLow() {
  Wire.end();
  pinMode(ESP_SDA, INPUT); pinMode(ESP_SCL, OUTPUT); digitalWrite(ESP_SCL, LOW);
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  writeReg(ENG_A, R_FILTER, 0);
  loadProgram(ENG_B, PROG_READ_PINS, PROG_READ_PINS_LEN);
  writeReg(ENG_B, R_CLKDIV, 0);
  writeReg(ENG_B, R_WRAP, wrapReg(0, PROG_READ_PINS_WRAP_BOTTOM, PROG_READ_PINS_WRAP_TOP));
  writeReg(ENG_B, R_MISC, 0); writeReg(ENG_B, R_INCFG, 0);
  writeReg(ENG_B, R_CTRL, 1);
  Serial.println();
  Serial.println("==== GPIO 22 held LOW for 30 s: meter GPIO 22 and J4-10 (M16); chip pin 2 should read 0 ====");
  for (int t = 0; t < 30; t++) {
    uint16_t v = 0;
    for (int i = 0; i < 8; i++) v = readReg(ENG_B, R_RX);
    Serial.printf("  t=%2d s   chip pin 2 (SCL) = %d   pin 3 (SDA) = %d", t, (v >> 2) & 1, (v >> 3) & 1);
    Serial.println();
    delay(1000);
  }
  pinMode(ESP_SCL, INPUT);
  writeReg(ENG_B, R_CTRL, 0);
  Serial.println("==== hold done, GPIO 22 released ====");
}

// 'w': slow LED walk on the 74HC595: one output at a time, QA to QH, 0.7 s each, QA first, round twice, then all on, then all
// off. Each transfer also reports what came back on QH' (the byte shifted in one transfer earlier).
void ledWalk() {
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  writeReg(ENG_A, R_FILTER, 0);
  int clkdiv = (int)(CHIP_HZ / (6.0 * 100000) + 0.5) - 1;
  loadProgram(ENG_A, PROG_SPI_MASTER, PROG_SPI_MASTER_LEN);
  writeReg(ENG_A, R_CLKDIV, clkdiv);
  writeReg(ENG_A, R_WRAP, wrapReg(0, PROG_SPI_MASTER_WRAP_BOTTOM, PROG_SPI_MASTER_WRAP_TOP));
  writeReg(ENG_A, R_OUTCFG, SPI_MOSI_ENG | (1 << 5) | (SPI_SCK_ENG << 10));
  writeReg(ENG_A, R_MISC, 4 | (SPI_SCK_ENG << 3) | (1 << 8) | (1 << 10));
  writeReg(ENG_A, R_INCFG, SPI_MISO_ENG);
  writeReg(ENG_A, R_CTRL, 1); delay(5);
  Serial.println();
  Serial.println("==== 74HC595 LED walk: QA (pin 15) first, then QB..QH (pins 1-7), 0.7 s each, twice; then all on 2 s, then all off ====");
  int prev = -1;
  for (int round = 0; round < 2; round++)
    for (int i = 0; i < 8; i++) {
      int bit = 1 << i;                                              // MSB first: bit 7 is clocked in first and ends at QH, bit 0 at QA
      spiSelect(); int back = spiXfer(bit); spiDeselect();
      Serial.printf("  sent 0x%02X -> Q%c should be lit;  QH' returned 0x%02X%s", bit, 'A' + i, back,
                    (prev >= 0 && back != prev) ? "   (expected the previous byte)" : "");
      Serial.println();
      prev = bit;
      delay(700);
    }
  spiSelect(); spiXfer(0xFF); spiDeselect(); Serial.println("  all eight on"); delay(2000);
  spiSelect(); spiXfer(0x00); spiDeselect(); Serial.println("  all off");
  writeReg(ENG_A, R_CTRL, 0);
  Serial.println("==== LED walk done ====");
}

// 'a': I2C address scan ("what is on this bus?"). Engine A as the I2C master on the usual pins; for every address
// 0x08-0x77: START, the address byte with the write bit, STOP; the reply's ACK bit says whether something answered.
// The ESP32's own I2C stays off: the devices under test hang on the two wires with their pull-ups.
const char *i2cGuess(int a) {
  if (a >= 0x50 && a <= 0x57) return "EEPROM (24Cxx) or our UNO/ESP32 slave";
  if (a == 0x68) return "RTC (DS1307/DS3231) or MPU6050";
  if (a == 0x76 || a == 0x77) return "BMP280/BME280 pressure sensor";
  if (a == 0x27 || a == 0x3F) return "PCF8574 (LCD1602 backpack)";
  if (a >= 0x20 && a <= 0x27) return "PCF8574 / MCP23017 port expander";
  if (a == 0x3C || a == 0x3D) return "SSD1306 OLED";
  if (a == 0x48) return "ADS1115 / LM75 / PCF8591";
  if (a == 0x40) return "INA219 / HTU21D / PCA9685";
  if (a == 0x1E) return "HMC5883L compass";
  return "";
}
void i2cScan() {
  Wire.end(); pinMode(ESP_SDA, INPUT); pinMode(ESP_SCL, INPUT);
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  writeReg(ENG_A, R_FILTER, 0);
  int clkdiv = (int)(CHIP_HZ / (10.0 * 100000) + 0.5) - 1;                 // 100 kHz
  loadProgram(ENG_A, PROG_I2C_MASTER, PROG_I2C_MASTER_LEN);
  writeReg(ENG_A, R_CLKDIV, clkdiv);
  writeReg(ENG_A, R_WRAP, wrapReg(0, PROG_I2C_MASTER_WRAP_BOTTOM, PROG_I2C_MASTER_WRAP_TOP));
  writeReg(ENG_A, R_OUTCFG, I2C_SDA_ENG | (1 << 5) | (I2C_SDA_ENG << 10));
  writeReg(ENG_A, R_MISC, 1 | (I2C_SCL_ENG << 3) | (1 << 8) | (1 << 10) | (1 << 13));
  writeReg(ENG_A, R_INCFG, I2C_SDA_ENG);
  writeReg(ENG_A, R_CTRL, 1); delay(5);
  Serial.println();
  Serial.printf("==== I2C address scan at %.0f kHz on engine pins %d (SCL) / %d (SDA) ====", CHIP_HZ / (10.0 * (clkdiv + 1)) / 1000, I2C_SCL_ENG, I2C_SDA_ENG);
  Serial.println();
  int found = 0;
  for (int a = 0x08; a <= 0x77; a++) {
    i2cCmd(i2cWord(I2C_MASTER_START), false);
    int r = i2cSend(a << 1);
    i2cCmd(i2cWord(I2C_MASTER_STOP), false);
    if (r < 0) { Serial.println("  no reply from the engine: is the chip loaded and wired?"); break; }
    if ((r & 1) == 0) { found++; Serial.printf("  0x%02X answered   %s", a, i2cGuess(a)); Serial.println(); }
    else if ((r >> 1) != (a << 1)) { Serial.printf("  0x%02X: the address did not go out as sent (0x%02X): bus held low?", a, r >> 1); Serial.println(); }
  }
  Serial.printf("==== scan done: %d device%s ====", found, found == 1 ? "" : "s");
  Serial.println();
  writeReg(ENG_A, R_CTRL, 0);
}

// 'x': engine isolation. A hangs on a WAIT that is never met (measure_pulse on the pulse pin, which GPIO 17 holds
// low), B keeps pushing 7, 8, 9 meanwhile, then A is stopped, reloaded and restarted through the host alone and B's
// last word must still be waiting. On a three-engine chip, C runs the UART transmitter throughout.
void isolationTest() {
  errors = 0;
  int n = readReg(ENG_A, R_ID) & 15;
  Serial.println(); Serial.printf("==== isolation: A hung, the other %d working, A recovered alone ====", n - 1); Serial.println();
  Serial2.end(); pinMode(PIN_PULSE, OUTPUT); digitalWrite(PIN_PULSE, LOW);
  for (int e = 0; e < n; e++) writeReg(e, R_CTRL, 0);
  writeReg(ENG_A, R_FILTER, 0);
  loadProgram(ENG_A, PROG_MEASURE_PULSE, PROG_MEASURE_PULSE_LEN);
  writeReg(ENG_A, R_CLKDIV, 0); writeReg(ENG_A, R_WRAP, wrapReg(0, PROG_MEASURE_PULSE_WRAP_BOTTOM, PROG_MEASURE_PULSE_WRAP_TOP));
  writeReg(ENG_A, R_OUTCFG, 0); writeReg(ENG_A, R_MISC, 0); writeReg(ENG_A, R_INCFG, PULSE_PIN);
  loadProgram(ENG_B, PROG_PUSH_789, PROG_PUSH_789_LEN);
  writeReg(ENG_B, R_CLKDIV, 0); writeReg(ENG_B, R_WRAP, wrapReg(0, PROG_PUSH_789_WRAP_BOTTOM, PROG_PUSH_789_WRAP_TOP));
  writeReg(ENG_B, R_OUTCFG, 0); writeReg(ENG_B, R_MISC, 0); writeReg(ENG_B, R_INCFG, 0);
  if (n >= 3) {
    loadProgram(ENG_C, PROG_UART_TX, PROG_UART_TX_LEN);
    writeReg(ENG_C, R_CLKDIV, (int)(CHIP_HZ / (8.0 * 115200) + 0.5) - 1);
    writeReg(ENG_C, R_WRAP, wrapReg(0, PROG_UART_TX_WRAP_BOTTOM, PROG_UART_TX_WRAP_TOP));
    writeReg(ENG_C, R_OUTCFG, 0 | (1 << 5) | 0); writeReg(ENG_C, R_MISC, 1 | (0 << 3) | (1 << 8) | (1 << 10) | (1 << 11)); writeReg(ENG_C, R_INCFG, 0);
    Serial2.begin(115200, SERIAL_8N1, PIN_RX2, -1);
  }
  writeReg(ENG_A, R_CTRL, 1); delay(2);
  check("A hung on its first WAIT (STATUS pc 0, running)", (readReg(ENG_A, R_STATUS) >> 8) & 63, 1);
  writeReg(ENG_B, R_CTRL, 1); delay(2);
  check("B works while A hangs (word 1)", readReg(ENG_B, R_RX), 7);
  check("B works while A hangs (word 2)", readReg(ENG_B, R_RX), 8);
  if (n >= 3) {
    writeReg(ENG_C, R_CTRL, 1); delay(2);
    while (Serial2.available()) Serial2.read();
    writeReg(ENG_C, R_TX, 'C'); writeReg(ENG_C, R_TX, '!'); delay(20);
    String got; while (Serial2.available()) got += (char)Serial2.read();
    Serial.printf("  %-44s [%s]  %s", "C sent over UART while A hangs", got.c_str(), got == "C!" ? "ok" : "WRONG"); Serial.println();
    if (got != "C!") errors++;
  }
  check("A still hung (pc 0, running)", (readReg(ENG_A, R_STATUS) >> 8) & 63, 1);
  // recover A alone
  writeReg(ENG_A, R_CTRL, 0);
  loadProgram(ENG_A, PROG_PUSH_789, PROG_PUSH_789_LEN);
  writeReg(ENG_A, R_WRAP, wrapReg(0, PROG_PUSH_789_WRAP_BOTTOM, PROG_PUSH_789_WRAP_TOP)); writeReg(ENG_A, R_INCFG, 0);
  writeReg(ENG_A, R_CTRL, 1); delay(2);
  check("A recovered: pushes 7", readReg(ENG_A, R_RX), 7);
  check("B still running", (readReg(ENG_B, R_STATUS) >> 8) & 1, 1);
  check("B's word 3 intact", readReg(ENG_B, R_RX), 9);
  if (n >= 3) check("C still running", (readReg(ENG_C, R_STATUS) >> 8) & 1, 1);
  for (int e = 0; e < n; e++) writeReg(e, R_CTRL, 0);
  digitalWrite(PIN_PULSE, HIGH);
  Serial.println(); Serial.printf("==== isolation %s (%d problems) ====", errors ? "FAIL" : "PASS", errors); Serial.println();
}

// 'o': scope loop for I2C. For 60 s, every 20 ms: START, address 0x50 + W, pointer 3, one data byte 0xA5, STOP at
// 100 kHz. Trigger the scope on SDA falling (the START) with SCL on the other channel; the UNO or ESP32 slave acks.
void i2cScopeLoop(bool forever = false) {
  Wire.end(); pinMode(ESP_SDA, INPUT); pinMode(ESP_SCL, INPUT);
  writeReg(ENG_A, R_CTRL, 0); writeReg(ENG_B, R_CTRL, 0);
  writeReg(ENG_A, R_FILTER, 0);
  int clkdiv = (int)(CHIP_HZ / (10.0 * 100000) + 0.5) - 1;
  loadProgram(ENG_A, PROG_I2C_MASTER, PROG_I2C_MASTER_LEN);
  writeReg(ENG_A, R_CLKDIV, clkdiv);
  writeReg(ENG_A, R_WRAP, wrapReg(0, PROG_I2C_MASTER_WRAP_BOTTOM, PROG_I2C_MASTER_WRAP_TOP));
  writeReg(ENG_A, R_OUTCFG, I2C_SDA_ENG | (1 << 5) | (I2C_SDA_ENG << 10));
  writeReg(ENG_A, R_MISC, 1 | (I2C_SCL_ENG << 3) | (1 << 8) | (1 << 10) | (1 << 13));
  writeReg(ENG_A, R_INCFG, I2C_SDA_ENG);
  writeReg(ENG_A, R_CTRL, 1); delay(5);
  Serial.println();
  Serial.println(forever ? "==== I2C scope loop: running until any key; [START 0xA0 0x03 0xA5 STOP] at 100 kHz every 20 ms ====" : "==== I2C scope loop: 60 s of [START 0xA0 0x03 0xA5 STOP] at 100 kHz every 20 ms; trigger on SDA falling ====");
  int acked = 0, total = 0;
  for (int t = 0; t < 3000 || (forever && !Serial.available()); t++) {   // 'z': until any character arrives
    i2cCmd(i2cWord(I2C_MASTER_START), false);
    int r1 = i2cSend(0xA0), r2 = i2cSend(0x03), r3 = i2cSend(0xA5);
    i2cCmd(i2cWord(I2C_MASTER_STOP), false);
    total++; if (r1 >= 0 && (r1 & 1) == 0 && (r2 & 1) == 0 && (r3 & 1) == 0) acked++;
    if (t % 500 == 499 && (!forever || t % 5000 == 4999)) { Serial.printf("  %d transactions, %d fully acked", total, acked); Serial.println(); }
    delay(20);
  }
  writeReg(ENG_A, R_CTRL, 0);
  Serial.println("==== scope loop done ====");
}

void loop() {
  if (Serial.available()) { int c = Serial.read(); if (c == 'r') runAll(); else if (c == 'i') i2cTest(); else if (c == 'n') i2cTest(true); else if (c == 's') spiTest(); else if (c == 'q') irqHold(); else if (c == 'p') leadProbe(); else if (c == 'l') scopeLoop(); else if (c == 'b') i2cWireCheck(); else if (c == 'k') sclHoldLow(); else if (c == 'w') ledWalk(); else if (c == 'a') i2cScan(); else if (c == 'x') isolationTest(); else if (c == 'o') i2cScopeLoop(); else if (c == 'z') { i2cScopeLoop(true); while (Serial.available()) Serial.read(); } }
}
