# Chess Robotic Tutor and Training System
## Master Engineering Blueprint

**Version 1.0 — prepared from the original hardware/process notes (`Chess_Board.pdf`) plus the engineering additions required to make the system actually buildable and playable.**

---

## Table of Contents

1. Executive Summary & System Overview
2. Assumptions, Clarifications & Flagged Ambiguities
3. Consolidated Bill of Materials
4. System Architecture
5. Mechanical Design & Coordinate System
6. Electrical Design (power, grounding, wiring tables)
7. Communication Protocol Specification
8. Firmware Architecture (Mega / Uno / ESP32)
9. Software Architecture (Python application)
10. Special Move Handling (captures, castling, en passant, promotion)
11. Calibration & Commissioning Procedure
12. Safety Notes
13. File Manifest
14. Future Enhancements

---

## 1. Executive Summary & System Overview

The system is a physical chess-playing and teaching robot built from three independent microcontrollers, each owning one subsystem, all coordinated by a Python application running on a laptop:

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

All three boards connect via independent **USB-Serial** links directly to the laptop (confirmed by the original notes: `COM3=Mega, COM7=ESP32, COM8=Uno`) — there is no wireless link anywhere in the system, which keeps the design simple and reliable.

**Subsystem responsibilities**

| Subsystem | MCU | Job |
|---|---|---|
| Chessboard | Arduino MEGA 2560 | Detects which square a piece is lifted from / placed on (reed switches); lights legal-move hints and the checkmate celebration (NeoPixels) |
| Gantry | Arduino UNO | Physically picks up and places pieces anywhere on the board (and on the captured-piece tray / promotion reserve) |
| Robotic Tutor | ESP32 | Animatronic gestures (arms, wrist, head), "eyes" (NeoPixels), and spoken explanations through a speaker |
| Orchestrator | Laptop (Python) | Chess rules + engine strength, game/puzzle modes, player profiles, progress graphing, and all decision-making that ties the three boards together |

**Design philosophy:** the Mega operates *autonomously* — it never waits to be asked, it just continuously reports board state changes. The Uno and ESP32 operate in a *synchronous command → ACK* style — the PC sends one command, waits for completion, then sends the next. This is a deliberate simplification: chess is turn-based, so there is no benefit to the added complexity of asynchronous motion control, and a synchronous design is dramatically easier to get right and to debug.

---

## 2. Assumptions, Clarifications & Flagged Ambiguities

The original notes are excellent for capturing *intent* but leave some physical details ambiguous, contain a couple of likely typos, and don't address some situations a real chess game requires (captures, castling, en passant, promotion need somewhere physical to put/take pieces). Every one of these is called out here explicitly, and every corresponding constant in the code is commented with a pointer back to this table so nothing is hidden.

| # | Item in original notes | Issue | Resolution used in this blueprint |
|---|---|---|---|
| 1 | "Distance between square midpoints is 53 cm" | 53 cm would make the board over 4 metres across — almost certainly a typo for **53 mm** (a normal chess square) | Used `53.0 mm` as `SQUARE_PITCH_MM` in `uno_gantry.ino`. **Measure your real board and correct this constant before running.** |
| 2 | "T8 Lead screw full set" | T8 leadscrews come in several lead variants (2/4/8 mm) | Assumed an 8 mm lead (`Z_LEAD_MM`). Check your specific screw's datasheet/markings and correct if different. |
| 3 | "MPI 5008 V4.9" display module | Not a part number we can verify; the same page states the display "connects to the computer by HDMI and USB micro port" | Treated as a generic HDMI+USB touchscreen monitor wired straight to the **laptop**, not to any microcontroller. The Python GUI (Kivy) renders directly to it — no embedded display driver code is needed on any board. |
| 4 | "5 DC current jack" in Robotic Tutor BOM | Ambiguous: quantity 5, or a 5V DC jack? | Interpreted as **one 5V DC barrel jack** (power input connector) — quantity "5" almost certainly refers to 5 **volts**, not five jacks. |
| 5 | "10 uhi Inductor", "100, 10 capacitors", "Diaode" | Typos for 10 µH inductor, 100 µF/10 µF capacitors, diode | These are standard supporting components for the MAX98357A audio amplifier's power supply filtering — included in the BOM and power design as such, no functional change needed. |
| 6 | Captured pieces (any capture, anywhere) | **Not addressed at all** in the original notes — a robot cannot simply delete a piece from the board | Added an **off-board captured-piece tray** (named virtual positions `TRAY_W1..TRAY_W16` / `TRAY_B1..TRAY_B16`) that the gantry firmware understands natively. See section 10. |
| 7 | Pawn promotion | **Not addressed** — the robot cannot conjure a new piece out of thin air | Added a **promotion reserve** — a spare queen kept at a fixed off-board position (`RES_Q1`) that the gantry brings on when a pawn promotes. Default covers queen promotion only (by far the most common); extend `config.PROMOTION_RESERVE` and the firmware's tray table if you want full under-promotion support. |
| 8 | "CNS divided into 1/16 micro steps" | Typo for "CNC" | Read as: the stepper drivers are configured for 1/16 microstepping. Implemented in the step/mm math (`MICROSTEPS = 16`) — set the matching physical microstep-select jumpers on your DRV8825 boards (MS1=0, MS2=0, MS3=1) to match. |
| 9 | Pick/place descend depth ("15 cm for king/queen, 17 cm for all other pieces") | Spec only mentions *pickup* depth | Assumed the same depth applies symmetrically to *placing* a piece of that type (the depth is a property of the piece's height, not the action) — implemented identically for PICK and PLACE in `uno_gantry.ino`. |
| 10 | X/Y axis homing | Only **one** limit switch exists in the BOM, and the notes say it homes Z | X and Y have **no homing switches**. The firmware tracks position purely by step-counting from a known starting point, set once via a `SETPOS:a8` command after the operator manually aligns the gripper to square a8 at power-up. See section 11 (Commissioning) and section 14 (recommended future enhancement: add X/Y limit switches). |
| 11 | Motor/servo direction signs | Not specified (depends on motor wiring polarity, which can't be predicted) | Exposed as `X_DIR_SIGN` / `Y_DIR_SIGN` calibration constants plus a `JOG` command for live testing — see section 11. |

---

## 3. Consolidated Bill of Materials

All three original BOMs merged into one, plus the additions this blueprint requires for a complete, working system. Prices below are exactly as given in the source document (assumed to be in LKR, unconfirmed) and are **not** re-priced.

### 3.1 Chess Board

| Component | Qty | Unit cost |
|---|---|---|
| Reed switch | 64 | 7680 (total) |
| MCP23017 I/O expander | 4 | 3800 |
| NeoPixel (WS2812) | 64 | 750 |
| Chess pieces | 32 | 2500 |
| Chess board | 1 | 12500 |
| Arduino MEGA 2560 | 1 | 4800 |

### 3.2 X-Y-Z Gantry

| Component | Qty | Unit cost |
|---|---|---|
| V-slot gantry plate set | 3 | 4950 |
| Wire ties | 10 | 100 |
| T8 lead screw, full set | 1 | 1880 |
| MG995 servo (gripper) | 1 | 1150 |
| Robotic gripper | 1 | 1300 |
| Horizontal limit switch | 1 | 160 |
| Box bar | 4 | 1300 |
| CNC controller board | 1 | 450 |
| DRV8825 motor driver | 4 | 1600 |
| Arduino UNO | 1 | 1300 |
| NEMA17 stepper motor | 4 | 9200 |
| GT2 20T timing pulley | 6 | 720 |
| GT2 timing belt, 5 m | 2 | 2250 |
| NEMA17 motor holder | 2 | 560 |
| 2020 V-slot profile | 4 | 8640 |
| Angle bracket | 4 | 800 |

### 3.3 Robotic Tutor

| Component | Qty | Unit cost |
|---|---|---|
| MG90S servo | 4 | 2320 |
| Display module (HDMI+USB touch, "MPI 5008 V4.9") | 1 | 10950 |
| NeoPixel (eyes) | 5 | 65 |
| Custom PCB | 1 | 13000 |
| ESP32 dev board | 1 | 1400 |
| 3D-printed enclosure | 1 | 20000 |
| 3 W / 4 Ω speaker | 1 | 130 |
| 10 µH inductor | 1 | 700 |
| 100 µF / 10 µF capacitors | 2 | — |
| MAX98357A I2S amplifier | 1 | — |
| Protection diode | — | — |
| 3.3 V regulator | — | — |
| Logic level shifter | — | — |
| 5 V DC barrel jack | 1 | — |

### 3.4 Additions required by this blueprint (not in the original BOM)

| Component | Qty | Why |
|---|---|---|
| 5V / 4A+ switching PSU | 1 | Dedicated supply for the 64-NeoPixel chessboard matrix — must **not** share the Arduino's onboard 5V rail |
| 12V (or 24V) PSU for steppers | 1 | DRV8825 motor supply — sized to your NEMA17 current rating × 4 motors with headroom |
| 5V/3A linear or switching PSU for servos | 1 | Dedicated rail for MG995 + 4× MG90S; servos draw current spikes that will brown out shared logic rails |
| 1000 µF electrolytic capacitor | 1 | Across the NeoPixel strip's power input, standard best practice to absorb inrush current |
| 300–500 Ω resistor | 1 | In series with the NeoPixel data line, standard signal-integrity practice |
| Captured-piece tray (physical) | 1 | Off-board holding area for captured pieces — see section 10 |
| Spare queen (+ optional R/B/N) | 1+ | Promotion reserve piece(s) — see section 10 |
| Common ground bus / star-ground point | 1 | All supplies and all three boards must share one reference ground |

---

## 4. System Architecture

### 4.1 Communication topology

Three independent USB-CDC serial links, one per board, all terminating at the laptop. No board talks to another board directly — the Python app is the single source of truth for game state and the only thing that ever issues commands.

### 4.2 Two operating styles, by design

| Board | Style | Why |
|---|---|---|
| Mega (chessboard) | **Autonomous event stream.** Continuously polls all 64 reed switches (~33 Hz) and reports every state change unprompted. Also accepts LED commands at any time. | The PC needs to know *immediately* when a human lifts or places a piece — this can happen at any moment, not on request. |
| Uno (gantry), ESP32 (tutor) | **Synchronous command/ACK.** Idle until commanded; a motion or gesture command blocks the board's main loop until physically complete, then sends exactly one `ACK`/`ERR` line. The PC always waits for that response before sending the next command. | Motion sequencing only ever needs to happen one step at a time during the robot's own turn — there's nothing to gain from overlapping commands, and a strictly synchronous protocol is far simpler to get reliably correct. |

### 4.3 End-to-end move sequence (robot's turn)

1. PC asks Stockfish for the best move at the current difficulty.
2. PC builds a human-readable explanation and synthesizes it to speech (offline TTS).
3. PC streams the speech audio to the ESP32, which plays it through the onboard speaker — **before** any physical motion, per the original "explain the best move… before make every move" requirement.
4. PC decomposes the chess move into an ordered list of physical actions (see section 10) and sends them to the Uno one at a time, waiting for each ACK.
5. Uno always returns the gripper to the home position (square a8) after the sequence completes.
6. PC updates its internal board state only after the physical sequence is confirmed complete.

### 4.4 End-to-end move sequence (human's turn)

1. Human lifts a piece → Mega reports `SQEVT:<square>:OPEN`.
2. PC looks up that piece's legal destinations and sends `SHOWMOVES` to the Mega (quiet moves in light blue, capture squares in red) — this is the "tutor" hint feature.
3. Human places a piece down somewhere → Mega reports `SQEVT:<square>:CLOSED`.
4. PC clears the LEDs and checks whether the resulting move is legal.
   - **Legal:** game state updates, turn passes to the robot.
   - **Illegal:** ESP32 plays the "illegal move" gesture (right arm + wrist raise, red eyes) and the GUI prompts the player to undo it.

---

## 5. Mechanical Design & Coordinate System

### 5.1 Axis convention (exactly as specified in the original notes)

- The human sits in front of the robot; square **a8** is on the robot's right side, and is the gripper's **default/home position**.
- **Files (a–h)** are the robot's **Y axis**.
- **Ranks (1–8)** are the robot's **X axis**.
- a8 is the coordinate-system **origin (0, 0)**.

### 5.2 Step/mm calibration math (implemented in `uno_gantry.ino`)

```
XY axes (GT2 belt, 20T pulley, 2mm pitch):
   mm per motor revolution = 20 teeth × 2 mm = 40 mm
   microsteps per revolution = 200 (1.8° motor) × 16 (microstepping) = 3200
   → steps per mm = 3200 / 40 = 80 steps/mm

Z axis (T8 leadscrew, assumed 8mm lead — VERIFY):
   microsteps per revolution = 3200 (same as above)
   → steps per mm = 3200 / 8 = 400 steps/mm

Distance between two squares = SQUARE_PITCH_MM (53mm, VERIFY — see assumption #1)
   → steps between adjacent squares (XY) = 53 × 80 = 4240 steps
```

### 5.3 Gripper descend depths (from the Z-home / fully-retracted position)

| Piece type | Depth |
|---|---|
| King, Queen | 150 mm (15 cm) |
| All other pieces (Pawn, Rook, Bishop, Knight) | 170 mm (17 cm) |

The gripper **always** returns to Z = 0 (home height) before any X/Y travel, so it never drags across other pieces while transiting the board.

### 5.4 Gripper jaw angles

| State | Servo angle |
|---|---|
| Closed / holding a piece | 0° |
| Open / clear of a piece | 120° |

### 5.5 Off-board physical layout (captured-piece tray & promotion reserve)

Not present in the original drawings — this blueprint defines a simple grid of named slots beyond the playing area that the gantry firmware understands natively (see `tryTraySlot()` in `uno_gantry.ino`):

- `TRAY_W1`…`TRAY_W16` — white pieces captured by the tutor, in an 8-per-row grid
- `TRAY_B1`…`TRAY_B16` — black pieces captured by the human, in an 8-per-row grid, offset from the white tray by `TRAY_SIDE_GAP_MM`
- `RES_Q1` — spare queen for pawn promotion

All five geometry constants (`TRAY_ORIGIN_X_MM`, `TRAY_ORIGIN_Y_MM`, `TRAY_SLOT_PITCH_MM`, `TRAY_ROWS_PER_SIDE`, `TRAY_SIDE_GAP_MM`, `RESERVE_Q_X_MM`, `RESERVE_Q_Y_MM`) live at the top of `uno_gantry.ino` — lay your physical tray out within the gantry's reach envelope and adjust these to match.

---

## 6. Electrical Design

### 6.1 Power & grounding plan (critical — most robot build failures are power problems, not code problems)

| Rail | Powers | Notes |
|---|---|---|
| 5V / 4A+ | 64× NeoPixel chessboard matrix | **Dedicated supply, not the Arduino's onboard 5V.** Add a 1000 µF cap across the strip's power input and a 300–500 Ω resistor on the data line (standard NeoPixel practice). |
| 12V (or 24V) | 4× NEMA17 via DRV8825 | Set per your motor's rated current — see Vref formula below. |
| 5V / 3A | MG995 gripper servo + 4× MG90S tutor servos | Servos draw sharp current spikes; an undersized or shared rail causes brownouts that look like "random" motion glitches. |
| 5V (USB or regulated) | Arduino Mega, Arduino UNO logic | |
| 5V → 3.3V (onboard regulator) | ESP32 logic | BOM's "3.3V Regulator" / "Logic Level Shifter" protect this rail and any 3.3V↔5V signal interface if you later add direct GPIO links between boards (the design here avoids needing any, since all three boards only ever talk to the laptop). |

**All supplies must share one common ground** (star-ground recommended) — float grounds between supplies are a very common source of intermittent NeoPixel flicker and erratic stepper behaviour.

### 6.2 DRV8825 current-limit (Vref) calculation

```
Vref = Imotor × 0.8     (for drivers with a 0.1Ω current-sense resistor, the common default)
```
Look up your NEMA17's rated current (typically 1.2–1.7 A) and set each of the 4 drivers' trim pots accordingly, **measuring with a multimeter** at the trim-pot reference point before connecting any motor.

### 6.3 Arduino MEGA — Chessboard wiring

| Signal | Mega pin |
|---|---|
| I2C SDA | 20 |
| I2C SCL | 21 |
| NeoPixel data | 6 (through 330Ω resistor) |
| MCP23017 #1 (squares 0–15) | I2C address 0x20 |
| MCP23017 #2 (squares 16–31) | I2C address 0x21 |
| MCP23017 #3 (squares 32–47) | I2C address 0x22 |
| MCP23017 #4 (squares 48–63) | I2C address 0x23 |

Each reed switch wires between its MCP23017 pin and ground; internal pull-ups are enabled in firmware, so a closed (occupied) square reads LOW.

### 6.4 Arduino UNO — Gantry wiring

| Signal | Uno pin |
|---|---|
| X1 STEP / DIR | 2 / 3 |
| X2 STEP / DIR | 4 / 5 |
| Y STEP / DIR | 6 / 7 |
| Z STEP / DIR | 8 / 9 |
| Driver ENABLE (shared, active LOW) | 10 |
| Z limit switch | 11 (INPUT_PULLUP) |
| Gripper servo (MG995) | 12 |
| Status LED | 13 (onboard) |

X1 and X2 drive the two motors on either side of the gantry beam — they are always given identical step targets so the beam stays square; no special CNC-shield "A axis" wiring trick is needed since each DRV8825 simply gets its own STEP/DIR pair directly from the Uno.

### 6.5 ESP32 — Robotic Tutor wiring

| Signal | ESP32 GPIO |
|---|---|
| Right arm servo (MG90S) | 13 |
| Right wrist servo (MG90S) | 4 |
| Left arm servo (MG90S) | 16 |
| Head servo (MG90S) | 17 |
| Eyes NeoPixel data | 5 |
| MAX98357A BCLK | 26 |
| MAX98357A LRC/WS | 25 |
| MAX98357A DIN | 22 |

Pins 0, 2, 12, 15 (boot-strapping) and 6–11 (internal flash) are deliberately avoided.

---

## 7. Communication Protocol Specification

Plain ASCII, one command or event per line, `\n`-terminated, 115200 baud on all three links.

### 7.1 Handshake (all boards)

| PC sends | Board replies |
|---|---|
| `PING` | `PONG:MEGA_CHESSBOARD_V1` / `PONG:UNO_GANTRY_V1` / `PONG:ESP32_TUTOR_V1` |

This is how `serial_comm.py` auto-discovers which physical COM port belongs to which board, regardless of USB enumeration order.

### 7.2 Mega (Chessboard) commands

| Command | Effect | Reply |
|---|---|---|
| `SHOWMOVES:<csv blue>:<csv red>` | Light given squares blue (quiet moves) / red (captures); clears everything else | `ACK:SHOWMOVES` |
| `CLEARLEDS` | All LEDs off | `ACK:CLEARLEDS` |
| `WINGREEN` | All 64 LEDs green (checkmate celebration) | `ACK:WINGREEN` |
| `GETSTATE` | Full 64-bit occupancy snapshot | `STATE:<16 hex chars>` |
| *(unsolicited, anytime)* | — | `SQEVT:<square>:OPEN` / `SQEVT:<square>:CLOSED` |

### 7.3 Uno (Gantry) commands

| Command | Effect | Reply |
|---|---|---|
| `HOME` | Home Z against the limit switch, then move X/Y to a8 | `ACK:HOME` |
| `SETPOS:<square>` | Tell the firmware "the gripper is physically here right now" (calibration) | `ACK:SETPOS:<square>` |
| `MOVETO:<square>` | Move X/Y over the given square (or tray/reserve name) | `ACK:MOVETO:<square>` |
| `PICK:<piece letter>` | Descend to the depth for that piece type, close the gripper, retract | `ACK:PICK` |
| `PLACE:<piece letter>` | Descend, open the gripper, retract | `ACK:PLACE` |
| `JOG:<X/Y/Z>:<signed microsteps>` | Manual nudge — calibration only | `ACK:JOG` |
| `GRIP:<OPEN/CLOSE>` | Manual gripper test | `ACK:GRIP` |

### 7.4 ESP32 (Tutor) commands

| Command | Effect | Reply |
|---|---|---|
| `EYES:<BLUE/RED/GREEN/OFF>` | Set eye colour | `ACK:EYES` |
| `GESTURE:<IDLE/ILLEGAL/WIN_PLAYER/THINKING>` | Play a gesture | `ACK:GESTURE` |
| `AUDIO:<byte count>` then raw PCM bytes | Buffer and play 16kHz/16-bit mono speech | `ACK:AUDIO` |

### 7.5 Error reporting (all boards)

Any unrecognised command or failure condition replies `ERR:<reason>` instead of an `ACK` — `serial_comm.py` raises a Python exception on any `ERR:` so failures are never silently swallowed.

---

## 8. Firmware Architecture

| File | Library dependencies | Core responsibility |
|---|---|---|
| `firmware/mega_chessboard/mega_chessboard.ino` | `Wire`, `Adafruit_MCP23017` (or `Adafruit_MCP23X17`), `Adafruit_NeoPixel` | Reed-switch polling + event reporting; NeoPixel hint/celebration rendering |
| `firmware/uno_gantry/uno_gantry.ino` | `AccelStepper`, `Servo` | Coordinated 3-axis stepper motion, Z homing, gripper control, square/tray coordinate math |
| `firmware/esp32_tutor/esp32_tutor.ino` | `ESP32Servo`, `Adafruit_NeoPixel`, ESP-IDF `driver/i2s.h` | Gesture servos, eye colour, I2S audio playback through the MAX98357A |

Each `.ino` file is self-contained, heavily commented, and has every calibration constant grouped at the top of the file with an explicit "verify on your build" note where the source spec was ambiguous (cross-referenced to section 2 above).

---

## 9. Software Architecture

| File | Role |
|---|---|
| `software/config.py` | Every tunable constant in one place — serial ports, Stockfish path/difficulty mapping, tray geometry names, TTS settings |
| `software/serial_comm.py` | `BoardConnection` (one board, auto-discovery + ACK/event handling) and `RobotInterface` (clean unified API over all three boards) |
| `software/chess_logic.py` | `ChessSession` — wraps python-chess + Stockfish; legal-move lookups for LED hints; `physical_plan_for_move()` decomposes any move (including captures/castling/en passant/promotion) into an ordered PICK/PLACE list |
| `software/database.py` | SQLite profiles + game history; `last_30_days_accuracy()` feeds the progress graph directly |
| `software/tts_audio.py` | Offline TTS (pyttsx3) → 16kHz/16-bit mono PCM, ready to stream to the ESP32 |
| `software/gui.py` | Kivy touchscreen UI: Profile → Mode → Level → Game → Graph screens |
| `software/main.py` | `AppController` — the game loop that ties everything together, run on a background thread so the GUI stays responsive |
| `software/puzzles.json` | Sample puzzle data (FEN + solution move list) for Puzzle mode — extend with a larger puzzle set (e.g. an exported Lichess puzzle database) as needed |
| `software/requirements.txt` | pip dependencies (Stockfish binary and ffmpeg must be installed separately — see comments in the file) |

### 9.1 Difficulty mapping

| Level | Stockfish Skill Level | Search depth | Time budget |
|---|---|---|---|
| Easy | 3 | 4 | 200 ms |
| Medium | 10 | 10 | 800 ms |
| Hard | 20 (max) | 22 | 3000 ms |

"Hard" deliberately uses near-maximum engine strength, per the brief's "if we select the level as hard it should be hard seriously."

### 9.2 Progress metric (the "improvement over 30 days" graph)

`database.py` stores one `accuracy` value (0–100) per completed game. `main.py` currently records a placeholder value — for a genuine accuracy metric, call `ChessSession.evaluate_centipawns()` before and after each of the player's moves and convert centipawn loss to an accuracy percentage (a common formula is `accuracy ≈ 103.1 × e^(-0.04 × centipawn_loss) − 3.1`, clipped to 0–100). The graph screen (`gui.py` `GraphScreen`) already plots whatever is in the database — only the *scoring* needs filling in once you decide exactly which accuracy formula you prefer.

### 9.3 Puzzle data format

```json
{
  "title": "Mate in 1 - back rank",
  "fen": "<starting position>",
  "solution": ["e1e8"]
}
```
`solution` is a list because multi-move puzzles are supported — `main.py`'s puzzle loop advances through it one human move at a time.

---

## 10. Special Move Handling

This section is the single biggest engineering gap in the original spec, since it only describes the 8×8 board and says nothing about what happens when a piece needs to leave it. `ChessSession.physical_plan_for_move()` resolves every case:

| Case | Physical handling |
|---|---|
| **Ordinary move** | One PICK at the origin square, one PLACE at the destination |
| **Capture** | Captured piece is PICKed from its square and PLACEd into the next free tray slot (`TRAY_W*`/`TRAY_B*`) **before** the capturing piece moves |
| **En passant** | Same as a capture, but the captured pawn's square is computed separately from the destination square (`python-chess`'s `board.is_en_passant()` makes this exact) — the code is tested against this case explicitly |
| **Castling** | Decomposed into two ordinary relocations: king first, then the corresponding rook, to the FIDE-correct squares for king-side/queen-side, either colour |
| **Promotion** | The pawn is retired to the tray (it no longer exists as a pawn), then the reserve piece (`RES_Q1` by default) is PICKed and PLACEd on the destination square |

**Known limitation, by design:** the default promotion reserve only covers queen promotion (the overwhelming majority of real promotions). If you want the robot to also handle promoting to a rook, bishop, or knight, add the physical reserve piece + a named slot in `uno_gantry.ino`'s `tryTraySlot()`, then add the matching entry to `config.PROMOTION_RESERVE` — the Python logic already supports it generically.

**Tray capacity:** 16 slots per side (32 total) covers every piece on the board being captured, which can never actually happen simultaneously for one side (max 15 captures per side), so this has headroom built in.

---

## 11. Calibration & Commissioning Procedure

Run through this **in order** on a freshly-wired robot, before ever starting a real game:

1. **Power-up check.** Verify all rails independently with a multimeter before connecting any board (5V NeoPixel rail, 12/24V stepper rail, 5V servo rail). Confirm common ground across all of them.
2. **DRV8825 Vref tuning.** Set each of the 4 drivers per section 6.2, motors disconnected.
3. **Microstep jumpers.** Confirm MS1/MS2/MS3 give 1/16 microstepping on all 4 drivers (see section 2, item 8).
4. **Flash all three boards** with their respective `.ino` files via the Arduino IDE (Mega/Uno) and the ESP32 board package (ESP32).
5. **Mega bring-up:** open the Arduino Serial Monitor at 115200 baud, send `PING`, confirm `PONG:MEGA_CHESSBOARD_V1`. Place/remove a piece on a few squares and confirm `SQEVT` lines appear correctly. Send `SHOWMOVES:e4,e5:d5` and confirm the right squares light blue/red.
6. **Uno bring-up:** send `PING`, confirm `PONG:UNO_GANTRY_V1`. With the gantry clear of obstructions, send `HOME` and confirm Z retracts cleanly against the limit switch. Use `JOG:X:200` / `JOG:Y:200` to confirm each axis moves the expected physical direction — **flip `X_DIR_SIGN`/`Y_DIR_SIGN` in the firmware and re-flash if a direction is backwards**, then re-measure actual mm-per-command-vs-expected to refine `SQUARE_PITCH_MM` and `Z_LEAD_MM` against your real hardware (see assumptions #1–2).
7. **Gripper calibration:** with a king and a pawn on hand, use `GRIP:OPEN`/`GRIP:CLOSE` and `JOG:Z` to confirm `DEPTH_KING_QUEEN_MM` and `DEPTH_OTHER_MM` actually reach a good grip height for your physical pieces; adjust if your pieces differ from a standard set.
8. **ESP32 bring-up:** send `PING`, confirm `PONG:ESP32_TUTOR_V1`. Test `EYES:RED`, `GESTURE:ILLEGAL`, `GESTURE:WIN_PLAYER`. Test `AUDIO:<n>` with a short known PCM clip to confirm the speaker works before relying on live TTS.
9. **Tray & reserve calibration:** physically place the captured-piece tray and the spare queen, then use `MOVETO:TRAY_W1`, `MOVETO:RES_Q1` etc. to confirm the gantry actually reaches them; adjust `TRAY_ORIGIN_X_MM`/`TRAY_ORIGIN_Y_MM`/etc. in `uno_gantry.ino` to match.
10. **Origin calibration:** physically align the gripper directly over square a8, then in the Python app (or manually over serial) send `SETPOS:a8` — this must happen once every power-cycle, since there is no X/Y homing switch (assumption #10).
11. **Software setup:** `pip install -r requirements.txt`, install a Stockfish binary and set its path in `config.py`, install `ffmpeg` for speech, then run `python main.py`.
12. **End-to-end test:** play a full game on Easy, deliberately triggering at least one capture, one castle, and (if you have time) one promotion, to confirm every special case in section 10 works on your physical build before trusting it unsupervised.

---

## 12. Safety Notes

- NEMA17 steppers and the gantry beam can pinch fingers — keep the play area clear of hands during the robot's turn, and consider an emergency-stop button wired to cut motor power (the Uno has spare digital pins for this — see section 14).
- The MG995 gripper has real clamping force — do not place fingers between the jaws during testing.
- Verify polarity before connecting any PSU; a reversed 12/24V supply to the DRV8825 boards will destroy them (and possibly the motors).
- Keep the NeoPixel 5V supply's ground tied to the Mega's ground — floating grounds between a separate LED PSU and the Arduino are a common cause of erratic, hard-to-diagnose behaviour.

---

## 13. File Manifest

```
chess_robot/
├── BLUEPRINT.md                          <- this document
├── firmware/
│   ├── mega_chessboard/mega_chessboard.ino
│   ├── uno_gantry/uno_gantry.ino
│   └── esp32_tutor/esp32_tutor.ino
└── software/
    ├── config.py
    ├── serial_comm.py
    ├── chess_logic.py
    ├── database.py
    ├── tts_audio.py
    ├── gui.py
    ├── main.py
    ├── puzzles.json
    └── requirements.txt
```

Each `.ino` file is a complete, standalone Arduino sketch — open the single file in the Arduino IDE (or place its containing folder anywhere, since the folder name matches the file name as Arduino requires) and flash it to the corresponding board. The `software/` folder is a complete Python application — run `python main.py` from inside that folder after installing `requirements.txt`.

---

## 14. Future Enhancements

Not required for a working system, but worth knowing about as you iterate:

- **X/Y limit switches.** Currently only Z homes against a switch; adding switches to X and Y would remove the manual `SETPOS:a8` calibration step entirely and make the system self-recovering after a power loss mid-game.
- **Interrupt-driven reed switches.** The Mega currently polls at ~33 Hz, which is more than fast enough for human reaction times, but wiring the MCP23017s' INTA pins to the Mega's hardware interrupt pins would make square-state reporting effectively instant and reduce I2C bus traffic.
- **Emergency stop.** A physical E-stop button wired to the Uno's shared `ENABLE_PIN` (or directly cutting the stepper PSU) for instant motion-halt during testing or in case of a jam.
- **Full under-promotion support.** Add physical reserve rooks/bishops/knights and extend `config.PROMOTION_RESERVE` (the Python logic already supports this generically — see section 10).
- **Larger puzzle bank.** Swap the bundled 3-puzzle sample file for an imported Lichess puzzle database export for a much larger Puzzle-mode library.
- **Real accuracy scoring.** Wire up `ChessSession.evaluate_centipawns()` into the game loop to replace the placeholder accuracy value with a genuine centipawn-loss-derived score (formula suggested in section 9.2).
