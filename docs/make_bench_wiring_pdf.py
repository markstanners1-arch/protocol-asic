"""Landscape A4 PDF of the bench wiring: one wire per row, FROM -> TO (-> AND). Big type for a monitor.
Run: python docs/make_bench_wiring_pdf.py docs/bench_wiring.pdf"""
import sys
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

out = sys.argv[1]
doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=14*mm, rightMargin=14*mm, topMargin=12*mm, bottomMargin=12*mm,
                        title="Bench wiring sheet", author="Mark Stanners + Claude")
ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=24, leading=28, spaceAfter=4, alignment=0)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=17, leading=21, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#1a3d6d"))
P  = ParagraphStyle("p", parent=ss["Normal"], fontSize=12.5, leading=16)
PB = ParagraphStyle("pb", parent=P, fontName="Helvetica-Bold")
C  = ParagraphStyle("c", parent=P, fontSize=12.5, leading=15)
CB = ParagraphStyle("cb", parent=C, fontName="Helvetica-Bold", textColor=colors.white)
ARROW = "  ->  "

def wires(rows, widths=(70, 70, 58, 72)):
    """rows of (from, to, and, what). Columns: FROM | TO | AND (third end, if any) | what the wire is."""
    head = ["FROM", "TO", "AND (third end)", "What it is"]
    data = [[Paragraph(h, CB) for h in head]] + [[Paragraph(str(c), C) for c in r] for r in rows]
    t = Table(data, colWidths=[w*mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3d6d")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef2f7")]),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#9aa7b8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t

s = []
s.append(Paragraph("Bench wiring sheet - protocol emulator on the MachXO3L kit (3 Nov 2026)", H1))
s.append(Paragraph("One wire per row: <b>FROM</b> one end <b>TO</b> the other, <b>AND</b> a third end where the wire has one (a pull-up, a second board). "
                   "Kit pins are written <b>J4-n (ball)</b>: n is the numbered hole on header J4, the ball name (K12...) is the FPGA's own label printed beside it, "
                   "the same connection under a second name, for checking by continuity. <b>Go by the hole number</b>: the ball letters H and M (H16 = hole 25, M16 = hole 10) are easy to misread. <b>Engine pin</b> numbers (0-19) are what the chip's programs call that pin. "
                   "Everything is <b>3.3 V logic</b> (FPGA and ESP32 pins are not 5 V tolerant); one common ground between every board.", P))

s.append(Paragraph("1. Core: kit to ESP32 host. Fit these eight first, then rerun.ps1 (command r): ID reads 0x0022, 0 problems.", H2))
s.append(wires([
    ["J4-3 (K12)", "ESP32 GPIO 5", "", "CS, host SPI"],
    ["J4-5 (M14)", "ESP32 GPIO 23", "", "MOSI, host SPI"],
    ["J4-7 (L14)", "ESP32 GPIO 19", "", "MISO, host SPI"],
    ["J4-9 (M15)", "ESP32 GPIO 18", "", "SCK, host SPI"],
    ["J4-11 (GND)", "ESP32 GND", "every other board's GND", "common ground"],
    ["J4-4 (K13)", "ESP32 GPIO 4", "", "IRQ: high while any engine has data"],
    ["J4-6 (N14)", "ESP32 GPIO 16", "", "engine pin 0: engine A's UART out, into ESP32 Serial2 RX"],
    ["J4-26 (G15)", "ESP32 GPIO 17", "", "engine pin 15: the ESP32 sends test pulses into the chip (glitch filter)"],
]))
s.append(Spacer(1, 4))
s.append(Paragraph("J4-1 and J4-2 are the kit's 3.3 V (printed IO1, the bank supply, not a ball name): use for pull-ups only, never join them to the ESP32's 3.3 V. "
                   "Kit: <b>bash fpga/machxo3/build.sh load</b> (volatile SRAM, never the NVCM). ESP32 (the scripts find its port themselves): <b>esp32\\upload_and_watch.ps1 -Sketch chip_test</b>.", P))

s.append(PageBreak())
s.append(Paragraph("2. I2C bus (engine pins 2 = SCL, 3 = SDA). ESP32 as the slave: rerun.ps1 -Cmd i. UNO R3 as the slave: -Cmd n.", H2))
s.append(wires([
    ["J4-10 (M16)  SCL", "ESP32 GPIO 22  or  UNO A5", "5.1 k resistor to 3.3 V", "SCL, engine pin 2"],
    ["J4-13 (L15)  SDA", "ESP32 GPIO 21  or  UNO A4", "5.1 k resistor to 3.3 V", "SDA, engine pin 3"],
    ["UNO GND", "common ground", "", "only when the UNO is the slave; its own 5 V pull-ups are switched off by its sketch"],
    ["3.3 V for the two pull-ups", "J4-1  or  the UNO's 3.3 V pin", "", "one source, not both"],
]))
s.append(Spacer(1, 4))
s.append(Paragraph("<b>Never both slaves at once</b> (both answer at address 0x50): unplug the UNO's A4 and A5 for -Cmd i. UNO sketch: arduino/i2c_slave_nano on COM11.", P))

s.append(PageBreak())
s.append(Paragraph("3. SPI master to the 74HC595 (engine pins 4 to 7). rerun.ps1 -Cmd s.", H2))
s.append(wires([
    ["J4-14 (L16)", "595 pin 11  SRCLK", "", "SCK, engine pin 4"],
    ["J4-15 (K14)", "595 pin 14  SER", "", "MOSI, engine pin 5"],
    ["J4-16 (K16)", "595 pin 9  QH'", "", "MISO, engine pin 6: the 595's serial out comes back"],
    ["J4-17 (K15)", "595 pin 12  RCLK", "", "CS / latch, engine pin 7"],
    ["595 pin 16  VCC", "3.3 V", "", "power"],
    ["595 pin 8  GND", "common ground", "", "power"],
    ["595 pin 13  OE", "GND", "", "outputs enabled"],
    ["595 pin 10  SRCLR", "3.3 V", "", "not clearing"],
    ["595 pins 15, 1, 2, 3, 4, 5, 6, 7  (QA..QH)", "LED long leg", "LED short leg -> 330 ohm -> GND", "red, yellow or green only (white/blue stay dim at 3.3 V; the flat-topped ones never lit); the run ends on 0x55 so QA (pin 15) is high"],
]))
s.append(Spacer(1, 4))
s.append(Paragraph("Before the rebuild the LEDs stayed dark with the chip side proven good: meter pins 16, 8, 13, 10 first, then pin 15 after a run, then the QH' lead.", P))

s.append(PageBreak())
s.append(Paragraph("4. Every J4 hole the chip uses (for anything new)", H2))
head = ["J4 holes", "Balls", "Engine pins", "Direction"]
rows = [["6, 8, 10, 13, 14, 15, 16, 17", "N14, N16, M16, L15, L16, K14, K16, K15", "0, 1, 2, 3, 4, 5, 6, 7", "in and out (open drain able)"],
        ["18, 19, 20", "J14, H14, J15", "8, 9, 10", "out only"],
        ["23, 24, 25", "J16, H15, H16", "11, 12, 13", "out only"],
        ["26, 27, 28, 29, 30", "G15, G16, F15, F16, E15", "15, 16, 17, 18, 19", "in only"],
        ["1, 2", "3.3 V", "", ""],
        ["11, 12", "GND", "", ""]]
data = [[Paragraph(h, CB) for h in head]] + [[Paragraph(c, C) for c in r] for r in rows]
t = Table(data, colWidths=[62*mm, 90*mm, 58*mm, 60*mm], repeatRows=1)
t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3d6d")),
                       ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef2f7")]),
                       ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#9aa7b8")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                       ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
s.append(t)
s.append(Spacer(1, 4))
s.append(Paragraph("Holes and balls pair up in order: hole 6 is ball N14 (engine pin 0), hole 8 is N16 (pin 1), and so on along each row. "
                   "Kit LEDs: P16 lights for IRQ, N15 is the heartbeat (they light when driven low).", P))
s.append(Paragraph("<b>Cyclone IV board</b> (black EP4CE6E22C8N core board): everything on the right-hand header, pins 38-72, both bank jumpers at 3.3. CS 38, SCK 39, MOSI 42, MISO 43, IRQ 44 to the same ESP32 GPIOs as section 1; engine pin 0 = 46 (to GPIO 16), pins 1-7 = 49 50 51 52 53 54 55 (I2C SCL 50 / SDA 51; SPI 52-55), pins 8-13 = 58 59 60 64 65 66, pin 15 = 67 (from GPIO 17), 16-19 = 68-71. Clock 50 MHz on pin 24, LEDs 1 (IRQ) and 2 (heartbeat). Needs a USB Blaster on the JTAG header (ordered 3 Nov, due 5-6 Nov): bash fpga/cyclone4/build.sh load. Sketch: CHIP_HZ = 50e6. This board runs three engines (ID 0x0023); the kit two.", P))
s.append(Paragraph("If it doesn't answer: esp32 rerun.ps1 -Cmd p (lead probe: a FLOATING pin = lead open or wrong hole; ID 0x0000 with MISO driven = CS/SCK/MOSI not arriving; 0xFFFF = MISO open), -Cmd q (IRQ held high 15 s), -Cmd b (I2C wire check: names the chip pin each I2C lead reaches), -Cmd k (GPIO 22 held low 30 s to meter), -Cmd l (repeating ID reads for the oscilloscope), -Cmd y (keypad: names every key pressed; every key 'pressed' = row pull-ups not reaching J4-27..30), -Cmd e (live level of engine pins 15-19 for 30 s, a line on every change: a row with its 10 k in place reads 1). Writes working but reads all zero = MISO lead's J4 end in a hole held low (11/12 GND, 18-25 driven low). The kit forgets its build on any power blip: reload with bash fpga/machxo3/build.sh load.", P))
s.append(Paragraph("Order of work after replugging", H2))
s.append(Paragraph("1. Section 1 only. Load the kit, upload the sketch, rerun.ps1 (command r): ID 0x0022, 0 problems.&nbsp;&nbsp; "
                   "2. Add section 2: rerun.ps1 -Cmd i (ESP32 slave) or -Cmd n (UNO slave).&nbsp;&nbsp; "
                   "3. Add section 3: rerun.ps1 -Cmd s.&nbsp;&nbsp; 4. Keypad: section 6 (595 leads out), rerun.ps1 -Cmd y.", PB))
s.append(PageBreak())
s.append(Paragraph("6. Keypad (rerun.ps1 -Cmd y), IR receiver and ultrasonic: the Elegoo kit parts (4 Nov 2026)", H2))
s.append(Paragraph("Keypad tail, keys facing you and the tail at the bottom, pin 1 on the left: pins 1-4 are the <b>rows</b> top to bottom, 5-8 the <b>columns</b> left to right. "
                   "The chip pulls one column low at a time and reads the rows, so each row needs a 10 k pull-up. The 595 shares J4-14 to 17: unplug its four leads first.", P))
s.append(wires([
    ["keypad pin 1  (row 1: 1 2 3 A)", "J4-27 (G16)", "10 k resistor to J4-1 (3.3 V)", "row 1, engine pin 16"],
    ["keypad pin 2  (row 2: 4 5 6 B)", "J4-28 (F15)", "10 k resistor to J4-1", "row 2, engine pin 17"],
    ["keypad pin 3  (row 3: 7 8 9 C)", "J4-29 (F16)", "10 k resistor to J4-1", "row 3, engine pin 18"],
    ["keypad pin 4  (row 4: * 0 # D)", "J4-30 (E15)", "10 k resistor to J4-1", "row 4, engine pin 19"],
    ["keypad pin 5  (column 1: 1 4 7 *)", "J4-14 (L16)", "", "column 1, engine pin 4"],
    ["keypad pin 6  (column 2: 2 5 8 0)", "J4-15 (K14)", "", "column 2, engine pin 5"],
    ["keypad pin 7  (column 3: 3 6 9 #)", "J4-16 (K16)", "", "column 3, engine pin 6"],
    ["keypad pin 8  (column 4: A B C D)", "J4-17 (K15)", "", "column 4, engine pin 7"],
]))
s.append(Spacer(1, 4))
s.append(Paragraph("The sketch names each key and prints the raw map. Every key mirrored (1 reads as *) = the tail is numbered the other way: swap the two groups of four. "
                   "A key that never shows = its row or column lead.", P))
s.append(Paragraph("IR receiver (KY-022, 3.3 V) and ultrasonic HC-SR04 (5 V part, echo divided down): one at a time, they share J4-8. Programs to follow.", PB))
s.append(wires([
    ["IR module S (signal)", "J4-8 (N16)", "", "engine pin 1: idles high, pulses low under the 38 kHz bursts"],
    ["IR module + (VCC)", "J4-1 (3.3 V)", "", "power"],
    ["IR module - (GND)", "common ground", "", "power"],
    ["HC-SR04 VCC", "ESP32 5 V pin (VIN)", "", "5 V power"],
    ["HC-SR04 GND", "common ground", "", "power"],
    ["HC-SR04 Trig", "J4-18 (J14)", "", "engine pin 8 (out only): the 10 us trigger; 3.3 V is enough"],
    ["HC-SR04 Echo", "1 k resistor", "other end to J4-8 (N16) and a 2 k resistor to GND", "echo (5 V) divided to 3.3 V, engine pin 1; 58 us per cm"],
]))
doc.build(s)
print("wrote", out)
