"""
Chess Robotic Tutor and Training System
Central configuration. Tune every value here to match your physical
build - nothing else in the software package should need editing for a
standard setup.

See BLUEPRINT.md for the full rationale behind each setting.
"""

# ---------------------------------------------------------------------
# Serial ports.
# Leave as None to let serial_comm.py auto-detect each board by its
# PING/PONG handshake (recommended - immune to COM port renumbering).
# Set explicitly only if you want to skip auto-detection, e.g. on
# Windows: PORT_MEGA = "COM3", on Linux: PORT_MEGA = "/dev/ttyACM0".
# ---------------------------------------------------------------------
PORT_MEGA = None     # Chessboard board   -> identifies itself as MEGA_CHESSBOARD_V1
PORT_UNO = None      # Gantry board       -> identifies itself as UNO_GANTRY_V1
PORT_ESP32 = None    # Robotic tutor board -> identifies itself as ESP32_TUTOR_V1
BAUD_RATE = 115200
SERIAL_TIMEOUT_S = 2.0
LOSE_SOUND_MP3 = "checkmate.mp3"

# ---------------------------------------------------------------------
# Chess engine (Stockfish via the UCI protocol through python-chess).
# Download a Stockfish binary for your OS and point this at it.
# ---------------------------------------------------------------------
STOCKFISH_PATH = r"C:\chess_robot\stockfish.exe"   # <-- CHANGE THIS

# Difficulty mapping. "Hard" intentionally uses (near) full engine
# strength per the brief ("if we select hard it should be hard seriously").
LEVEL_SETTINGS = {
    "Easy":   {"skill": 3,  "depth": 4,  "time_ms": 200},
    "Medium": {"skill": 10, "depth": 10, "time_ms": 800},
    "Hard":   {"skill": 20, "depth": 22, "time_ms": 3000},
}

# ---------------------------------------------------------------------
# Local database (player profiles + game history + the 30-day graph).
# ---------------------------------------------------------------------
DB_PATH = "chess_tutor.db"

# ---------------------------------------------------------------------
# Text-to-speech / audio streamed to the ESP32's speaker.
# Must stay within the ESP32 firmware's AUDIO_BUF_MAX (64000 bytes).
# ---------------------------------------------------------------------
TTS_SAMPLE_RATE = 16000
AUDIO_CHUNK_MAX_BYTES = 60000

# ---------------------------------------------------------------------
# Captured-piece tray & promotion reserve (off-board physical storage).
# These names must exactly match the special-position table in
# firmware/uno_gantry/uno_gantry.ino (tryTraySlot()).
# ---------------------------------------------------------------------
CAPTURED_TRAY_SLOTS_PER_SIDE = 16
PROMOTION_RESERVE = {
    "Q": "RES_Q1",   # spare queen kept off-board for promotions.
    # If you want full under-promotion support, add physical reserve
    # slots for R/B/N on the gantry firmware and list them here too.
}

# ---------------------------------------------------------------------
# Puzzle mode data file (see software/puzzles.json for the format).
# ---------------------------------------------------------------------
PUZZLES_PATH = "puzzles.json"
