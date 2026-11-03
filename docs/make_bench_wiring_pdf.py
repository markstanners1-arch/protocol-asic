"""Landscape A4 PDF of docs/bench_wiring.md, big type for a monitor. Run: python make_wiring_pdf.py <out.pdf>"""
import sys
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

out = sys.argv[1]
doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=14*mm, rightMargin=14*mm, topMargin=12*mm, bottomMargin=12*mm,
                        title="Bench wiring sheet", author="Mark Stanners + Claude")
ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=24, leading=28, spaceAfter=4, alignment=0)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=17, leading=21, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#1a3d6d"))
P  = ParagraphStyle("p", parent=ss["Normal"], fontSize=12.5, leading=16)
PB = ParagraphStyle("pb", parent=P, fontName="Helvetica-Bold")
C  = ParagraphStyle("c", parent=P, fontSize=12, leading=15)
CB = ParagraphStyle("cb", parent=C, fontName="Helvetica-Bold", textColor=colors.white)

def tbl(rows, widths):
    data = [[Paragraph(str(c), CB) for c in rows[0]]] + [[Paragraph(str(c), C) for c in r] for r in rows[1:]]
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
s.append(Paragraph("Everything is <b>3.3 V logic</b>: the FPGA and ESP32 pins are not 5 V tolerant. One common ground between every board. "
                   "Check each lead by continuity to the labelled pad before blaming the design (programs/read_pins.asm shows what the chip sees).", P))
s.append(Spacer(1, 3))
s.append(Paragraph("<b>Column key.</b> <b>J4 hole</b> = the numbered hole on the kit's header J4 where the lead goes. "
                   "<b>Ball</b> = the FPGA's own name for that same connection (printed beside the hole, used in the constraints file): same wire, second name, for checking. "
                   "<b>Engine pin</b> = the number the chip's programs use for that pin (0-19). "
                   "<b>Signal</b> = what the wire carries (CS, SCK, SCL...); the far end is in the next column (ESP32 GPIO, UNO pin or 74HC595 pin).", P))

s.append(Paragraph("1. Core: kit header J4 to the ESP32 host - fit these first, then run rerun.ps1 (command r). ID register should read 0x0022.", H2))
s.append(tbl([["J4 hole", "Ball", "Chip signal", "ESP32 GPIO", "Notes"],
              ["3", "K12", "CS", "5", "host SPI"],
              ["5", "M14", "MOSI", "23", "host SPI"],
              ["7", "L14", "MISO", "19", "host SPI"],
              ["9", "M15", "SCK", "18", "host SPI"],
              ["11", "GND", "GND", "GND", "common ground"],
              ["4", "K13", "IRQ", "4", "high while any engine has data"],
              ["6", "N14", "engine pin 0", "16", "engine A's UART out, ESP32 Serial2 RX"],
              ["26", "G15", "engine pin 15", "17", "glitch filter test: the ESP32 sends pulses into the chip"]],
             [22, 18, 36, 28, 150]))
s.append(Spacer(1, 4))
s.append(Paragraph("J4 holes 1 and 2 are the kit's 3.3 V: fine for pull-ups, never joined to the ESP32's 3.3 V. "
                   "Kit: <b>bash fpga/machxo3/build.sh load</b> (volatile SRAM only, never the NVCM). ESP32 on COM7: <b>esp32\\upload_and_watch.ps1 -Sketch chip_test</b>.", P))

s.append(PageBreak())
s.append(Paragraph("2. I2C: engine pins 2 and 3 (rerun.ps1 -Cmd i with the ESP32 as slave, -Cmd n with the UNO R3)", H2))
s.append(tbl([["J4 hole", "Ball", "Engine pin", "Bus", "ESP32 as slave (-Cmd i)", "UNO R3 as slave (-Cmd n)"],
              ["10", "M16", "2", "SCL", "GPIO 22", "A5"],
              ["13", "L15", "3", "SDA", "GPIO 21", "A4"]],
             [22, 18, 28, 20, 80, 80]))
s.append(Spacer(1, 4))
s.append(Paragraph("One 5.1 k pull-up from SCL to 3.3 V and one from SDA to 3.3 V (J4-1 or the UNO's 3.3 V pin, one source only). UNO ground to the common ground; "
                   "the UNO sketch (arduino/i2c_slave_nano, COM11) switches its own 5 V pull-ups off. <b>Never both slaves at once</b> (both answer at 0x50): unplug A4/A5 for -Cmd i.", P))
s.append(Spacer(1, 6))

s.append(Paragraph("3. SPI master to the 74HC595: engine pins 4 to 7 (rerun.ps1 -Cmd s)", H2))
s.append(tbl([["J4 hole", "Ball", "Engine pin", "Signal", "74HC595 pin"],
              ["14", "L16", "4", "SCK", "11 SRCLK"],
              ["15", "K14", "5", "MOSI", "14 SER"],
              ["16", "K16", "6", "MISO", "9 QH' (serial out)"],
              ["17", "K15", "7", "CS / latch", "12 RCLK"]],
             [22, 18, 28, 32, 60]))
s.append(Spacer(1, 4))
s.append(Paragraph("595 power: pin 16 VCC = 3.3 V, pin 8 GND, pin 13 OE = GND (outputs on), pin 10 SRCLR = 3.3 V (not clearing). "
                   "LEDs on QA..QH = pins 15, 1, 2, 3, 4, 5, 6, 7, each through about 330 ohms to ground (long leg to the 595). "
                   "Every transfer returns the previous byte through QH'; the run ends on 0x55, so QA (pin 15) = high. "
                   "Before the rebuild the LEDs stayed dark with the chip side proven good: meter the four power pins first, then QA after a run, then the QH' lead.", P))

s.append(PageBreak())
s.append(Paragraph("4. The whole of J4 (for anything new)", H2))
s.append(tbl([["J4 holes", "Balls", "Chip pins", "Engine pins", "Direction"],
              ["6, 8, 10, 13, 14, 15, 16, 17", "N14 N16 M16 L15 L16 K14 K16 K15", "uio[0..7]", "0-7", "in and out (open drain able)"],
              ["18, 19, 20", "J14 H14 J15", "uo_out[2..4]", "8-10", "out only"],
              ["23, 24, 25", "J16 H15 H16", "uo_out[5..7]", "11-13", "out only"],
              ["26, 27, 28, 29, 30", "G15 G16 F15 F16 E15", "ui_in[3..7]", "15-19", "in only"],
              ["1, 2", "3.3 V", "", "", ""],
              ["11, 12", "GND", "", "", ""]],
             [62, 78, 36, 30, 60]))
s.append(Spacer(1, 4))
s.append(Paragraph("Kit LEDs: P16 lights for IRQ, N15 is the heartbeat (they light when driven low). "
                   "<b>Cyclone IV EP4CE6</b> (arrived 3 Nov): pin locations still to be chosen in fpga/cyclone4/chip_c4.qsf; the same eight leads of section 1 move across; "
                   "set CHIP_HZ = 50e6 in the sketch (SPI goes to 4 MHz).", P))

s.append(Paragraph("Order of work after replugging", H2))
s.append(Paragraph("1. Section 1 only. Load the kit, upload the sketch, rerun.ps1 (command r): ID 0x0022, 0 problems.&nbsp;&nbsp; "
                   "2. Add section 2: rerun.ps1 -Cmd i (ESP32 slave) or -Cmd n (UNO slave).&nbsp;&nbsp; "
                   "3. Add section 3: rerun.ps1 -Cmd s.", PB))
doc.build(s)
print("wrote", out)
