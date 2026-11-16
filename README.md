# Chess Robotic Tutor and Training System

![Platform](https://img.shields.io/badge/Platform-Arduino%20Mega%20%7C%20Arduino%20Uno%20%7C%20ESP32-blue)
![Python](https://img.shields.io/badge/Python-3.x%20%7C%20Kivy%20%7C%20python--chess-yellow)
![Engine](https://img.shields.io/badge/AI%20Engine-Stockfish-green)
![Database](https://img.shields.io/badge/Database-SQLite3-lightgrey)
![Status](https://img.shields.io/badge/Version-1.0%20Master%20Blueprint-brightgreen)

**Institution:** First Year Project ,Faculty of Information Technology, University of Moratuwa  

Developing the **Chess Robotic Tutor and Training System** at the Faculty of Information Technology, University of Moratuwa, bridges distributed embedded systems, precision 3-axis mechatronics, and Stockfish-driven artificial intelligence into a single interactive physical platform. Rather than playing on a flat screen, players interact with real chess pieces while guided by an animatronic tutor, illuminated board hints, and an automated overhead gantry.

---

## Table of Contents

1. [System Overview & Distributed Microcontroller Architecture](#1-system-overview--distributed-microcontroller-architecture)
2. [Smart Chessboard Subsystem: I2C Matrix Sensing & Visual Feedback](#2-smart-chessboard-subsystem-i2c-matrix-sensing--visual-feedback)
3. [Precision 3-Axis Gantry & Stepper Kinematics](#3-precision-3-axis-gantry--stepper-kinematics)
4. [Animatronic Robotic Tutor & Interactive Touchscreen GUI](#4-animatronic-robotic-tutor--interactive-touchscreen-gui)
5. [Solving Real-World Chess Edge Cases in Hardware](#5-solving-real-world-chess-edge-cases-in-hardware)
6. [Electrical Design, Power Distribution & Complete Pinout Tables](#6-electrical-design-power-distribution--complete-pinout-tables)
7. [ASCII Serial Communication Protocol Specification](#7-ascii-serial-communication-protocol-specification)
8. [Consolidated Bill of Materials (BOM)](#8-consolidated-bill-of-materials-bom)
9. [Assumptions, Clarifications & Flagged Engineering Ambiguities](#9-assumptions-clarifications--flagged-engineering-ambiguities)
10. [Core Firmware & Software Implementation (Code & Sinhala Explanations)](#10-core-firmware--software-implementation-code--sinhala-explanations)
11. [Repository Structure & File Manifest](#11-repository-structure--file-manifest)
12. [Installation, Calibration & Commissioning Procedure](#12-installation-calibration--commissioning-procedure)
13. [Safety Notes & Future Enhancements](#13-safety-notes--future-enhancements)
14. [Viva Presentation — Examiner Q&A Preparation](#14-viva-presentation--examiner-qa-preparation)

---

## 1. System Overview & Distributed Microcontroller Architecture

Instead of overloading a single microcontroller with real-time sensor polling, stepper pulse generation, and audio streaming, the system distributes responsibilities across three dedicated microcontrollers coordinated by a central Python application on a laptop:

```
                         ┌───────────────────────────┐
                         │   LAPTOP (Python app)     │
                         │  - python-chess + Stockfish│
                         │  - SQLite profile/history  │
                         │  - Kivy touchscreen GUI    │
                         │  - Offline TTS speech      │
                         └──────┬─────┬─────┬─────────┘
                     USB-Serial │     │     │ USB-Serial
                          COM3  │     │     │  COM7
                                │     │ USB-Serial
                                │     │  COM8
                  ┌─────────────▼┐ ┌──▼──────────┐ ┌▼─────────────┐
                  │ ARDUINO MEGA │ │ ARDUINO UNO  │ │    ESP32     │
                  │ Chessboard   │ │ X-Y-Z Gantry │ │ Robotic Tutor│
                  │ 64 reed sw.  │ │ + Gripper    │ │ Servos, eyes,│
                  │ 64 NeoPixels │ │              │ │ speech       │
                  └──────────────┘ └──────────────┘ └──────────────┘
```

All three microcontrollers connect directly to the laptop via independent $115200\text{ baud}$ **USB-Serial** links (`COM3 = Arduino Mega`, `COM7 = ESP32`, `COM8 = Arduino Uno`), eliminating wireless latency and drop-outs.

### Subsystem Responsibilities

| Subsystem | MCU | Primary Responsibility | Operating Mode |
|---|---|---|---|
| **Smart Chessboard** | Arduino MEGA 2560 | Continuously scans 64 reed switches to detect piece lifts and placements; drives 64 WS2812 NeoPixels for legal-move hints and checkmate celebration. | **Autonomous Event Stream** (~$33\text{ Hz}$ polling) |
| **X-Y-Z Gantry & Gripper** | Arduino UNO | Controls 4 NEMA 17 stepper motors and an MG995 servo gripper to move pieces across the board, captured-piece trays, and promotion reserve. | **Synchronous Command $\rightarrow$ ACK** |
| **Animatronic Robotic Tutor** | ESP32 | Drives 4 MG90S gesture servos (arms, wrist, head), 5 NeoPixel eye LEDs, and a MAX98357A I2S audio amplifier for spoken move explanations. | **Synchronous Command $\rightarrow$ ACK** |
| **Central Orchestrator** | Laptop (Python) | Integrates `python-chess` and Stockfish for game logic, SQLite for player profiles and 30-day progress tracking, Kivy for the touchscreen GUI, and `pyttsx3` for offline speech synthesis. | **Master Controller** |

### End-to-End Move Sequence (Robot's Turn)
1. PC queries Stockfish for the best move at the selected difficulty level.
2. PC constructs a human-readable explanation and synthesizes it to speech (offline TTS).
3. PC streams the speech audio to the ESP32, which plays it through the onboard speaker **before** any physical movement occurs.
4. PC decomposes the chess move into an ordered list of physical actions and sends them to the Arduino Uno one at a time, waiting for each `ACK`.
5. Uno automatically returns the gripper to the home position (square `a8`) after the move sequence completes.
6. PC updates its internal board state only after physical completion is confirmed.

### End-to-End Move Sequence (Human's Turn)
1. Human lifts a piece $\rightarrow$ Mega reports `SQEVT:<square>:OPEN`.
2. PC calculates that piece's legal destinations and sends `SHOWMOVES` to the Mega (quiet moves in light blue, capture squares in red).
3. Human places the piece on a target square $\rightarrow$ Mega reports `SQEVT:<square>:CLOSED`.
4. PC clears the LEDs and validates whether the resulting move is legal:
   - **Legal:** Game state updates and turn passes to the robot.
   - **Illegal:** ESP32 triggers the illegal move gesture (right arm raises $45^\circ$, wrist raises $70^\circ$, eyes turn red) and the GUI prompts the player to undo the move.

---

## 2. Smart Chessboard Subsystem: I2C Matrix Sensing & Visual Feedback

To monitor all 64 squares without exhausting microcontroller pins, the chessboard wires 64 reed switches across four **MCP23017 I/O expanders** (`0x20`, `0x21`, `0x22`, `0x23`) connected to the Arduino Mega's I2C bus (Pin 20 SDA, Pin 21 SCL). Each reed switch connects between an MCP23017 GPIO pin and ground with internal pull-up resistors enabled in firmware, so a closed switch (occupied square) reads `LOW`. The Mega autonomously polls the matrix at ~$33\text{ Hz}$ and immediately emits `SQEVT:<square>:OPEN` or `SQEVT:<square>:CLOSED` events over serial.

For visual guidance, 64 NeoPixel (WS2812) LEDs are wired in an ascending zig-zag (serpentine) order and driven from Mega Pin 6 through a $330\ \Omega$ data-line resistor:
* **Quiet Legal Moves:** When a player lifts a piece, valid empty destination squares illuminate in **light blue**.
* **Capture Targets:** Squares containing opponent pieces that can be legally captured illuminate in **red**.
* **Checkmate Celebration:** If the human player checkmates the robotic tutor, all 64 LEDs across the board light up in **green**.

---

## 3. Precision 3-Axis Gantry & Stepper Kinematics

Mounted above the chessboard on a 2020 V-Slot aluminum profile frame, the X-Y-Z gantry is powered by an Arduino UNO and four **DRV8825** stepper motor drivers configured for $1/16$ microstepping.

* **X-Axis (Ranks 1–8):** Driven by two parallel NEMA 17 motors (`X1` on Pins 2/3, `X2` on Pins 4/5) on either side of the gantry beam so the bridge remains square and moves smoothly during travel.
* **Y-Axis (Files a–h):** Driven by a single NEMA 17 motor (Pins 6/7), with both X and Y axes utilizing GT2 20-tooth timing pulleys and GT2 timing belts.
* **Z-Axis & Lead Screw:** A fourth NEMA 17 motor (Pins 8/9) drives a T8 lead screw coupled to the robotic gripper, using a horizontal limit switch on Pin 11 to home the `(0, 0)` Z position.
* **Servo Actuation:** An **MG995 servo** (Pin 12) actuates the gripper jaws, closing to $0^\circ$ to grasp a piece and opening to $120^\circ$ to release it.

### Coordinate System & Stepper Calibration Math
With the human seated in front of the robot, square **a8** on the robot's right side serves as the default/home origin `(0, 0)`.

$$\text{Travel per motor revolution (XY)} = 20\text{ teeth} \times 2\text{ mm pitch} = 40\text{ mm}$$

$$\text{Microsteps per revolution} = 200\text{ steps/rev } (1.8^\circ) \times 16\text{ microsteps} = 3200\text{ microsteps/rev}$$

$$\text{XY Steps per mm} = \frac{3200}{40\text{ mm}} = 80\text{ steps/mm}$$

$$\text{Z Steps per mm (T8 Lead Screw, } 8\text{ mm lead)} = \frac{3200}{8\text{ mm}} = 400\text{ steps/mm}$$

$$\text{Steps between adjacent square centers } (53\text{ mm pitch}) = 53\text{ mm} \times 80\text{ steps/mm} = 4240\text{ microsteps}$$

### Gripper Descend Depths & Collision Prevention
Because chess pieces vary in height, the Z-axis uses two calibrated descend depths from the top home position (`Z = 0`):
* **King and Queen:** Descends **$150\text{ mm}$ ($15\text{ cm}$)** from Z-home.
* **Pawn, Rook, Bishop, and Knight:** Descends **$170\text{ mm}$ ($17\text{ cm}$)** from Z-home.
* **Collision Prevention:** The gripper always retracts to `Z = 0` before any X/Y movement and automatically returns to the `a8` home square after completing every move.

---

## 4. Animatronic Robotic Tutor & Interactive Touchscreen GUI

The physical tutor is controlled by an **ESP32** driving four **MG90S servo motors** (Right Arm on GPIO 13, Right Wrist on GPIO 4, Left Arm on GPIO 16, Head on GPIO 17) and five **NeoPixel LEDs** (GPIO 5) for its eyes:
* **Default Idle State:** All five eye NeoPixels glow in **light blue**.
* **Illegal Move Warning:** When the player makes an illegal move, the robot's eyes turn **red**, its right arm raises $45^\circ$, and its right wrist raises $70^\circ$.
* **Player Victory Gesture:** When the player wins, both the right and left arms raise $70^\circ$ while the head swings $30^\circ$ left and right in celebration.
* **Spoken Move Explanations:** Before executing each move, the Python app synthesizes an explanation of the best move into $16\text{ kHz}$ / $16\text{-bit}$ mono PCM audio (`pyttsx3`) and streams it to the ESP32's **MAX98357A I2S amplifier** (BCLK 26, LRC 25, DIN 22) and **$3\text{ W}$, $4\ \Omega$ speaker**.

An **MPI 5008 V4.9** touchscreen display connects directly to the laptop via HDMI and micro-USB to render the Kivy GUI:
* **Player Profiles:** New players create a profile; existing players select their profile and log in (stored in SQLite).
* **Game Modes:** Select between **Standard** mode and **Puzzle** mode (`puzzles.json`).
* **Difficulty Levels:** Select between **Easy**, **Medium**, and **Hard**, mapped directly to Stockfish parameters:

| Level | Stockfish Skill Level | Search Depth | Time Budget |
|---|---|---|---|
| **Easy** | 3 | 4 | $200\text{ ms}$ |
| **Medium** | 10 | 10 | $800\text{ ms}$ |
| **Hard** | 20 (Maximum) | 22 | $3000\text{ ms}$ |

* **30-Day Progress Graph:** Tracks player improvement over 30 days plotted on an X-Y accuracy graph (`GraphScreen`).

---

## 5. Solving Real-World Chess Edge Cases in Hardware

A physical chess robot cannot simply make captured pieces vanish or conjure promoted pieces out of thin air. In our software architecture, `ChessSession.physical_plan_for_move()` decomposes every legal move into an ordered sequence of synchronous `MOVETO`, `PICK`, and `PLACE` commands executed by the Arduino Uno:

| Chess Scenario | Physical Gantry Execution Sequence |
|---|---|
| **Ordinary Move** | One `PICK` at the origin square, followed by one `PLACE` at the destination square. |
| **Captures** | The gantry first `PICK`s the captured piece from the target square and `PLACE`s it into the next free slot in the off-board **Captured-Piece Tray** (`TRAY_W1..TRAY_W16` or `TRAY_B1..TRAY_B16`) before moving the attacking piece. |
| **En Passant** | Using `python-chess`'s `board.is_en_passant()`, the orchestrator calculates the captured pawn's actual square separately from the destination square, removes the pawn to the tray, and then moves the capturing pawn. |
| **Castling** | Decomposed into two standard relocations: moving the King first, followed by the corresponding Rook to its FIDE-standard castling square (King-side or Queen-side). |
| **Pawn Promotion** | The promoting pawn is retired to the captured-piece tray, and a spare Queen is fetched from the off-board **Promotion Reserve (`RES_Q1`)** and placed onto the promotion square. |

---

## 6. Electrical Design, Power Distribution & Complete Pinout Tables

### 6.1 Power & Grounding Plan
Most robotics failures stem from power brownouts rather than software bugs. All power supplies must share a **common star-ground reference**:

| Power Rail | Subsystem Powered | Engineering Notes |
|---|---|---|
| **$5\text{ V}$ / $4\text{ A+}$ PSU** | $64\times$ NeoPixel Chessboard Matrix | **Dedicated supply — never use Arduino's onboard $5\text{ V}$.** Add a $1000\ \mu\text{F}$ electrolytic capacitor across power input and a $300\text{--}500\ \Omega$ resistor on the data line. |
| **$12\text{ V}$ (or $24\text{ V}$) PSU** | $4\times$ NEMA 17 Steppers via DRV8825 | Sized to motor rated current $\times 4$ with headroom. |
| **$5\text{ V}$ / $3\text{ A}$ PSU** | MG995 Gripper + $4\times$ MG90S Tutor Servos | Dedicated rail isolates sharp inductive current spikes from logic boards. |
| **$5\text{ V}$ (USB / Regulated)** | Arduino Mega 2560 & Arduino UNO Logic | Standard logic supply. |
| **$5\text{ V} \rightarrow 3.3\text{ V}$ Regulator** | ESP32 Logic & MAX98357A Filtering | Protected with diode, $10\ \mu\text{H}$ inductor, and $100\ \mu\text{F}$ / $10\ \mu\text{F}$ filtering capacitors. |

**DRV8825 Current Limit ($V_{\text{ref}}$) Formula:**
$$V_{\text{ref}} = I_{\text{motor}} \times 0.8 \quad (\text{for standard } 0.1\ \Omega \text{ sense resistors})$$

### 6.2 Arduino MEGA 2560 — Smart Chessboard Pinout (`COM3`)

| Signal / Component | Mega Pin / I2C Address | Notes |
|---|---|---|
| I2C SDA | Pin 20 | Connects to all 4 MCP23017 expanders |
| I2C SCL | Pin 21 | Connects to all 4 MCP23017 expanders |
| NeoPixel Matrix Data (64 LEDs) | Pin 6 | Wired via $330\ \Omega$ series resistor |
| MCP23017 #1 (Squares 0–15) | `0x20` | Internal pull-ups enabled (`LOW` = occupied) |
| MCP23017 #2 (Squares 16–31) | `0x21` | Internal pull-ups enabled (`LOW` = occupied) |
| MCP23017 #3 (Squares 32–47) | `0x22` | Internal pull-ups enabled (`LOW` = occupied) |
| MCP23017 #4 (Squares 48–63) | `0x23` | Internal pull-ups enabled (`LOW` = occupied) |

### 6.3 Arduino UNO — X-Y-Z Gantry Pinout (`COM8`)

| Signal / Component | Uno Pin | Notes |
|---|---|---|
| X1 Stepper `STEP` / `DIR` | Pin 2 / Pin 3 | Left gantry beam NEMA 17 |
| X2 Stepper `STEP` / `DIR` | Pin 4 / Pin 5 | Right gantry beam NEMA 17 (driven in lockstep with X1) |
| Y Stepper `STEP` / `DIR` | Pin 6 / Pin 7 | Cross-beam carriage NEMA 17 |
| Z Stepper `STEP` / `DIR` | Pin 8 / Pin 9 | T8 lead screw vertical NEMA 17 |
| Stepper Driver `ENABLE` | Pin 10 | Shared across all 4 DRV8825 drivers (Active `LOW`) |
| Z-Axis Limit Switch | Pin 11 | Configured as `INPUT_PULLUP` (homes `Z = 0`) |
| Robotic Gripper Servo (MG995) | Pin 12 | $0^\circ$ = Closed/Pick, $120^\circ$ = Open/Drop |
| Onboard Status LED | Pin 13 | Diagnostic indicator |

### 6.4 ESP32 — Animatronic Robotic Tutor Pinout (`COM7`)

| Signal / Component | ESP32 GPIO | Notes |
|---|---|---|
| Right Arm Servo (MG90S) | GPIO 13 | Raises $45^\circ$ on illegal move, $70^\circ$ on player win |
| Right Wrist Servo (MG90S) | GPIO 4 | Raises $70^\circ$ on illegal move |
| Left Arm Servo (MG90S) | GPIO 16 | Raises $70^\circ$ on player win |
| Head Servo (MG90S) | GPIO 17 | Swings $30^\circ$ left/right on player win |
| Eyes NeoPixel Data (5 LEDs) | GPIO 5 | Light Blue = Default, Red = Illegal Move |
| MAX98357A I2S `BCLK` | GPIO 26 | Digital audio bit clock |
| MAX98357A I2S `LRC` / `WS` | GPIO 25 | Digital audio word select |
| MAX98357A I2S `DIN` | GPIO 22 | Digital audio data input |

*(Note: ESP32 boot-strapping pins 0, 2, 12, 15 and internal flash pins 6–11 are deliberately avoided.)*

---

## 7. ASCII Serial Communication Protocol Specification

All three USB-Serial links operate at **$115200\text{ baud}$**, transmitting plain ASCII lines terminated by `\n`.

### 7.1 Auto-Discovery Handshake (All Boards)

| PC Sends | Microcontroller Replies |
|---|---|
| `PING` | `PONG:MEGA_CHESSBOARD_V1` / `PONG:UNO_GANTRY_V1` / `PONG:ESP32_TUTOR_V1` |

### 7.2 Arduino MEGA (Chessboard) Commands & Events

| Command / Event | Effect | Response |
|---|---|---|
| `SHOWMOVES:<csv blue>:<csv red>` | Lights quiet legal moves in light blue and capture moves in red; clears other LEDs | `ACK:SHOWMOVES` |
| `CLEARLEDS` | Turns off all 64 NeoPixels | `ACK:CLEARLEDS` |
| `WINGREEN` | Illuminates all 64 NeoPixels in green (checkmate celebration) | `ACK:WINGREEN` |
| `GETSTATE` | Requests a full 64-bit occupancy snapshot | `STATE:<16 hex chars>` |
| *(Unsolicited Event)* | Emitted immediately when a reed switch changes state | `SQEVT:<square>:OPEN` / `SQEVT:<square>:CLOSED` |

### 7.3 Arduino UNO (Gantry) Commands

| Command | Effect | Response |
|---|---|---|
| `HOME` | Homes Z-axis against the limit switch, then returns X/Y to `a8` | `ACK:HOME` |
| `SETPOS:<square>` | Calibrates current physical gripper position as `<square>` | `ACK:SETPOS:<square>` |
| `MOVETO:<square>` | Moves X/Y over the given board square, tray slot, or reserve slot | `ACK:MOVETO:<square>` |
| `PICK:<piece letter>` | Descends to piece-specific depth ($150\text{ mm}$ or $170\text{ mm}$), closes gripper ($0^\circ$), retracts to `Z = 0` | `ACK:PICK` |
| `PLACE:<piece letter>` | Descends to piece-specific depth, opens gripper ($120^\circ$), retracts to `Z = 0` | `ACK:PLACE` |
| `JOG:<X/Y/Z>:<signed steps>` | Manual microstep nudge for axis calibration | `ACK:JOG` |
| `GRIP:<OPEN/CLOSE>` | Manual gripper jaw actuation test | `ACK:GRIP` |

### 7.4 ESP32 (Robotic Tutor) Commands

| Command | Effect | Response |
|---|---|---|
| `EYES:<BLUE/RED/GREEN/OFF>` | Sets the 5 eye NeoPixels to the specified color | `ACK:EYES` |
| `GESTURE:<IDLE/ILLEGAL/WIN_PLAYER/THINKING>` | Executes the corresponding servo choreography | `ACK:GESTURE` |
| `AUDIO:<byte count>` + raw PCM | Buffers and plays $16\text{ kHz}$ / $16\text{-bit}$ mono PCM speech over I2S | `ACK:AUDIO` |

*Error Handling:* Any invalid command or hardware fault returns `ERR:<reason>`, causing `serial_comm.py` to raise an explicit Python exception.

---

## 8. Consolidated Bill of Materials (BOM)

Prices are preserved as recorded in the original hardware documentation (in LKR).

### 8.1 Smart Chessboard Subsystem

| Component | Quantity | Cost (LKR) |
|---|---|---|
| Reed switches | 64 | 7,680 |
| MCP23017 I/O expander ICs | 4 | 3,800 |
| NeoPixel (WS2812) LEDs | 64 | 750 |
| Chess pieces (magnetic base) | 32 | 2,500 |
| Physical chessboard | 1 | 12,500 |
| Arduino MEGA 2560 | 1 | 4,800 |

### 8.2 X-Y-Z Gantry & Gripper Subsystem

| Component | Quantity | Cost (LKR) |
|---|---|---|
| NEMA 17 stepper motors | 4 | 9,200 |
| GT2 20T timing pulleys | 6 | 720 |
| GT2 timing belt ($5\text{ m}$) | 2 | 2,250 |
| NEMA 17 motor holders | 2 | 560 |
| 2020 V-Slot aluminum profiles | 4 | 8,640 |
| Angle brackets | 4 | 800 |
| V-Slot gantry plate sets | 3 | 4,950 |
| Wire ties | 10 | 100 |
| T8 lead screw full set | 1 | 1,880 |
| MG995 servo motor (gripper) | 1 | 1,150 |
| Robotic gripper assembly | 1 | 1,300 |
| Horizontal limit switch (Z-axis) | 1 | 160 |
| Box bars | 4 | 1,300 |
| CNC controller shield/board | 1 | 450 |
| DRV8825 stepper motor drivers | 4 | 1,600 |
| Arduino UNO | 1 | 1,300 |

### 8.3 Animatronic Robotic Tutor & Display Subsystem

| Component | Quantity | Cost (LKR) |
|---|---|---|
| MG90S micro servo motors | 4 | 2,320 |
| MPI 5008 V4.9 HDMI+USB touchscreen display | 1 | 10,950 |
| NeoPixel LEDs (eyes) | 5 | 65 |
| Custom PCB | 1 | 13,000 |
| ESP32 development board | 1 | 1,400 |
| 3D-printed robot enclosure | 1 | 20,000 |
| $3\text{ W}$ $4\ \Omega$ speaker | 1 | 130 |
| MAX98357A I2S amplifier module & $10\ \mu\text{H}$ inductor | 1 + 1 | 700 |
| $100\ \mu\text{F}$ and $10\ \mu\text{F}$ electrolytic capacitors | 2 | — |
| Protection diode, $3.3\text{ V}$ regulator, logic level shifter | 1 set | — |
| $5\text{ V}$ DC barrel jack | 1 | — |

### 8.4 Essential Engineering Additions (Blueprint Requirements)

| Component | Quantity | Purpose |
|---|---|---|
| $5\text{ V}$ / $4\text{ A+}$ switching PSU | 1 | Dedicated power rail for the 64-NeoPixel chessboard matrix |
| $12\text{ V}$ (or $24\text{ V}$) stepper PSU | 1 | Dedicated motor power for the 4 DRV8825 drivers |
| $5\text{ V}$ / $3\text{ A}$ servo PSU | 1 | Dedicated power rail for MG995 + $4\times$ MG90S servos |
| $1000\ \mu\text{F}$ capacitor & $330\ \Omega$ resistor | 1 + 1 | Inrush protection and signal integrity for NeoPixel strip |
| Off-board captured-piece tray & spare Queen | 1 set | Physical staging area for captures (`TRAY_*`) and promotion (`RES_Q1`) |
| Star-ground bus bar | 1 | Common ground reference across all power supplies and MCUs |

---

## 9. Assumptions, Clarifications & Flagged Engineering Ambiguities

To make the hardware specification completely buildable and playable, the following engineering clarifications were standardized across the firmware and software:

| # | Original Spec Note | Identified Issue | Engineering Resolution Implemented |
|---|---|---|---|
| 1 | "Distance between square midpoints is $53\text{ cm}$" | $53\text{ cm}$ would make the board over $4\text{ m}$ wide (typo for $53\text{ mm}$). | Standardized `SQUARE_PITCH_MM = 53.0` ($53\text{ mm}$) in `uno_gantry.ino`. |
| 2 | "T8 Lead screw full set" | Lead pitch (2, 4, or $8\text{ mm}$) not explicitly stated. | Assumed $8\text{ mm}$ lead (`Z_LEAD_MM = 8.0`, giving $400\text{ steps/mm}$). Verify against physical screw. |
| 3 | "MPI 5008 V4.9" display | Connects via HDMI and USB micro port to the laptop. | Treated as an HDMI+USB touchscreen monitor driven directly by the laptop's Kivy GUI. |
| 4 | "5 DC current jack" | Ambiguous between quantity 5 vs. $5\text{ V}$ rating. | Interpreted as one $5\text{ V}$ DC barrel jack connector. |
| 5 | "10 uhi Inductor", "100, 10 capacitors", "Diaode" | Component spelling typos in BOM. | Standardized as $10\ \mu\text{H}$ inductor, $100\ \mu\text{F}$ / $10\ \mu\text{F}$ capacitors, and protection diode for MAX98357A power filtering. |
| 6 | Captured pieces | Unaddressed in original notes (physical pieces cannot vanish). | Added off-board captured-piece tray coordinates (`TRAY_W1..W16`, `TRAY_B1..B16`). |
| 7 | Pawn promotion | Unaddressed in original notes. | Added off-board promotion reserve (`RES_Q1`) holding a spare Queen. |
| 8 | "CNS divided into $1/16$ micro steps" | Typo for CNC shield microstepping. | Configured `MICROSTEPS = 16` in firmware; set DRV8825 jumpers to `MS1=0, MS2=0, MS3=1`. |
| 9 | Pick/place descend depth ($15\text{ cm}$ K/Q, $17\text{ cm}$ others) | Only mentioned for pickup. | Applied symmetrically to both `PICK` and `PLACE` operations. |
| 10 | X/Y axis homing | Only 1 limit switch is in the BOM (assigned to Z-axis). | Z homes via the switch; X/Y use step-counting from `a8` calibrated via `SETPOS:a8` at startup. |
| 11 | Motor direction polarity | Depends on physical coil wiring order. | Exposed `X_DIR_SIGN` and `Y_DIR_SIGN` constants and a `JOG` command for rapid commissioning. |

---

## 10. Core Firmware & Software Implementation (Code & Sinhala Explanations)

### A. Serpentine Matrix Mapping & Stepper Kinematics (`mega_chessboard.ino` & `uno_gantry.ino`)

```cpp
// Custom Serpentine Matrix Mapping Table (wired row-by-row sequentially in zig-zag order)
// Maps each sensor/LED index (0..63) to its physical algebraic chess square
const String squares[64] = {
    "h1","h2","h3","h4","h5","h6","h7","h8",
    "g8","g7","g6","g5","g4","g3","g2","g1",
    "f1","f2","f3","f4","f5","f6","f7","f8",
    "e8","e7","e6","e5","e4","e3","e2","e1",
    "d1","d2","d3","d4","d5","d6","d7","d8",
    "c8","c7","c6","c5","c4","c3","c2","c1",
    "b1","b2","b3","b4","b5","b6","b7","b8",
    "a8","a7","a6","a5","a4","a3","a2","a1"
};

// Kinematic Calibration Constants (uno_gantry.ino)
// XY axes: 20-tooth GT2 pulley * 2mm pitch = 40mm travel per revolution
// 200 full steps * 16 microsteps = 3200 microsteps/rev -> 3200 / 40mm = 80 steps/mm
const float XY_STEPS_PER_MM = 80.0;

// Z axis: T8 leadscrew (8mm lead) -> 3200 microsteps / 8mm = 400 steps/mm
const float Z_STEPS_PER_MM = 400.0;

// Center-to-center distance between adjacent squares = 53.0 mm (4240 microsteps)
const float SQUARE_PITCH_MM = 53.0;

// Vertical descend depths from Z=0 home position
const float DEPTH_KING_QUEEN_MM = 150.0; // 15 cm for King and Queen
const float DEPTH_OTHER_MM      = 170.0; // 17 cm for all other pieces
```

**Technical Explanation:**
- **Serpentine Matrix Mapping:** To simplify under-board wiring, the 64 reed switches and 64 NeoPixel LEDs are connected in an ascending zig-zag (serpentine) pattern (running forward from `h1` to `h8`, then backward on the next row from `g8` to `g1`, and so on). The `squares[64]` lookup array maps any physical sensor or LED index (`0–63`) directly to its corresponding algebraic chess square.
- **Kinematics Calculation:** Because a 20-tooth GT2 timing pulley with a 2 mm belt pitch advances 20 × 2 mm = 40 mm per motor revolution, and a 1.8° stepper motor (200 steps/rev) configured for 1/16 microstepping on the DRV8825 driver yields 200 × 16 = 3200 microsteps/rev, linear travel requires 3200 / 40 = 80 steps/mm. Consequently, traversing the 53 mm center-to-center distance between adjacent squares requires 53 × 80 = 4240 microsteps.

### B. Physical Move Decomposition Algorithm (`chess_logic.py`)

```python
def physical_plan_for_move(board, move, next_white_tray, next_black_tray):
    """
    Decomposes any legal python-chess Move into an ordered list of synchronous 
    physical gantry commands (MOVETO, PICK, PLACE) for the Arduino UNO.
    """
    actions = []
    from_sq = chess.square_name(move.from_square)
    to_sq = chess.square_name(move.to_square)
    moving_piece = board.piece_at(move.from_square)

    # 1. Handle Captures (including En Passant where captured pawn is not on 'to_sq')
    if board.is_capture(move):
        if board.is_en_passant(move):
            # Captured pawn sits on the destination file and origin rank
            ep_sq = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
            cap_sq = chess.square_name(ep_sq)
            captured_piece = board.piece_at(ep_sq)
        else:
            cap_sq = to_sq
            captured_piece = board.piece_at(move.to_square)

        # Route captured piece to the next free off-board tray slot
        tray_slot = next_white_tray() if captured_piece.color == chess.WHITE else next_black_tray()
        actions.extend([
            f"MOVETO:{cap_sq}",
            f"PICK:{captured_piece.symbol()}",
            f"MOVETO:{tray_slot}",
            f"PLACE:{captured_piece.symbol()}"
        ])

    # 2. Handle Castling (Relocate King first, then move the corresponding Rook)
    if board.is_castling(move):
        actions.extend([
            f"MOVETO:{from_sq}",
            f"PICK:{moving_piece.symbol()}",
            f"MOVETO:{to_sq}",
            f"PLACE:{moving_piece.symbol()}"
        ])
        if chess.square_file(move.to_square) == 6:  # King-side castling (g-file)
            rook_from = "h1" if moving_piece.color == chess.WHITE else "h8"
            rook_to   = "f1" if moving_piece.color == chess.WHITE else "f8"
        else:                                       # Queen-side castling (c-file)
            rook_from = "a1" if moving_piece.color == chess.WHITE else "a8"
            rook_to   = "d1" if moving_piece.color == chess.WHITE else "d8"
        actions.extend([
            f"MOVETO:{rook_from}",
            "PICK:R",
            f"MOVETO:{rook_to}",
            "PLACE:R"
        ])
        return actions

    # 3. Handle Pawn Promotion (Retire Pawn to tray, fetch spare Queen from RES_Q1)
    if move.promotion is not None:
        tray_slot = next_white_tray() if moving_piece.color == chess.WHITE else next_black_tray()
        actions.extend([
            f"MOVETO:{from_sq}",
            f"PICK:{moving_piece.symbol()}",
            f"MOVETO:{tray_slot}",
            f"PLACE:{moving_piece.symbol()}",
            "MOVETO:RES_Q1",
            "PICK:Q",
            f"MOVETO:{to_sq}",
            "PLACE:Q"
        ])
        return actions

    # 4. Standard Move
    actions.extend([
        f"MOVETO:{from_sq}",
        f"PICK:{moving_piece.symbol()}",
        f"MOVETO:{to_sq}",
        f"PLACE:{moving_piece.symbol()}"
    ])
    return actions
```

**Technical Explanation:**
- This Python function decomposes any complex chess move executed by Stockfish or the player into an ordered sequence of synchronous commands (`MOVETO`, `PICK`, `PLACE`) understood by the Arduino UNO.
- Passing the piece symbol (`K`, `Q`, `P`, `R`, etc.) along with `PICK:<piece letter>` and `PLACE:<piece letter>` allows the UNO firmware to determine the exact Z-axis descend depth—150 mm for the King and Queen, and 170 mm for all other pieces.



### 11. 12-Step Hardware Commissioning Checklist
Run through this sequence in order before playing an automated game:
1. **Power-Up Verification:** Measure all power rails independently ($5\text{ V}$ NeoPixel rail, $12\text{ V}/24\text{ V}$ stepper rail, $5\text{ V}$ servo rail) with a multimeter before connecting logic boards. Verify common star-ground continuity.
2. **DRV8825 $V_{\text{ref}}$ Tuning:** With stepper motors disconnected, adjust the trim pot on all 4 DRV8825 drivers to $V_{\text{ref}} = I_{\text{motor}} \times 0.8$.
3. **Microstep Jumpers:** Set `MS1=0, MS2=0, MS3=1` ($1/16$ microstepping) across all 4 DRV8825 sockets.
4. **Flash Firmware:** Upload the respective `.ino` sketches to the Mega, Uno, and ESP32.
5. **Mega Bring-Up (`COM3`):** Open Serial Monitor at $115200\text{ baud}$, send `PING`, and verify `PONG:MEGA_CHESSBOARD_V1`. Lift/place pieces to confirm `SQEVT` events and test `SHOWMOVES:e4,e5:d5`.
6. **Uno Bring-Up (`COM8`):** Send `PING` and verify `PONG:UNO_GANTRY_V1`. Clear the board, send `HOME` to verify Z-axis limit switch homing, and use `JOG:X:200` / `JOG:Y:200` to check axis directions (invert `X_DIR_SIGN` or `Y_DIR_SIGN` if reversed).
7. **Gripper Depth Calibration:** Use `GRIP:OPEN`, `GRIP:CLOSE`, and `JOG:Z` with a physical King ($150\text{ mm}$) and Pawn ($170\text{ mm}$) to fine-tune grip heights.
8. **ESP32 Bring-Up (`COM7`):** Send `PING` and verify `PONG:ESP32_TUTOR_V1`. Test `EYES:RED`, `GESTURE:ILLEGAL`, `GESTURE:WIN_PLAYER`, and audio playback.
9. **Tray & Promotion Reserve Alignment:** Test `MOVETO:TRAY_W1` and `MOVETO:RES_Q1` to verify off-board reach and tune `TRAY_ORIGIN_X_MM` / `TRAY_ORIGIN_Y_MM` if needed.
10. **Origin Calibration (`a8`):** Manually position the gripper directly above square `a8` at startup and issue `SETPOS:a8`.
11. **Launch Application:** Run `python main.py` from `chess_robot/software/`.
12. **End-to-End Validation:** Play a test game on Easy mode, triggering a capture, castling, and promotion to verify all physical routines.

---

## 12. Safety Notes & Future Enhancements

### Safety Notes
* **Pinch Hazard:** NEMA 17 steppers and the moving gantry bridge can pinch fingers—keep hands clear of the board during the robot's turn.
* **Gripper Clamping Force:** The MG995 servo generates high torque at $0^\circ$; never place fingers between the gripper jaws during calibration.
* **Supply Polarity:** Double-check $12\text{ V}/24\text{ V}$ polarity before powering the DRV8825 drivers, and never disconnect a stepper motor while energized.

### Future Enhancements
* **X/Y Limit Switches:** Adding homing switches to the X and Y axes will eliminate the manual `SETPOS:a8` startup alignment step.
* **Interrupt-Driven Reed Matrix:** Wiring the MCP23017 `INTA`/`INTB` pins to Arduino Mega hardware interrupt pins to replace ~$33\text{ Hz}$ polling.
* **Hardware Emergency Stop:** Wiring a physical E-Stop mushroom button to the Uno's `ENABLE_PIN` (Pin 10) and stepper PSU rail.
* **Full Under-Promotion Reserve:** Adding dedicated off-board reserve slots for Rook, Bishop, and Knight promotions in `config.PROMOTION_RESERVE`.
* **Centipawn-Loss Accuracy Scoring:** Calling `ChessSession.evaluate_centipawns()` before and after every human move to compute live game accuracy via $\text{Accuracy} \approx 103.1 \times e^{-0.04 \times \text{centipawn\_loss}} - 3.1$.
