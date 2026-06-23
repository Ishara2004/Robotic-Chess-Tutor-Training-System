/* =====================================================================
   Chess Robotic Tutor and Training System
   Subsystem : X-Y-Z GANTRY + GRIPPER
   MCU       : Arduino UNO
   Board ID  : UNO_GANTRY_V1
   Link      : USB-CDC Serial, 115200 baud, ASCII line protocol (\n terminated)
   See       : BLUEPRINT.md section 6 (Electrical) and 7 (Protocol) for the
               full wiring diagram and the rationale behind every constant
               in the CALIBRATION block below.
   =====================================================================

   DESIGN NOTE - SYNCHRONOUS PROTOCOL
   -----------------------------------
   Every motion command BLOCKS until the motion is physically complete,
   then sends one ACK line. The PC always waits for that ACK before
   sending the next command. This is a deliberate simplification: chess
   is turn-based and not time-critical, so we trade theoretical
   parallelism for a vastly simpler and more reliable state machine.

   AXIS LAYOUT
   -----------
   - X axis (board RANKS, 1-8) is driven by TWO motors (X1, X2), one on
     each side of the gantry beam, stepped in perfect lockstep to keep
     the beam square. They are given identical targets every time.
   - Y axis (board FILES, a-h) is driven by ONE motor on the moving carriage.
   - Z axis (vertical) uses a T8 lead screw + ONE motor + the single
     horizontal limit switch for homing.
   - The MG995 gripper servo opens/closes the jaw.
   ===================================================================== */

#include <AccelStepper.h>
#include <Servo.h>

// ============================ PIN MAP (CNC SHIELD V3) ===================================
#define X1_STEP_PIN   2
#define X1_DIR_PIN    5
#define X2_STEP_PIN   2     // Hardware Clone මගින් ක්‍රියාත්මක වේ
#define X2_DIR_PIN    5     // Hardware Clone මගින් ක්‍රියාත්මක වේ
#define Y_STEP_PIN    3
#define Y_DIR_PIN     6
#define Z_STEP_PIN    4
#define Z_DIR_PIN     7
#define ENABLE_PIN    8     // CNC Shield එකේ නිවැරදි Enable පින් එක

#define Z_LIMIT_PIN   11    // Z-Limit ස්විචය (Z+ Endstop)
#define GRIPPER_PIN   9     // Servo මෝටරය (X+ Endstop)
#define STATUS_LED    13    // Onboard LED

// ===================== MECHANICAL CALIBRATION ===========================
// *** VERIFY EVERY ONE OF THESE ON YOUR PHYSICAL BUILD BEFORE FIRST RUN ***
#define SQUARE_PITCH_MM      53.0   // !! Source doc said "53 cm" between square
                                    // midpoints - that is almost certainly a
                                    // typo for 53 mm (a standard chess square).
                                    // Measure your own board and fix this.
#define MICROSTEPS           16    // doc specifies 1/16 microstepping
#define MOTOR_STEPS_PER_REV  200   // 1.8 deg/step NEMA17
#define BELT_PULLEY_TEETH    20    // GT2 20T pulley
#define BELT_PITCH_MM        2.0   // GT2 belt pitch
#define XY_MM_PER_REV        (BELT_PULLEY_TEETH * BELT_PITCH_MM)         // 40 mm/rev
#define XY_STEPS_PER_MM      ((MOTOR_STEPS_PER_REV * MICROSTEPS) / XY_MM_PER_REV)

#define Z_LEAD_MM            8.0   // T8 lead screw LEAD (not pitch!) - T8 screws
                                    // commonly come in 2/4/8 mm lead variants,
                                    // confirm yours and edit this constant.
#define Z_STEPS_PER_MM       ((MOTOR_STEPS_PER_REV * MICROSTEPS) / Z_LEAD_MM)

#define XY_MAX_SPEED   8000.0   
#define XY_ACCEL       4000.0   
#define Z_MAX_SPEED    6000.0
#define Z_ACCEL        4000.0
#define Z_HOMING_SPEED 2000.0
#define Z_HOME_BACKOFF_MM  3.0

// Pick/place descend depth from the Z-home (fully retracted) position.
#define DEPTH_KING_QUEEN_MM   150.0   // 15 cm - tall pieces
#define DEPTH_OTHER_MM        170.0   // 17 cm - all other piece types

// Gripper servo angles (per source spec)
#define GRIP_CLOSE_ANGLE   0     // holding a piece
#define GRIP_OPEN_ANGLE    120   // releasing / clear of a piece

// Flip these to -1 after a calibration test-run if a given axis moves backwards.
#define X_DIR_SIGN   1
#define Y_DIR_SIGN   1

// ===== Captured-piece tray & promotion-reserve geometry (see BLUEPRINT.md
// section 10 "Special Move Handling" for why this exists - the original
// spec only describes the 8x8 board, but captures and promotions need
// somewhere physical to put/take pieces). All values are mm offsets from
// the a8 origin; lay your tray out to match, or edit these to match your
// tray's actual position. ============================================
#define TRAY_ORIGIN_X_MM     480.0
#define TRAY_ORIGIN_Y_MM     20.0
#define TRAY_SLOT_PITCH_MM   30.0
#define TRAY_ROWS_PER_SIDE   8       // slots per row before wrapping to next row
#define TRAY_SIDE_GAP_MM     40.0    // gap between the white-tray block and black-tray block
#define RESERVE_Q_X_MM       480.0
#define RESERVE_Q_Y_MM       -40.0

AccelStepper stepX1(AccelStepper::DRIVER, X1_STEP_PIN, X1_DIR_PIN);
AccelStepper stepX2(AccelStepper::DRIVER, X2_STEP_PIN, X2_DIR_PIN);
AccelStepper stepY (AccelStepper::DRIVER, Y_STEP_PIN,  Y_DIR_PIN);
AccelStepper stepZ (AccelStepper::DRIVER, Z_STEP_PIN,  Z_DIR_PIN);
Servo gripper;

String inputBuffer = "";

// ---------------------------------------------------------------------
void enableDrivers(bool en) {
  digitalWrite(ENABLE_PIN, en ? LOW : HIGH);   // LOW = enabled on common drivers
}

bool tryTraySlot(const String &sq, float &xmm, float &ymm) {
  if (sq.equalsIgnoreCase("RES_Q1")) {
    xmm = RESERVE_Q_X_MM;
    ymm = RESERVE_Q_Y_MM;
    return true;
  }
  String upper = sq;
  upper.toUpperCase();
  if (upper.startsWith("TRAY_W") || upper.startsWith("TRAY_B")) {
    int n = upper.substring(6).toInt();   // 1-based slot number
    if (n < 1) return false;
    int row = (n - 1) / TRAY_ROWS_PER_SIDE;
    int col = (n - 1) % TRAY_ROWS_PER_SIDE;
    float sideOffset = upper.startsWith("TRAY_B") ? TRAY_SIDE_GAP_MM : 0.0;
    xmm = TRAY_ORIGIN_X_MM + col * TRAY_SLOT_PITCH_MM;
    ymm = TRAY_ORIGIN_Y_MM + sideOffset + row * TRAY_SLOT_PITCH_MM;
    return true;
  }
  return false;
}

// Converts an algebraic square ("e4") OR a special tray/reserve name
// ("TRAY_W3", "RES_Q1") into absolute step targets relative to the a8 origin.
void squareToSteps(String sq, long &xSteps, long &ySteps) {
  sq.trim();
  float xmm, ymm;
  if (tryTraySlot(sq, xmm, ymm)) {
    xSteps = (long)(xmm * XY_STEPS_PER_MM) * X_DIR_SIGN;
    ySteps = (long)(ymm * XY_STEPS_PER_MM) * Y_DIR_SIGN;
    return;
  }
  sq.toLowerCase();
  int fileIdx = sq[0] - 'a';      // 0..7  (a..h)  -> Y axis per source spec
  int rank    = sq[1] - '0';      // 1..8          -> X axis per source spec
  int rankFromA8 = 8 - rank;      // a8 -> 0, a1 -> 7
  int fileFromA8 = fileIdx;       // a8 -> 0, h8 -> 7
  xSteps = (long)(rankFromA8 * SQUARE_PITCH_MM * XY_STEPS_PER_MM) * X_DIR_SIGN;
  ySteps = (long)(fileFromA8 * SQUARE_PITCH_MM * XY_STEPS_PER_MM) * Y_DIR_SIGN;
}

void homeZ() {
  enableDrivers(true);
  stepZ.setMaxSpeed(Z_HOMING_SPEED);
  stepZ.setAcceleration(Z_ACCEL);

  // Fast approach toward the switch.
  stepZ.setSpeed(-Z_HOMING_SPEED);
  while (digitalRead(Z_LIMIT_PIN) == HIGH) {
    stepZ.runSpeed();
  }
  stepZ.setCurrentPosition(0);

  // Back off, then re-approach slowly for repeatable homing accuracy.
  stepZ.moveTo((long)(Z_HOME_BACKOFF_MM * Z_STEPS_PER_MM));
  while (stepZ.distanceToGo() != 0) stepZ.run();

  stepZ.setSpeed(-Z_HOMING_SPEED / 4.0);
  while (digitalRead(Z_LIMIT_PIN) == HIGH) stepZ.runSpeed();
  stepZ.setCurrentPosition(0);   // Z=0 == fully retracted "top"/home position
}

void moveXYTo(long targetX, long targetY) {
  digitalWrite(STATUS_LED, HIGH);
  stepX1.setMaxSpeed(XY_MAX_SPEED); stepX1.setAcceleration(XY_ACCEL);
  stepX2.setMaxSpeed(XY_MAX_SPEED); stepX2.setAcceleration(XY_ACCEL);
  stepY.setMaxSpeed(XY_MAX_SPEED);  stepY.setAcceleration(XY_ACCEL);
  stepX1.moveTo(targetX);
  stepX2.moveTo(targetX);
  stepY.moveTo(targetY);
  while (stepX1.distanceToGo() != 0 || stepX2.distanceToGo() != 0 || stepY.distanceToGo() != 0) {
    stepX1.run();
    stepX2.run();
    stepY.run();
  }
  digitalWrite(STATUS_LED, LOW);
}

void moveZTo(long targetZ) {
  stepZ.setMaxSpeed(Z_MAX_SPEED);
  stepZ.setAcceleration(Z_ACCEL);
  stepZ.moveTo(targetZ);
  while (stepZ.distanceToGo() != 0) stepZ.run();
}

float depthForPiece(String pieceType) {
  pieceType.toUpperCase();
  if (pieceType == "K" || pieceType == "Q") return DEPTH_KING_QUEEN_MM;
  return DEPTH_OTHER_MM;
}

void doPick(String pieceType) {
  gripper.write(GRIP_OPEN_ANGLE);
  delay(200);
  long depthSteps = (long)(depthForPiece(pieceType) * Z_STEPS_PER_MM);
  moveZTo(depthSteps);
  gripper.write(GRIP_CLOSE_ANGLE);
  delay(300);
  moveZTo(0);   // always return to Z-home before any XY transit
}

void doPlace(String pieceType) {
  long depthSteps = (long)(depthForPiece(pieceType) * Z_STEPS_PER_MM);
  moveZTo(depthSteps);
  gripper.write(GRIP_OPEN_ANGLE);
  delay(300);
  moveZTo(0);
}

void goHomeXY() {
  long hx, hy;
  squareToSteps("a8", hx, hy);
  moveXYTo(hx, hy);
}

void processCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line == "PING") {
    Serial.println("PONG:UNO_GANTRY_V1");
  }
  else if (line == "HOME") {
    homeZ();
    goHomeXY();
    Serial.println("ACK:HOME");
  }
  else if (line.startsWith("SETPOS:")) {
    // One-time calibration: tell the firmware "the gripper is physically
    // sitting over this square right now" (there is no X/Y homing switch,
    // so the operator must align the gripper to a8 by hand at power-up,
    // then the PC sends SETPOS:a8 once).
    String sq = line.substring(7);
    long x, y;
    squareToSteps(sq, x, y);
    stepX1.setCurrentPosition(x);
    stepX2.setCurrentPosition(x);
    stepY.setCurrentPosition(y);
    Serial.print("ACK:SETPOS:");
    Serial.println(sq);
  }
  else if (line.startsWith("MOVETO:")) {
    String sq = line.substring(7);
    long tx, ty;
    squareToSteps(sq, tx, ty);
    moveXYTo(tx, ty);
    Serial.print("ACK:MOVETO:");
    Serial.println(sq);
  }
  else if (line.startsWith("PICK:")) {
    doPick(line.substring(5));
    Serial.println("ACK:PICK");
  }
  else if (line.startsWith("PLACE:")) {
    doPlace(line.substring(6));
    Serial.println("ACK:PLACE");
  }
  else if (line.startsWith("JOG:")) {
    // Calibration helper: JOG:X:200  JOG:Y:-100  JOG:Z:50  (signed microsteps)
    int p1 = line.indexOf(':', 4);
    String axis = line.substring(4, p1);
    long steps = line.substring(p1 + 1).toInt();
    if (axis == "X") {
      stepX1.move(steps); stepX2.move(steps);
      while (stepX1.distanceToGo() != 0 || stepX2.distanceToGo() != 0) { stepX1.run(); stepX2.run(); }
    } else if (axis == "Y") {
      stepY.move(steps);
      while (stepY.distanceToGo() != 0) stepY.run();
    } else if (axis == "Z") {
      stepZ.move(steps);
      while (stepZ.distanceToGo() != 0) stepZ.run();
    }
    Serial.println("ACK:JOG");
  }
  else if (line.startsWith("GRIP:")) {
    // Manual gripper test: GRIP:OPEN / GRIP:CLOSE
    String a = line.substring(5);
    gripper.write(a == "CLOSE" ? GRIP_CLOSE_ANGLE : GRIP_OPEN_ANGLE);
    Serial.println("ACK:GRIP");
  }
  else {
    Serial.print("ERR:UNKNOWN_CMD:");
    Serial.println(line);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(ENABLE_PIN, OUTPUT);
  pinMode(Z_LIMIT_PIN, INPUT_PULLUP);
  pinMode(STATUS_LED, OUTPUT);
  enableDrivers(true);            // මෙය මගින් Pin 8 "LOW" වී මෝටර් වලට Current එක ලැබේ!
  gripper.attach(GRIPPER_PIN);
  gripper.write(GRIP_OPEN_ANGLE);
  Serial.println("READY:UNO_GANTRY_V1");
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
}
