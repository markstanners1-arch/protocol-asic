// A classic Nano (ATmega328P) as an I2C slave for the chip's I2C master: the same register-pointer device as
// model/i2c_slave.py, address 0x50, 16 registers.
//   write: address+W, pointer, data... (into regs[pointer], pointer + 1 each)
//   read:  address+R, data from regs[pointer] (pointer + 1 each) until the master NAKs
// The AVR's I2C hardware is open drain and STRETCHES THE CLOCK while these handlers run, so this is the test of the
// master's stretch handling on real wires (the original ESP32's slave hardware cannot stretch).
// Wiring: A4 = SDA, A5 = SCL, GND to the common ground. Pull-ups stay on the bus at 3.3 V (5.1 k): the Nano's own
// pull-ups to 5 V are switched off below, so it only ever pulls the lines low. Power the Nano from its USB.
// Serial Monitor at 115200 shows every transaction.
#include <Wire.h>

const uint8_t ADDR = 0x50;
volatile uint8_t regs[16];
volatile uint8_t ptr = 0;
volatile uint16_t writes = 0, reads = 0;
volatile bool event = false;

void onReceive(int n) {
  bool first = true;
  while (Wire.available()) {
    uint8_t b = Wire.read();
    if (first) { ptr = b & 15; first = false; }
    else { regs[ptr] = b; ptr = (ptr + 1) & 15; writes++; }
  }
  event = true;
}

void onRequest() {                       // SCL is held low by the hardware until we answer: clock stretching
  uint8_t out[4];                        // called once per read transaction: queue 4 bytes (the master may take fewer)
  for (int i = 0; i < 4; i++) out[i] = regs[(ptr + i) & 15];
  Wire.write(out, 4);
  ptr = (ptr + 4) & 15;
  reads++;
  event = true;
}

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < 16; i++) regs[i] = 0;
  Wire.begin(ADDR);
  digitalWrite(SDA, LOW);                // Wire.begin turned on the internal pull-ups to 5 V: off again, the bus
  digitalWrite(SCL, LOW);                // is pulled up to 3.3 V by its own resistors
  Wire.onReceive(onReceive);
  Wire.onRequest(onRequest);
  Serial.println("Nano I2C slave at 0x50, 16 registers, pull-ups off");
}

void loop() {
  if (event) {
    event = false;
    delay(20);                           // let the transaction finish before printing
    Serial.print("regs:");
    for (int i = 0; i < 16; i++) { Serial.print(' '); Serial.print(regs[i], HEX); }
    Serial.print("  ptr "); Serial.print(ptr); Serial.print("  writes "); Serial.print(writes);
    Serial.print("  reads "); Serial.println(reads);
  }
}
