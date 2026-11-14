// Arduino Nano + 0.95" I2C OLED (assumed SSD1306, 128x64, address 0x3C)
// Wiring: SDA -> A4, SCL -> A5 (the Nano's hardware I2C pins)
// Library needed: "U8g2" by olikraus (Library Manager)

#include <U8g2lib.h>
#include <Servo.h>
#include "table.h"
#include "findtable.h"

// Page-buffer mode (_1_) keeps RAM use low on the Nano's 2 KB.
// Args: rotation, reset. Hardware I2C uses A4/A5 automatically.
U8G2_SSD1306_128X64_NONAME_1_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

// Hardcoded tables: id, chairs, adjacent1, adjacent2, angle, accessible
table tables[] = {
    table(1, 6,  -1, -1, 180, true),
    table(2, 4,  -1, -1, 135, true),
    table(3, 6,  4, -1,  90, false),
    table(4, 2,  3,  5,  60, false),
    table(5, 2,  4,  6,  30, false),
    table(6, 4,  5, -1,   0, false),

};
const int NUM_TABLES = sizeof(tables) / sizeof(tables[0]);

// Servo signal on D9 (power the servo from a separate 5 V supply, shared GND)
const int SERVO_PIN = 9;
Servo servo;

const table* TableById(int id) {
    for (int i = 0; i < NUM_TABLES; ++i) {
        if (tables[i].Id() == id) return &tables[i];
    }
    return nullptr;
}

// Angle for the result: the table's angle, or the average for a pair.
int AngleFor(const TableResult& r) {
    int angle = TableById(r.first)->Angle();
    if (r.second != -1) {
        angle = (angle + TableById(r.second)->Angle()) / 2;
    }
    return angle;
}

void Show(const char* line1, const char* line2) {
    u8g2.firstPage();
    do {
        u8g2.setFont(u8g2_font_6x12_tr);
        u8g2.drawStr(0, 12, line1);
        u8g2.setFont(u8g2_font_ncenB14_tr);
        u8g2.drawStr(0, 44, line2);
    } while (u8g2.nextPage());
}

// Same logic the old setup() ran once, now run per group.
void Seat(int groupSize) {
    TableResult r = FindTable(groupSize, tables, NUM_TABLES);

    if (r.first != -1) {
        servo.write(AngleFor(r));
        AssignTables(r, tables, NUM_TABLES);  // mark as in use
    }

    char line1[20];
    char line2[20];
    snprintf(line1, sizeof(line1), "Group of %d", groupSize);
    if (r.first == -1) {
        snprintf(line2, sizeof(line2), "No table");
    } else if (r.second == -1) {
        snprintf(line2, sizeof(line2), "Table %d", r.first);
    } else {
        snprintf(line2, sizeof(line2), "Tables %d+%d", r.first, r.second);
    }
    Show(line1, line2);
    Serial.println(line2);  // laptop shows this as "Arduino: ..."
}

void setup() {
    Serial.begin(115200);  // must match finger_count.py
    Serial.setTimeout(50);
    u8g2.begin();
    servo.write(0);  // set before attach so it goes straight to 0, not 90
    servo.attach(SERVO_PIN);
    Show("Ready", "Show hand");
}

// Commands from finger_count.py, one per line:
//   P<n> seat a group of n   R free all tables + servo to 0   F<t> free table t
//   (C<n> = live count, ignored)
void loop() {
    if (!Serial.available()) return;
    char cmd = Serial.read();
    if (cmd == 'P') {
        int n = Serial.parseInt();
        if (n > 0) Seat(n);
    } else if (cmd == 'R') {
        for (int i = 0; i < NUM_TABLES; ++i) tables[i].Clear();
        servo.write(0);
        Show("Reset", "All free");
        Serial.println("All free");
    } else if (cmd == 'F') {
        int id = Serial.parseInt();
        for (int i = 0; i < NUM_TABLES; ++i) {
            if (tables[i].Id() == id) tables[i].Clear();
        }
        Serial.print("Freed ");
        Serial.println(id);
    }
}
