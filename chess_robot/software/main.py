"""
Chess Robotic Tutor and Training System
Main application entry point.

Run with:   python main.py

Ties together:
  serial_comm.RobotInterface   -> talks to the Mega / Uno / ESP32 boards
  chess_logic.ChessSession      -> rules engine + Stockfish + physical move planning
  database.Database             -> profiles & 30-day progress history
  tts_audio                     -> speech synthesis for the tutor's voice
  gui.ChessTutorGUI              -> touchscreen front-end

See BLUEPRINT.md section 9 "Software Architecture" for the full game-loop
sequence diagrams this file implements.
"""

import json
import threading
import time

import chess

import config
import tts_audio
from chess_logic import ChessSession
from database import Database
from gui import ChessTutorGUI
from serial_comm import RobotInterface


class AppController:
    """Owns all application state and runs the game loop on a background
    thread so the Kivy GUI thread is never blocked waiting on hardware."""

    def __init__(self):
        self.cfg = config
        self.db = Database(config.DB_PATH)
        self.robot = RobotInterface(config)
        self.session = None

        self.profile_id = None
        self.selected_mode = None
        self.status_text = "Connecting to robot..."
        self.move_log_text = ""

        self.puzzles = []
        self.puzzle_index = 0
        self.puzzle_solution = []
        self.puzzle_step = 0

        self._running = False
        self._game_thread = None

    # ---------------- Startup ----------------
    def connect_hardware(self):
        results = self.robot.connect_all()
        if all(results.values()):
            self.status_text = "All systems connected."
        else:
            missing = [k for k, v in results.items() if not v]
            self.status_text = f"WARNING: could not connect to: {', '.join(missing)}"
            return

        # There is no X/Y homing switch on the gantry (see uno_gantry.ino),
        # so the operator MUST physically align the gripper over square a8
        # before powering on. We then tell the firmware that's where it is.
        try:
            self.robot.gantry_setpos("a8")
        except Exception as e:
            self.status_text += f" | gantry SETPOS failed: {e}"

    def select_profile(self, name):
        self.profile_id = self.db.get_or_create_profile(name)

    # ---------------- Mode / level selection ----------------
    def start_standard_game(self, level):
        self.selected_mode = "Standard"
        self.status_text = f"Standard game started - {level}"
        self.move_log_text = ""
        self._running = True
        
        self._game_thread = threading.Thread(target=self._standard_game_loop, args=(level,), daemon=True)
        self._game_thread.start()

    def start_puzzle_mode(self):
        with open(self.cfg.PUZZLES_PATH) as f:
            self.puzzles = json.load(f)
        if not self.puzzles:
            self.status_text = "No puzzles found in puzzles.json"
            return
        self.puzzle_index = 0
        self.session = ChessSession(self.cfg, level="Hard")
        self._load_current_puzzle()
        self.move_log_text = ""
        self._running = True
        self._game_thread = threading.Thread(target=self._puzzle_loop, daemon=True)
        self._game_thread.start()

    def _load_current_puzzle(self):
        puzzle = self.puzzles[self.puzzle_index]
        self.session.board.set_fen(puzzle["fen"])
        self.puzzle_solution = puzzle["solution"]
        self.puzzle_step = 0

# ---------------- Standard game loop ----------------
    def _standard_game_loop(self, level):
        self.session = ChessSession(self.cfg, level=level)
        self.robot.eyes("BLUE")
        
        while self._running and not self.session.board.is_game_over():
            if self.session.board.turn == chess.WHITE:
                self._handle_human_turn()
            else:
                self._handle_robot_turn()
                
        if self._running:
            self._handle_game_end()


    def _handle_human_turn(self):
        self.status_text = "Your move - lift a piece to see legal squares."
        from_square = self._wait_for_pickup()
        if from_square is None:
            return

        quiet, capture = self.session.legal_destinations(from_square)
        self.robot.show_moves(quiet, capture)

        to_square = self._wait_for_dropoff()
        self.robot.clear_leds()
        if to_square is None:
            return

        move = self.session.find_move(from_square, to_square)
        if move is not None:
            self.session.push(move)
            self.move_log_text += f"You: {from_square} -> {to_square}\n"
        else:
            self.robot.gesture("ILLEGAL")
            self.status_text = "Illegal move - please return the piece and try again."

    def _wait_for_pickup(self, timeout=120):
        deadline = time.time() + timeout
        while self._running and time.time() < deadline:
            for sq, state in self.robot.poll_board_events():
                if state == "OPEN":
                    return sq
            time.sleep(0.05)
        return None

    def _wait_for_dropoff(self, timeout=120):
        deadline = time.time() + timeout
        while self._running and time.time() < deadline:
            for sq, state in self.robot.poll_board_events():
                if state == "CLOSED":
                    return sq
            time.sleep(0.05)
        return None

    def _handle_robot_turn(self):
        self.robot.gesture("THINKING")
        self.status_text = "Tutor is thinking..."

        move = self.session.best_move()
        explanation = self.session.describe_move(move)
        self.status_text = explanation
        self.move_log_text += f"Tutor: {explanation}\n"

        # Speak the explanation through the robot's own speaker BEFORE moving,
        # per the brief ("explain the best move... before make every moves").
        try:
            pcm = tts_audio.synthesize_to_pcm(explanation, self.cfg.TTS_SAMPLE_RATE)
            self.robot.speak_pcm(pcm)
        except Exception as e:
            self.status_text += f" (speech failed: {e})"

        plan = self.session.physical_plan_for_move(move)   # must run BEFORE push()
        for step in plan:
            self.robot.gantry_move_to(step["square"])
            if step["type"] == "PICK":
                self.robot.gantry_pick(step["piece"])
            else:
                self.robot.gantry_place(step["piece"])
        self.robot.gantry_home()

        self.session.push(move)
        self.robot.eyes("BLUE")

    def _handle_game_end(self):
        board = self.session.board
        result = "draw"
        if board.is_checkmate():
            # board.turn is the side that is checkmated (has no legal moves).
            if board.turn == chess.BLACK:
                result = "win"     # human (white) checkmated the tutor
                self.robot.win_green()
                self.robot.gesture("WIN_PLAYER")
            else:
                result = "loss"

        accuracy = 100.0   # placeholder metric - see BLUEPRINT.md section 9 for
                           # a real centipawn-loss-derived accuracy calculation
                           # using ChessSession.evaluate_centipawns() per move.
        self.db.record_game(self.profile_id, "Standard", self.session.level, result, accuracy)
        self.status_text = f"Game over: {result}"
        self.session.quit()

    # ---------------- Puzzle loop ----------------
    def _puzzle_loop(self):
        while self._running:
            self.status_text = f"Puzzle {self.puzzle_index + 1}/{len(self.puzzles)} - find the best move."
            from_square = self._wait_for_pickup()
            if from_square is None:
                continue

            quiet, capture = self.session.legal_destinations(from_square)
            self.robot.show_moves(quiet, capture)
            to_square = self._wait_for_dropoff()
            self.robot.clear_leds()
            if to_square is None:
                continue

            attempted = f"{from_square}{to_square}"
            expected = self.puzzle_solution[self.puzzle_step]
            if attempted == expected:
                move = self.session.find_move(from_square, to_square)
                if move:
                    self.session.push(move)
                self.puzzle_step += 1
                self.move_log_text += f"Correct: {attempted}\n"
                if self.puzzle_step >= len(self.puzzle_solution):
                    self.status_text = "Puzzle solved!"
                    self.db.record_game(self.profile_id, "Puzzle", None, "solved", 100.0)
                    self.puzzle_index = (self.puzzle_index + 1) % len(self.puzzles)
                    self._load_current_puzzle()
            else:
                self.robot.gesture("ILLEGAL")
                self.status_text = "Not quite - try again."
                self.db.record_game(self.profile_id, "Puzzle", None, "failed", 0.0)

    def end_session(self):
        self._running = False


def main():
    app_ctrl = AppController()
    app_ctrl.connect_hardware()
    ChessTutorGUI(app_ctrl).run()
    app_ctrl.robot.close_all()


if __name__ == "__main__":
    main()
