# Smart Table Guide

UT Makeathon 2026. A guest holds up fingers for their party size, the laptop camera counts them, and a servo arrow points the group to the best free table.

## Laptop (finger counting)

```
cd laptop
pip install -r requirements.txt
python finger_count.py                 # finds the Arduino's USB port itself (prints only if none)
python finger_count.py --port COM5     # or pick the port yourself
python finger_count.py --camera 1      # if the wrong camera opens
```

The hand model (~8 MB) downloads on the first run. Hold a count steady for 2 seconds to confirm it.
Keys in the video window: `q` quit, `r` reset all tables, `1`-`6` mark that table free.
On macOS, allow your terminal app under System Settings > Privacy & Security > Camera.

Tables stay taken while the script runs. Launching it restarts the Nano, so every session starts with all tables free, and quitting sends the servo back to 0°.

## Arduino Nano (seating logic, servo, OLED)

Open `firmware/table_finder/table_finder.ino` in the Arduino IDE, install **U8g2** (Library Manager), and upload.
Clone Nanos may need Processor set to "ATmega328P (Old Bootloader)".

Wiring: OLED SDA to A4, SCL to A5, VCC to 5V, GND to GND. Servo signal to D9; power it from a separate 5 V supply with a shared GND (from the Nano's 5V pin it can brown out the USB link).

Tables are set in `tables[]` in `table_finder.ino` (id, chairs, adjacent1, adjacent2, angle, accessible). The finder picks the free table, or pair of adjacent tables, with the fewest extra chairs; a single table wins a tie. A pair points the servo halfway between the two.

Serial commands (115200 baud, Newline), also usable from the Serial Monitor:
`P2` seats a party of 2, `F1` frees table 1, `R` frees all tables and returns the servo to 0°.
`O` lists which tables are in use, `M3` marks table 3 in use.
Close the Serial Monitor before running the Python script, since only one program can use the port.
