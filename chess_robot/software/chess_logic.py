"""
Chess Robotic Tutor and Training System
Chess rules engine wrapper (python-chess + Stockfish) and the "physical
move planner" that turns an abstract chess.Move into the exact ordered
sequence of PICK/PLACE actions the gantry must perform.

This is where the four special-move cases that the original hardware
spec did not address are handled explicitly:
  - captures            -> captured piece is relocated to an off-board tray
  - en passant captures  -> the ACTUAL captured square differs from the
                            destination square; handled correctly here
  - castling             -> decomposed into two ordinary relocations (king,
                            then rook)
  - promotion             -> the pawn is retired to the tray and a reserve
                            piece (e.g. a spare queen) is brought on from
                            its dedicated off-board position
See BLUEPRINT.md section 10 "Special Move Handling" for the full design
rationale and the physical tray layout these square names refer to.
"""

import chess
import chess.engine


class ChessSession:
    """Wraps a python-chess Board + a Stockfish engine instance for one game."""

    PIECE_NAMES = {
        chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
        chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
    }

    def __init__(self, cfg, level="Medium"):
        self.cfg = cfg
        self.board = chess.Board()
        self.engine = chess.engine.SimpleEngine.popen_uci(cfg.STOCKFISH_PATH)
        self._tray_counters = {chess.WHITE: 0, chess.BLACK: 0}
        self.level = None
        self._limit = None
        self.set_level(level)

    def set_level(self, level):
        settings = self.cfg.LEVEL_SETTINGS[level]
        self.level = level
        self.engine.configure({"Skill Level": settings["skill"]})
        self._limit = chess.engine.Limit(depth=settings["depth"], time=settings["time_ms"] / 1000.0)

    # ------------------------------------------------------------------
    # Legal-move lookups, used to drive the LED "hint" squares the moment
    # a human player lifts a piece off the physical board.
    # ------------------------------------------------------------------
    def legal_destinations(self, square_name):
        """Returns (quiet_squares, capture_squares) for the piece sitting
        on square_name, e.g. for lighting legal moves in blue/red."""
        sq = chess.parse_square(square_name)
        quiet, capture = [], []
        for move in self.board.legal_moves:
            if move.from_square == sq:
                dest = chess.square_name(move.to_square)
                if self.board.is_capture(move):
                    capture.append(dest)
                else:
                    quiet.append(dest)
        return quiet, capture

    def find_move(self, frm, to, promotion=None):
        for move in self.board.legal_moves:
            if (chess.square_name(move.from_square) == frm and
                    chess.square_name(move.to_square) == to):
                if promotion is not None and move.promotion != promotion:
                    continue
                return move
        return None

    def is_legal_human_move(self, frm, to):
        return self.find_move(frm, to) is not None

    # ------------------------------------------------------------------
    # Tutor speech.
    # ------------------------------------------------------------------
    def describe_move(self, move):
        san = self.board.san(move)
        piece = self.board.piece_at(move.from_square)
        name = self.PIECE_NAMES.get(piece.piece_type, "piece")
        frm = chess.square_name(move.from_square)
        to = chess.square_name(move.to_square)
        verb = "captures on" if self.board.is_capture(move) else "moves to"
        return f"I will move my {name} from {frm}. It {verb} {to}. The notation is {san}."

    # ------------------------------------------------------------------
    # Physical execution planning.
    # ------------------------------------------------------------------
    def physical_plan_for_move(self, move):
        """
        Decomposes a chess.Move into an ordered list of physical actions.
        Each action is a dict: {"type": "PICK"|"PLACE", "square": "e4", "piece": "Q"}
        IMPORTANT: must be called BEFORE self.board.push(move) - it reads
        the pre-move board state to know what is being captured.
        """
        board = self.board
        frm = chess.square_name(move.from_square)
        to = chess.square_name(move.to_square)
        piece = board.piece_at(move.from_square)
        piece_letter = chess.piece_symbol(piece.piece_type).upper()

        plan = []

        # 1) Captures (including en passant) - clear the captured piece
        #    to the off-board tray FIRST, before anything moves onto/through
        #    that square.
        if board.is_en_passant(move):
            captured_sq_index = move.to_square + (-8 if piece.color == chess.WHITE else 8)
            captured_sq = chess.square_name(captured_sq_index)
            captured_piece = board.piece_at(captured_sq_index)
            plan += self._capture_to_tray(captured_sq, captured_piece)
        elif board.is_capture(move):
            captured_piece = board.piece_at(move.to_square)
            plan += self._capture_to_tray(to, captured_piece)

        # 2) Castling - two ordinary relocations: king, then rook.
        if board.is_castling(move):
            if board.is_kingside_castling(move):
                rook_from = "h1" if piece.color == chess.WHITE else "h8"
                rook_to = "f1" if piece.color == chess.WHITE else "f8"
            else:
                rook_from = "a1" if piece.color == chess.WHITE else "a8"
                rook_to = "d1" if piece.color == chess.WHITE else "d8"
            plan += self._relocate("K", frm, to)
            plan += self._relocate("R", rook_from, rook_to)
            return plan

        # 3) Promotion - retire the pawn to the tray, bring on a reserve piece.
        if move.promotion:
            plan += self._capture_to_tray(frm, piece)
            promo_letter = chess.piece_symbol(move.promotion).upper()
            reserve_square = self.cfg.PROMOTION_RESERVE.get(promo_letter)
            if reserve_square is None:
                raise ValueError(
                    f"No physical reserve configured for promotion to {promo_letter}. "
                    f"Add an entry to config.PROMOTION_RESERVE and a matching slot in "
                    f"uno_gantry.ino's tryTraySlot()."
                )
            plan.append({"type": "PICK", "square": reserve_square, "piece": promo_letter})
            plan.append({"type": "PLACE", "square": to, "piece": promo_letter})
            return plan

        # 4) Ordinary move.
        plan += self._relocate(piece_letter, frm, to)
        return plan

    def _relocate(self, piece_letter, frm, to):
        return [
            {"type": "PICK", "square": frm, "piece": piece_letter},
            {"type": "PLACE", "square": to, "piece": piece_letter},
        ]

    def _capture_to_tray(self, square, captured_piece):
        slot = self._next_tray_slot(captured_piece.color)
        letter = chess.piece_symbol(captured_piece.piece_type).upper()
        return [
            {"type": "PICK", "square": square, "piece": letter},
            {"type": "PLACE", "square": slot, "piece": letter},
        ]

    def _next_tray_slot(self, color):
        self._tray_counters[color] += 1
        n = self._tray_counters[color]
        if n > self.cfg.CAPTURED_TRAY_SLOTS_PER_SIDE:
            raise RuntimeError(
                f"Captured-piece tray for {'white' if color else 'black'} is full "
                f"({n} pieces) - increase CAPTURED_TRAY_SLOTS_PER_SIDE and the "
                f"physical tray size, or empty it between games."
            )
        prefix = "TRAY_W" if color == chess.WHITE else "TRAY_B"
        return f"{prefix}{n}"

    # ------------------------------------------------------------------
    def push(self, move):
        self.board.push(move)

    def best_move(self):
        result = self.engine.play(self.board, self._limit)
        return result.move

    def evaluate_centipawns(self):
        """Used to derive the 'accuracy' metric stored per game for the
        30-day improvement graph."""
        info = self.engine.analyse(self.board, chess.engine.Limit(depth=12))
        score = info["score"].white().score(mate_score=10000)
        return score

    def quit(self):
        self.engine.quit()
