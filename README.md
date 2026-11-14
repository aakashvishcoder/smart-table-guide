# Smart Table Guide

UT Makeathon 2026. A guest holds up fingers for their party size, the laptop camera counts them, and a servo arrow points the group to the best free table.

## Laptop (finger counting)

```
cd laptop
pip install -r requirements.txt
python finger_count.py                 # test without the Arduino
python finger_count.py --port COM5     # Windows (Mac: --port /dev/tty.usbserial-XXXX)
```

The hand model (~8 MB) downloads on the first run. Hold a count steady for 2 seconds to confirm it.
Keys in the video window: `q` quit, `r` reset all tables, `1`-`6` mark that table free.

## Arduino Nano (seating logic, servo, OLED)

Open `firmware/table_guide/table_guide.ino` in the Arduino IDE, install **Adafruit SSD1306** and **Adafruit GFX**, and upload.
Clone Nanos may need Processor set to "ATmega328P (Old Bootloader)".

Wiring: OLED SDA to A4, SCL to A5, VCC to 5V, GND to GND. Servo signal to D9, red to 5V, brown to GND.

Test from the Serial Monitor (115200 baud, Newline): `P2` seats a party of 2, `F1` frees table 1, `S` prints status.
Close the Serial Monitor before running the Python script, since only one program can use the port.
