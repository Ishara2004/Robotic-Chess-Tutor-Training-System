/* =====================================================================
   Chess Robotic Tutor and Training System
   Subsystem : CHESS BOARD  (64 reed switches + 64 NeoPixels)
   MCU       : Arduino MEGA 2560
   Board ID  : MEGA_CHESSBOARD_V1
   Link      : USB-CDC Serial, 115200 baud, ASCII line protocol (\n terminated)
   See       : BLUEPRINT.md section 7 (Communication Protocol) and
               section 6 (Electrical Design) for the full wiring tables.
   =====================================================================

   RESPONSIBILITIES
   ----------------
   1. Continuously scan all 64 reed switches (via 4x MCP23017 I2C I/O
      expanders) and report every state change to the PC as it happens
      (autonomous event stream - this board is never "commanded" to read,
      it just always reports).
   2. Receive lighting commands from the PC and drive the 64-pixel
      NeoPixel matrix accordingly (legal-move hints, capture squares,
      checkmate celebration).

   This board does NOT know anything about chess rules - it only knows
   "square name -> physical switch index" and "square name -> physical
   pixel index" via the serpentine wiring table below, copied verbatim
   from the original hardware design notes.
   ===================================================================== */

#include <Wire.h>

// ---- MCP23017 library --------------------------------------------------
// Using the classic Adafruit_MCP23017 library. If you are using the newer
// Adafruit BusIO-based library, the header is "Adafruit_MCP23X17.h" and the
// class is "Adafruit_MCP23X17" - the begin()/pinMode()/pullUp()/digitalRead()
// calls used below are functionally identical, just swap the two lines.
#include <Adafruit_MCP23017.h>
#include <Adafruit_NeoPixel.h>

#define STRIP_PIN_7 7
#define MOOD_PIN_8 8
#define STRIP_PIXELS 60

Adafruit_NeoPixel stripPixels(STRIP_PIXELS, STRIP_PIN_7, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel moodStrip(STRIP_PIXELS, MOOD_PIN_8, NEO_GRB + NEO_KHZ800);

// ====================== CONFIGURATION (verify on your build) ===========
#define NUM_SQUARES        64
#define NEOPIXEL_PIN       6        // free Mega digital pin -> NeoPixel DIN (through ~330ohm resistor)
#define MCP_COUNT          4
#define POLL_INTERVAL_MS   50       // reed-switch scan period (33Hz - plenty for a turn-based game)
#define LED_BRIGHTNESS     200      // 0-255, tune to your power budget (64 LEDs @ full draw ~3.8A)

// MCP23017 I2C addresses are set by tying A0/A1/A2 pins on each chip:
//   chip 0 -> A2=GND A1=GND A0=GND  -> 0x20  (squares index 0-15)
//   chip 1 -> A2=GND A1=GND A0=VCC  -> 0x21  (squares index 16-31)
//   chip 2 -> A2=GND A1=VCC A0=GND  -> 0x22  (squares index 32-47)
//   chip 3 -> A2=GND A1=VCC A0=VCC  -> 0x23  (squares index 48-63)
// The Adafruit_MCP23017 library's begin(n) takes the 0-7 address OFFSET,
// not the raw 7-bit address, so begin(0..3) is correct here.

// Colour palette (RGB - the NeoPixel library re-orders internally for GRB strips)
struct RGB { uint8_t r, g, b; };
static const RGB COLOR_OFF   = {0, 0, 0};
static const RGB COLOR_BLUE  = {0, 150, 255};   // legal "can move through / land on" squares
static const RGB COLOR_RED   = {255, 0, 0};     // legal "can capture / cross" squares
static const RGB COLOR_GREEN = {0, 255, 0};     // checkmate celebration (whole board)

// ====================== Serpentine wiring map ===========================
// Physical index -> algebraic square, exactly as the reed switches and
// NeoPixels are wired (row-by-row, alternating direction = boustrophedon).
// This table is the single source of truth for "index <-> square name"
// on THIS board. Do not change unless you rewire the matrix.
const char* squares[NUM_SQUARES] = {
  "h1","h2","h3","h4","h5","h6","h7","h8",
  "g8","g7","g6","g5","g4","g3","g2","g1",
  "f1","f2","f3","f4","f5","f6","f7","f8",
  "e8","e7","e6","e5","e4","e3","e2","e1",
  "d1","d2","d3","d4","d5","d6","d7","d8",
  "c8","c7","c6","c5","c4","c3","c2","c1",
  "b1","b2","b3","b4","b5","b6","b7","b8",
  "a8","a7","a6","a5","a4","a3","a2","a1"
};

Adafruit_MCP23017 mcp[MCP_COUNT];
Adafruit_NeoPixel strip(NUM_SQUARES, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

bool lastState[NUM_SQUARES];   // true = CLOSED (reed switch sees a magnet = square occupied)
bool firstScan = true;
unsigned long lastPoll = 0;
String inputBuffer = "";

// ----------------------------------------------------------------------
int squareToIndex(const String &sq) {
  for (int i = 0; i < NUM_SQUARES; i++) {
    if (sq.equalsIgnoreCase(squares[i])) return i;
  }
  return -1;
}

void setPixel(int idx, const RGB &c) {
  if (idx < 0 || idx >= NUM_SQUARES) return;
  strip.setPixelColor(idx, strip.Color(c.r, c.g, c.b));
}

void clearAllLeds() {
  strip.clear();
  strip.show();
}

void allGreen() {
  for (int i = 0; i < NUM_SQUARES; i++) setPixel(i, COLOR_GREEN);
  strip.show();
}

// closed = true means the reed switch is triggered (square occupied)
bool readSwitch(int idx) {
  int mcpIdx = idx / 16;
  int pin    = idx % 16;
  // Internal pull-up enabled; reed switch pulls the pin LOW to GND when closed.
  return mcp[mcpIdx].digitalRead(pin) == LOW;
}

void scanSwitches() {
  for (int i = 0; i < NUM_SQUARES; i++) {
    bool closed = readSwitch(i);
    if (firstScan || closed != lastState[i]) {
      lastState[i] = closed;
      Serial.print("SQEVT:");
      Serial.print(squares[i]);
      Serial.println(closed ? ":CLOSED" : ":OPEN");
    }
  }
  firstScan = false;
}

void sendState() {
  // 64-bit occupancy snapshot, sent as 16 hex characters (useful at startup
  // or to verify a physical move actually completed correctly).
  uint64_t bits = 0;
  for (int i = 0; i < NUM_SQUARES; i++) if (lastState[i]) bits |= (1ULL << i);
  char buf[17];
  // Mega is AVR: %llX is not reliably supported by avr-libc's sprintf, so
  // build the hex string manually, 4 bits at a time, MSB first.
  for (int nib = 15; nib >= 0; nib--) {
    uint8_t v = (bits >> (nib * 4)) & 0xF;
    buf[15 - nib] = v < 10 ? ('0' + v) : ('A' + v - 10);
  }
  buf[16] = '\0';
  Serial.print("STATE:");
  Serial.println(buf);
}

void applyList(const String &csv, const RGB &color) {
  int start = 0;
  while (start < (int)csv.length()) {
    int comma = csv.indexOf(',', start);
    String tok = (comma == -1) ? csv.substring(start) : csv.substring(start, comma);
    tok.trim();
    if (tok.length() > 0) setPixel(squareToIndex(tok), color);
    if (comma == -1) break;
    start = comma + 1;
  }
}

void handleShowMoves(const String &args) {
  // Format: SHOWMOVES:<csv blue squares>:<csv red squares>  (either list may be empty)
  int sep = args.indexOf(':');
  String blueList = (sep >= 0) ? args.substring(0, sep) : args;
  String redList  = (sep >= 0) ? args.substring(sep + 1) : "";
  strip.clear();
  applyList(blueList, COLOR_BLUE);
  applyList(redList,  COLOR_RED);   // applied after blue so red wins on overlap
  strip.show();
}

void processCommand(String line) {
  line.trim();
  if (line == "CLEARLEDS") { 
    strip.clear(); 
    strip.show(); 
    Serial.println("ACK:CLEARLEDS"); 
  }
  else if (line == "WINGREEN") { 
    for(int i=0; i<NUM_SQUARES; i++) setPixel(i, COLOR_GREEN); 
    strip.show(); 
    Serial.println("ACK:WINGREEN"); 
  }
  else if (line.startsWith("SHOWMOVES:")) {
    int sep = line.indexOf(':', 10);
    String b = line.substring(10, sep);
    String r = line.substring(sep + 1);
    strip.clear();
    int s1 = 0; while(s1 < (int)b.length()) { int c = b.indexOf(',', s1); String t = (c==-1) ? b.substring(s1) : b.substring(s1, c); t.trim(); if(t.length()>0) setPixel(squareToIndex(t), COLOR_BLUE); s1 = (c==-1) ? b.length() : c+1; }
    int s2 = 0; while(s2 < (int)r.length()) { int c = r.indexOf(',', s2); String t = (c==-1) ? r.substring(s2) : r.substring(s2, c); t.trim(); if(t.length()>0) setPixel(squareToIndex(t), COLOR_RED); s2 = (c==-1) ? r.length() : c+1; }
    strip.show(); 
    Serial.println("ACK:SHOWMOVES");
  }
  else if (line.startsWith("COLOR_")) {
    String c = line.substring(6);
    if (c == "BLUE") setMoodColor(0, 0, 255);
    else if (c == "RED") { setMoodColor(255, 0, 0); delay(1000); setMoodColor(255, 255, 255); }
    else if (c == "GREEN") { setMoodColor(0, 255, 0); delay(1000); setMoodColor(255, 255, 255); }
    else if (c == "WHITE") setMoodColor(255, 255, 255);
    Serial.println("ACK:COLOR");
  }
}



void setup() {
  Serial.begin(115200);
 
  Wire.begin();
  // පහත පේළි 2 අලුතින් එකතු කරන්න
  Wire.setWireTimeout(3000, true); // මයික්‍රෝ තත්පර 3000කට පසු I2C හිරවුණොත් ස්වයංක්‍රීයව රීසෙට් කරන්න
  Wire.clearWireTimeoutFlag();

  for (int i = 0; i < MCP_COUNT; i++) {
    mcp[i].begin(i);                 // address offset 0..3 -> 0x20..0x23
    for (int p = 0; p < 16; p++) {
      mcp[i].pinMode(p, INPUT);
      mcp[i].pullUp(p, HIGH);        // enable ~100k internal pull-up
    }
  }

  strip.begin();
  strip.setBrightness(LED_BRIGHTNESS);
  strip.clear();
  strip.show();

  for (int i = 0; i < NUM_SQUARES; i++) lastState[i] = false;

  Serial.println("READY:MEGA_CHESSBOARD_V1");

  stripPixels.begin();
  moodStrip.begin();

  for(int i = 0; i < STRIP_PIXELS; i++) {
    stripPixels.setPixelColor(i, stripPixels.Color(173, 216, 230));
  }
  stripPixels.show();

  for(int i = 0; i < STRIP_PIXELS; i++) {
    moodStrip.setPixelColor(i, moodStrip.Color(255, 255, 255));
  }
  moodStrip.show();
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      processCommand(inputBuffer);
      inputBuffer = "";
    } else if (c != '\r') {
      inputBuffer += c;
    }
  }

  unsigned long now = millis();
  if (now - lastPoll >= POLL_INTERVAL_MS) {
    lastPoll = now;
    scanSwitches();
  }
}

void setMoodColor(int r, int g, int b) {
  for(int i = 0; i < STRIP_PIXELS; i++) {
    moodStrip.setPixelColor(i, moodStrip.Color(r, g, b));
  }
  moodStrip.show();
}