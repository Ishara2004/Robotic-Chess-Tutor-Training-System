/* =====================================================================
   Chess Robotic Tutor and Training System
   Subsystem : ROBOTIC TUTOR  (gestures, eyes, speech)
   MCU       : ESP32 (any standard DevKitC-style board)
   Board ID  : ESP32_TUTOR_V1
   Link      : USB-CDC Serial, 115200 baud, ASCII line protocol (\n terminated)
   ===================================================================== */

#include <ESP32Servo.h>
#include <Adafruit_NeoPixel.h>
#include "driver/i2s.h"

// ============================ PIN MAP ===================================
#define SERVO_RIGHT_ARM_PIN    13
#define SERVO_RIGHT_WRIST_PIN  14
#define SERVO_LEFT_ARM_PIN     23
#define SERVO_HEAD_PIN         12
#define NEOPIXEL_PIN           27
#define NUM_EYE_PIXELS         5

#define I2S_BCLK_PIN   26     // MAX98357A BCLK
#define I2S_LRC_PIN    25     // MAX98357A LRC / WS
#define I2S_DOUT_PIN   22     // MAX98357A DIN

#define EYE_BRIGHTNESS  200
#define NEUTRAL_ANGLE   90    // servo "rest" position for all 4 servos

// Gesture angles taken directly from the source design notes:
//   illegal move : right hand +45 deg, wrist +70 deg
//   player wins  : both hands +70 deg, head sweeps +/-30 deg
#define ILLEGAL_ARM_DELTA     45
#define ILLEGAL_WRIST_DELTA   70
#define WIN_ARM_DELTA         70
#define WIN_HEAD_DELTA        30

// ---------------------- Smooth-motion step delays -----------------------
// Milliseconds held between each 1-degree step. Smaller = faster sweep.
#define ARM_STEP_DELAY      20   // arm sweeps
#define WRIST_STEP_DELAY    15   // quick wrist flick
#define HEAD_STEP_DELAY      25   // head turning

Servo rightArm, rightWrist, leftArm, head;
Adafruit_NeoPixel eyes(NUM_EYE_PIXELS, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

String inputBuffer = "";

// Audio receive buffer - sized for a few seconds of 16kHz/16-bit mono speech.
#define AUDIO_BUF_MAX  64000
uint8_t audioBuf[AUDIO_BUF_MAX];

// ---------------------- Current-position state (servos) -----------------
// Tracked in software because the Servo class doesn't expose its last
// commanded angle - moveServoSmoothly() needs a known starting point to
// interpolate from. Kept accurate by ALWAYS routing servo motion through
// moveServoSmoothly()/moveTwoServosSmoothly() after the boot-time snap
// in setup() (the one place these are written to directly).
int rightArmPos   = NEUTRAL_ANGLE;
int rightWristPos = NEUTRAL_ANGLE;
int leftArmPos    = NEUTRAL_ANGLE;
int headPos       = NEUTRAL_ANGLE;

// ---------------------------------------------------------------------
void setEyeColor(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < NUM_EYE_PIXELS; i++) eyes.setPixelColor(i, eyes.Color(r, g, b));
  eyes.show();
}

// ---------------------- Smooth servo interpolation -----------------------
// Steps a single servo 1 degree at a time from its tracked current
// position to targetPos, blocking stepDelay ms between steps. This caps
// both the mechanical slew rate (no more jerk at end of travel) and the
// instantaneous current draw (no more full-travel snap current spike).
void moveServoSmoothly(Servo &servoObj, int &currentPos, int targetPos, int stepDelay) {
  if (currentPos == targetPos) return;
  int step = (targetPos > currentPos) ? 1 : -1;
  while (currentPos != targetPos) {
    currentPos += step;
    servoObj.write(currentPos);
    delay(stepDelay);
  }
}

// Steps TWO servos together, one degree each per loop iteration, so
// motions that are meant to read as simultaneous (both arms raising,
// arm+wrist flicking out together) actually animate together instead of
// one servo finishing its full travel before the next one starts. A
// servo that reaches its target before the other simply holds position
// while the other catches up.
void moveTwoServosSmoothly(Servo &servoA, int &posA, int targetA,
                            Servo &servoB, int &posB, int targetB,
                            int stepDelay) {
  int stepA = (targetA > posA) ? 1 : (targetA < posA ? -1 : 0);
  int stepB = (targetB > posB) ? 1 : (targetB < posB ? -1 : 0);
  while (posA != targetA || posB != targetB) {
    if (posA != targetA) { posA += stepA; servoA.write(posA); }
    if (posB != targetB) { posB += stepB; servoB.write(posB); }
    delay(stepDelay);
  }
}

void gestureIdle() {
  moveServoSmoothly(rightArm, rightArmPos, NEUTRAL_ANGLE, ARM_STEP_DELAY);
  moveServoSmoothly(rightWrist, rightWristPos, NEUTRAL_ANGLE, WRIST_STEP_DELAY);
  moveServoSmoothly(leftArm, leftArmPos, NEUTRAL_ANGLE, ARM_STEP_DELAY);
  moveServoSmoothly(head, headPos, NEUTRAL_ANGLE, HEAD_STEP_DELAY);
  setEyeColor(0, 150, 255);   // default light-blue eyes
}

void gestureIllegal() {
  // Right arm + wrist flick out together, then return together - the
  // "no, that move isn't legal" rejection gesture.
  moveTwoServosSmoothly(rightArm, rightArmPos, NEUTRAL_ANGLE + ILLEGAL_ARM_DELTA,
                         rightWrist, rightWristPos, NEUTRAL_ANGLE + ILLEGAL_WRIST_DELTA,
                         WRIST_STEP_DELAY);
  setEyeColor(255, 0, 0);
  delay(1200);
  moveTwoServosSmoothly(rightArm, rightArmPos, NEUTRAL_ANGLE,
                         rightWrist, rightWristPos, NEUTRAL_ANGLE,
                         WRIST_STEP_DELAY);
  setEyeColor(0, 150, 255);
}

void gestureWinPlayer() {
  // "In the winning movement of the player" - i.e. the human checkmates
  // the tutor: both arms raise together and the head sweeps side to side.
  moveTwoServosSmoothly(rightArm, rightArmPos, NEUTRAL_ANGLE + WIN_ARM_DELTA,
                         leftArm, leftArmPos, NEUTRAL_ANGLE - WIN_ARM_DELTA,
                         ARM_STEP_DELAY);

  for (int i = 0; i < 2; i++) {
    moveServoSmoothly(head, headPos, NEUTRAL_ANGLE + WIN_HEAD_DELTA, HEAD_STEP_DELAY);
    moveServoSmoothly(head, headPos, NEUTRAL_ANGLE - WIN_HEAD_DELTA, HEAD_STEP_DELAY);
  }
  moveServoSmoothly(head, headPos, NEUTRAL_ANGLE, HEAD_STEP_DELAY);

  setEyeColor(0, 255, 0);
  delay(1000);

  moveTwoServosSmoothly(rightArm, rightArmPos, NEUTRAL_ANGLE,
                         leftArm, leftArmPos, NEUTRAL_ANGLE,
                         ARM_STEP_DELAY);
  setEyeColor(0, 150, 255);
}

void gestureThinking() {
  setEyeColor(255, 165, 0);   // amber while the engine is calculating
}

// ---------------------- Audio (I2S -> MAX98357A) ----------------------
void i2sInit() {
  i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = 16000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = (i2s_comm_format_t)(I2S_COMM_FORMAT_STAND_I2S),
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 256,
    .use_apll = false
  };
  i2s_pin_config_t pins = {
    .bck_io_num = I2S_BCLK_PIN,
    .ws_io_num = I2S_LRC_PIN,
    .data_out_num = I2S_DOUT_PIN,
    .data_in_num = I2S_PIN_NO_CHANGE
  };
  i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pins);
}

void playPcmBuffer(uint8_t *buf, size_t len) {
  size_t written = 0;
  i2s_write(I2S_NUM_0, buf, len, &written, portMAX_DELAY);
}

void receiveAndPlayAudio(long byteCount) {
  if (byteCount <= 0 || byteCount > AUDIO_BUF_MAX) {
    Serial.println("ERR:AUDIO_SIZE");
    return;
  }
  size_t received = 0;
  unsigned long start = millis();
  while (received < (size_t)byteCount) {
    if (Serial.available()) {
      audioBuf[received++] = Serial.read();
    }
    if (millis() - start > 8000) {   // 8s safety timeout
      Serial.println("ERR:AUDIO_TIMEOUT");
      return;
    }
  }
  playPcmBuffer(audioBuf, (size_t)byteCount);
  Serial.println("ACK:AUDIO");
}

// ---------------------------------------------------------------------
void processCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line == "PING") {
    Serial.println("PONG:ESP32_TUTOR_V1");
  }
  else if (line.startsWith("EYES:")) {
    String c = line.substring(5);
    if (c == "BLUE")  setEyeColor(0, 150, 255);
    else if (c == "RED")   setEyeColor(255, 0, 0);
    else if (c == "GREEN") setEyeColor(0, 255, 0);
    else if (c == "OFF")   setEyeColor(0, 0, 0);
    Serial.println("ACK:EYES");
  }
  else if (line.startsWith("GESTURE:")) {
    String g = line.substring(8);
    if (g == "ILLEGAL")      gestureIllegal();
    else if (g == "WIN_PLAYER") gestureWinPlayer();
    else if (g == "THINKING")   gestureThinking();
    else if (g == "IDLE")       gestureIdle();
    Serial.println("ACK:GESTURE");
  }
  else if (line.startsWith("AUDIO:")) {
    long n = line.substring(6).toInt();
    receiveAndPlayAudio(n);
  }
  else {
    Serial.print("ERR:UNKNOWN_CMD:");
    Serial.println(line);
  }
}

void setup() {
  Serial.begin(115200);

  rightArm.attach(SERVO_RIGHT_ARM_PIN);
  rightWrist.attach(SERVO_RIGHT_WRIST_PIN);
  leftArm.attach(SERVO_LEFT_ARM_PIN);
  head.attach(SERVO_HEAD_PIN);

  // Snap directly to neutral on boot (NOT via moveServoSmoothly): there is
  // no known prior physical position to interpolate FROM right after
  // power-on, and this single immediate write() establishes the
  // deterministic starting pose the *Pos tracking variables above assume.
  rightArm.write(NEUTRAL_ANGLE);
  rightWrist.write(NEUTRAL_ANGLE);
  leftArm.write(NEUTRAL_ANGLE);
  head.write(NEUTRAL_ANGLE);
  rightArmPos   = NEUTRAL_ANGLE;
  rightWristPos = NEUTRAL_ANGLE;
  leftArmPos    = NEUTRAL_ANGLE;
  headPos       = NEUTRAL_ANGLE;

  eyes.begin();
  eyes.setBrightness(EYE_BRIGHTNESS);
  setEyeColor(0, 150, 255);   // matches gestureIdle()'s default idle color

  i2sInit();

  Serial.println("READY:ESP32_TUTOR_V1");
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
