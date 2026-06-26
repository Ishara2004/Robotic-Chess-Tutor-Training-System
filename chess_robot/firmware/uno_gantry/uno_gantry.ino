/* =====================================================================
   Chess Robotic Tutor and Training System
   Subsystem : X-Y-Z GANTRY + GRIPPER
   MCU       : Arduino UNO
   Board ID  : UNO_GANTRY_V1
   ===================================================================== */

#include <AccelStepper.h>
#include <Servo.h>

// ============================ PIN MAP (CNC SHIELD V3) ===================================
#define X_STEP_PIN    2
#define X_DIR_PIN     5
#define Y_STEP_PIN    3
#define Y_DIR_PIN     6
#define Z_STEP_PIN    4
#define Z_DIR_PIN     7
#define ENABLE_PIN    8     // CNC Shield එකේ නිවැරදි Enable පින් එක

#define Z_LIMIT_PIN   11    // Z-Limit ස්විචය (Z+ Endstop)
#define GRIPPER_PIN   9     // Servo මෝටරය (X+ Endstop)
#define STATUS_LED    13    // Onboard LED

// ===================== MECHANICAL CALIBRATION ===========================
#define SQUARE_PITCH_MM      53.0   // කොටුවක පළල මිලිමීටර් වලින්
#define MICROSTEPS           16     // 1/16 Microstepping
#define MOTOR_STEPS_PER_REV  200    // 1.8 deg/step NEMA17
#define BELT_PULLEY_TEETH    20     // GT2 20T pulley
#define BELT_PITCH_MM        2.0    // GT2 belt pitch
#define XY_MM_PER_REV        (BELT_PULLEY_TEETH * BELT_PITCH_MM)         
#define XY_STEPS_PER_MM      ((MOTOR_STEPS_PER_REV * MICROSTEPS) / XY_MM_PER_REV)

#define Z_LEAD_MM            8.0    // T8 lead screw LEAD
#define Z_STEPS_PER_MM       ((MOTOR_STEPS_PER_REV * MICROSTEPS) / Z_LEAD_MM)

#define XY_MAX_SPEED   8000.0   
#define XY_ACCEL       4000.0   
#define Z_MAX_SPEED    6000.0
#define Z_ACCEL        4000.0
#define Z_HOMING_SPEED 2000.0
#define Z_HOME_BACKOFF_MM  3.0

// Pick/place descend depth from the Z-home (fully retracted) position.
#define DEPTH_KING_QUEEN_MM   150.0 
#define DEPTH_OTHER_MM        170.0 

// Gripper servo angles
#define GRIP_CLOSE_ANGLE   120     
#define GRIP_OPEN_ANGLE    0 

// Flip these to -1 after a calibration test-run if a given axis moves backwards.
#define X_DIR_SIGN   1
#define Y_DIR_SIGN   1

#define TRAY_ORIGIN_X_MM     480.0
#define TRAY_ORIGIN_Y_MM     20.0
#define TRAY_SLOT_PITCH_MM   30.0
#define TRAY_ROWS_PER_SIDE   8       
#define TRAY_SIDE_GAP_MM     40.0    
#define RESERVE_Q_X_MM       480.0
#define RESERVE_Q_Y_MM       -40.0

// මෙහි දැන් ඇත්තේ X සඳහා එක් මෝටරයක් පමණි (Clone වීම Hardware මගින් සිදුවේ)
AccelStepper stepX(AccelStepper::DRIVER, X_STEP_PIN, X_DIR_PIN);
AccelStepper stepY(AccelStepper::DRIVER, Y_STEP_PIN, Y_DIR_PIN);
AccelStepper stepZ(AccelStepper::DRIVER, Z_STEP_PIN, Z_DIR_PIN);
Servo gripper;

String inputBuffer = "";

void enableDrivers(bool en) {
  digitalWrite(ENABLE_PIN, en ? LOW : HIGH);
}

bool tryTraySlot(const String &sq, float &xmm, float &ymm) {
  // Promotion waladi ganna Reserve Queen ge position eka (Board eken udin wam paththe)
  if (sq.equalsIgnoreCase("RES_Q1")) {
    xmm = -45.0; 
    ymm = -65.0;
    return true;
  }
  
  String upper = sq;
  upper.toUpperCase();
  
  if (upper.startsWith("TRAY_W") || upper.startsWith("TRAY_B")) {
    int n = upper.substring(6).toInt();   // Piece number eka (1, 2, 3...)
    
    // REQUIREMENT 3: Pieces 16k capture wunama apahu 1 idan patan ganma (Modulo Logic)
    n = ((n - 1) % 16) + 1; 

    // Pieces 16 eka peliyata thiyanna ida madi nisa, peli (columns) 2kata bedamu.
    int row = (n - 1) % 8; // X axis digata position eka (0 idan 7 wenakan)
    int col = (n - 1) / 8; // Y axis digata column eka (0 ho 1)

    // X axis eke dura (Ranks digata eka langa pieces thiyena dura = 45mm gap ekak)
    xmm = 10.0 + (row * 45.0); 
    
    if (upper.startsWith("TRAY_W")) {
       // REQUIREMENT 1 & 2: White pieces 'a' file eken (Y=0) 65mm eliyata.
       // Column 2k thiyena nisa dewani column eka thawa 35mm athata yanawa.
       ymm = -65.0 - (col * 35.0); 
    } else {
       // REQUIREMENT 1 & 2: Black pieces 'h' file eken 65mm eliyata.
       float h_file_y = 7.0 * SQUARE_PITCH_MM; // h-file eke Y position eka
       ymm = h_file_y + 65.0 + (col * 35.0);
    }
    
    return true;
  }
  return false;
}

void squareToSteps(String sq, long &xSteps, long &ySteps) {
  sq.trim();
  float xmm, ymm;
  if (tryTraySlot(sq, xmm, ymm)) {
    xSteps = (long)(xmm * XY_STEPS_PER_MM) * X_DIR_SIGN;
    ySteps = (long)(ymm * XY_STEPS_PER_MM) * Y_DIR_SIGN;
    return;
  }
  sq.toLowerCase();
  int fileIdx = sq[0] - 'a';
  int rank    = sq[1] - '0';
  int rankFromA8 = 8 - rank;
  int fileFromA8 = fileIdx;
  xSteps = (long)(rankFromA8 * SQUARE_PITCH_MM * XY_STEPS_PER_MM) * X_DIR_SIGN;
  ySteps = (long)(fileFromA8 * SQUARE_PITCH_MM * XY_STEPS_PER_MM) * Y_DIR_SIGN;
}

void homeZ() {
  enableDrivers(true);
  stepZ.setMaxSpeed(Z_HOMING_SPEED);
  stepZ.setAcceleration(Z_ACCEL);
  stepZ.setSpeed(-Z_HOMING_SPEED);
  while (digitalRead(Z_LIMIT_PIN) == HIGH) {
    stepZ.runSpeed();
  }
  stepZ.setCurrentPosition(0);
  stepZ.moveTo((long)(Z_HOME_BACKOFF_MM * Z_STEPS_PER_MM));
  while (stepZ.distanceToGo() != 0) stepZ.run();
  stepZ.setSpeed(-Z_HOMING_SPEED / 4.0);
  while (digitalRead(Z_LIMIT_PIN) == HIGH) stepZ.runSpeed();
  stepZ.setCurrentPosition(0);
}

void moveXYTo(long targetX, long targetY) {
  digitalWrite(STATUS_LED, HIGH);
  stepX.setMaxSpeed(XY_MAX_SPEED); stepX.setAcceleration(XY_ACCEL);
  stepY.setMaxSpeed(XY_MAX_SPEED); stepY.setAcceleration(XY_ACCEL);
  stepX.moveTo(targetX);
  stepY.moveTo(targetY);
  while (stepX.distanceToGo() != 0 || stepY.distanceToGo() != 0) {
    stepX.run();
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
  moveZTo(0);
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
    String sq = line.substring(7);
    long x, y;
    squareToSteps(sq, x, y);
    stepX.setCurrentPosition(x);
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
    int p1 = line.indexOf(':', 4);
    String axis = line.substring(4, p1);
    long steps = line.substring(p1 + 1).toInt();
    if (axis == "X") {
      stepX.move(steps);
      while (stepX.distanceToGo() != 0) stepX.run();
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
  enableDrivers(true);
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