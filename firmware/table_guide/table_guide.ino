// Smart Table Guide - Arduino Nano firmware
// Holds table state, runs the seating algorithm, drives the servo arrow + OLED.
//
// Serial commands (115200 baud, newline-terminated) - you can type these in the
// Serial Monitor to test before the Python side is ready:
//   C3  -> candidate party of 3 (shows "Party of 3?")
//   P3  -> confirmed party of 3: assign a table, point the arrow
//   F5  -> mark table 5 free (same as pressing table 5's staff button)
//   R   -> reset: all tables free
//   S   -> print every table's status
//
// Wiring (Nano):
//   OLED  VCC->5V  GND->GND  SDA->A4  SCL->A5
//   Servo red->5V  brown/black->GND  orange/yellow (signal)->D9
//   Staff buttons (optional, add later): one leg to D2..D7, other leg to GND
//   Table LEDs (optional, add later): D10, D11, D12, D13, A0, A1 -> 220-330 ohm resistor -> LED -> GND
//
// Libraries: Servo (built in), Adafruit SSD1306 + Adafruit GFX (Library Manager)

#include <Wire.h>
#include <Servo.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

Adafruit_SSD1306 oled(128, 64, &Wire, -1);
Servo arrow;

struct Table {
  uint8_t seats;
  uint8_t angle;          // where the arrow points for this table
  bool isFree;
  unsigned long freedAt;  // for tie-breaks: free longest gets picked first
  uint8_t btnPin;
  uint8_t ledPin;
};

// Edit this to match the model cafe layout.
Table tables[] = {
  {2,  15, true, 0, 2, 10},
  {2,  45, true, 0, 3, 11},
  {4,  75, true, 0, 4, 12},
  {4, 105, true, 0, 5, 13},
  {6, 135, true, 0, 6, A0},
  {6, 165, true, 0, 7, A1},
};
const uint8_t N = sizeof(tables) / sizeof(tables[0]);

const uint8_t SERVO_PIN = 9;
const uint8_t CENTER = 90;
const unsigned long IDLE_MS = 10000;   // arrow returns to center after this
const unsigned long DEBOUNCE_MS = 30;

unsigned long lastAction = 0;
bool idle = true;
bool btnState[N];
unsigned long btnChangedAt[N];
String line;

// ---------- display ----------
void show(const char* small, const String& big) {
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(1);
  oled.setCursor(0, 0);
  oled.print(small);
  oled.setTextSize(2);            // 10 characters per line at size 2
  oled.setCursor(0, 24);
  oled.print(big);
  oled.display();
}

void showWelcome() {
  show("Hold up fingers for", "party size");
}

// ---------- tables ----------
void setFree(uint8_t i, bool f) {
  tables[i].isFree = f;
  if (f) tables[i].freedAt = millis();
  digitalWrite(tables[i].ledPin, f ? HIGH : LOW);   // LED on = free
}

// Best fit: smallest free table that seats the party; tie -> free longest.
int pickTable(uint8_t party) {
  int best = -1;
  for (uint8_t i = 0; i < N; i++) {
    if (!tables[i].isFree || tables[i].seats < party) continue;
    if (best < 0 ||
        tables[i].seats < tables[best].seats ||
        (tables[i].seats == tables[best].seats && tables[i].freedAt < tables[best].freedAt)) {
      best = i;
    }
  }
  return best;
}

uint8_t largestTable() {
  uint8_t m = 0;
  for (uint8_t i = 0; i < N; i++) m = max(m, tables[i].seats);
  return m;
}

void seatParty(uint8_t party) {
  lastAction = millis();
  idle = false;

  if (party > largestTable()) {
    arrow.write(CENTER);
    show("Party too large", "See counter");
    Serial.println("W");
    return;
  }

  int t = pickTable(party);
  if (t < 0) {
    arrow.write(CENTER);
    show("All tables busy", "Wait a bit");
    Serial.println("W");
    return;
  }

  setFree(t, false);
  arrow.write(tables[t].angle);
  String msg = "Table " + String(t + 1);
  String top = "Party of " + String(party) + " ->";
  show(top.c_str(), msg);
  Serial.print("T");
  Serial.println(t + 1);
}

void printStatus() {
  for (uint8_t i = 0; i < N; i++) {
    Serial.print("Table ");
    Serial.print(i + 1);
    Serial.print(" seats ");
    Serial.print(tables[i].seats);
    Serial.println(tables[i].isFree ? " FREE" : " TAKEN");
  }
}

// ---------- input ----------
void handleLine(String s) {
  s.trim();
  if (s.length() == 0) return;
  char cmd = toupper(s.charAt(0));
  int n = s.substring(1).toInt();

  switch (cmd) {
    case 'C':
      if (n > 0) {
        String big = "Party of " + String(n);
        show("Hold steady...", big + "?");
        lastAction = millis();
        idle = false;
      }
      break;
    case 'P':
      if (n > 0) seatParty(n);
      break;
    case 'F':
      if (n >= 1 && n <= N) {
        setFree(n - 1, true);
        Serial.print("Freed ");
        Serial.println(n);
      }
      break;
    case 'R':
      for (uint8_t i = 0; i < N; i++) setFree(i, true);
      Serial.println("Reset");
      break;
    case 'S':
      printStatus();
      break;
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      handleLine(line);
      line = "";
    } else if (line.length() < 16) {
      line += c;
    }
  }
}

void readButtons() {
  for (uint8_t i = 0; i < N; i++) {
    bool pressed = digitalRead(tables[i].btnPin) == LOW;   // INPUT_PULLUP
    if (pressed != btnState[i] && millis() - btnChangedAt[i] > DEBOUNCE_MS) {
      btnState[i] = pressed;
      btnChangedAt[i] = millis();
      if (pressed) {
        setFree(i, true);
        Serial.print("Freed ");
        Serial.println(i + 1);
      }
    }
  }
}

// ---------- main ----------
void setup() {
  Serial.begin(115200);

  for (uint8_t i = 0; i < N; i++) {
    pinMode(tables[i].btnPin, INPUT_PULLUP);
    pinMode(tables[i].ledPin, OUTPUT);
    btnState[i] = false;
    btnChangedAt[i] = 0;
    setFree(i, true);
  }

  arrow.attach(SERVO_PIN);
  arrow.write(CENTER);

  // Most 0.96" I2C OLEDs are at 0x3C; try 0x3D if the screen stays blank.
  if (!oled.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED not found - check wiring/address");
  }
  showWelcome();
  Serial.println("Ready");
}

void loop() {
  readSerial();
  readButtons();

  if (!idle && millis() - lastAction > IDLE_MS) {
    arrow.write(CENTER);
    showWelcome();
    idle = true;
  }
}
