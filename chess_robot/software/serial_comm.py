"""
Chess Robotic Tutor and Training System
Serial communication layer.

Manages one independent USB-serial link per board (Mega / Uno / ESP32).
Each board is auto-discovered by sending PING and checking the PONG
identity string, so it doesn't matter which physical USB port each
board lands on or in what order Windows/Linux enumerates them.

Protocol recap (full spec in BLUEPRINT.md section 7):
  PC -> board : "<COMMAND>[:<args>]\n"
  board -> PC : "ACK:<...>\n" | "ERR:<reason>\n" | "PONG:<id>\n" | "STATE:<...>\n"
                or, ONLY from the Mega, unsolicited "SQEVT:<square>:<OPEN|CLOSED>\n"
                events streamed at any time as reed switches change state.

NOTE: every board's firmware MUST answer a bare "PING" with
"PONG:<BOARD_ID>". This file assumes that contract. If a board's .ino
doesn't implement it, connect() will never succeed for that board no
matter how long you wait - see mega_chessboard.ino for the fix that
was missing there.
"""

import queue
import threading
import time

import serial
import serial.tools.list_ports

# Lines that are responses to a command we just sent.
_RESPONSE_PREFIXES = ("ACK:", "ERR:", "PONG:", "STATE:")


class BoardConnection:
    def __init__(self, expected_id, baud=115200, timeout=1.0, port_name=None):
        self.expected_id = expected_id
        self.baud = baud
        self.timeout = timeout
        self.port_name = port_name
        self.ser = None

        # Two separate queues so an unsolicited SQEVT stream can never be
        # mis-ordered with, or starve, the ACK/ERR/PONG/STATE responses to
        # commands we actively sent (and vice versa).
        self.event_queue = queue.Queue()      # unsolicited (SQEVT, etc.)
        self.response_queue = queue.Queue()   # ACK / ERR / PONG / STATE

        self._running = False
        self._lock = threading.Lock()
        self.thread = None

    # ------------------------------------------------------------------
    # Connection / handshake
    # ------------------------------------------------------------------
    def connect(self, claimed_ports=None):
        """Try every available serial port (or just self.port_name, if it
        was set explicitly) until one answers PING with PONG:<expected_id>.

        claimed_ports: an optional set[str] of port device names already
        owned by sibling BoardConnections this run, so we don't waste time
        (and risk a noisy access-denied error) re-opening a port another
        board already claimed.
        """
        if claimed_ports is None:
            claimed_ports = set()

        candidates = [self.port_name] if self.port_name else \
            [p.device for p in serial.tools.list_ports.comports()]

        for port in candidates:
            if port in claimed_ports:
                continue
            try:
                ser = serial.Serial(port, self.baud, timeout=self.timeout)
            except (serial.SerialException, OSError):
                continue

            try:
                # Let the board finish its reset-on-open boot sequence
                # (Mega/Uno/ESP32 all reset when DTR toggles on port open).
                # We deliberately do NOT reset_input_buffer() here - any
                # unsolicited boot banner the board prints is harmless and
                # simply won't match the PONG check below, so there's no
                # need to throw it away (and discarding it is exactly what
                # caused the original race condition).
                time.sleep(2.0)

                ser.write(b"PING\n")

                deadline = time.time() + 2.0
                matched = False
                while time.time() < deadline:
                    line = ser.readline().decode(errors="ignore").strip()
                    if not line:
                        continue
                    if line.startswith("PONG:") and self.expected_id in line:
                        matched = True
                        break
                    # Anything else (boot banner, stray SQEVT, etc.) is
                    # simply ignored during the handshake window.

                if matched:
                    self.ser = ser
                    self.port_name = port
                    claimed_ports.add(port)
                    self._start_reader()
                    return True
            except (serial.SerialException, OSError):
                pass

            ser.close()

        return False

    # ------------------------------------------------------------------
    # Background reader - the ONLY thing that ever calls ser.readline().
    # Routes every line to response_queue or event_queue so the two
    # consumers (send()'s ACK wait, and poll_board_events()) never
    # compete for the same queue.
    # ------------------------------------------------------------------
    def _start_reader(self):
        self._running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def _read_loop(self):
        while self._running:
            ser = self.ser
            if ser is None:
                break
            try:
                line = ser.readline().decode(errors="ignore").strip()
            except (serial.SerialException, OSError) as e:
                # Real disconnect (cable pulled, port vanished) - stop.
                print(f"[ERROR] {self.expected_id} serial disconnected: {e}")
                self._running = False
                break
            except Exception as e:
                # Anything else (e.g. a transient decode hiccup) should
                # NOT permanently kill the link - log it and keep reading.
                print(f"[WARN] {self.expected_id} reader hiccup: {e}")
                continue

            if not line:
                continue

            print(f"[{self.expected_id} IN] {line}")
            if line.startswith(_RESPONSE_PREFIXES):
                self.response_queue.put(line)
            else:
                self.event_queue.put(line)

    # ------------------------------------------------------------------
    # Sending commands
    # ------------------------------------------------------------------
    def send(self, command: str, wait_ack=True, ack_timeout=10.0):
        if not self.ser:
            raise ConnectionError(f"Board {self.expected_id} is not connected")

        print(f"[{self.expected_id} OUT] {command}")
        with self._lock:
            self.ser.write((command + "\n").encode())
            self.ser.flush()

        if not wait_ack:
            return None

        deadline = time.time() + ack_timeout
        while time.time() < deadline:
            try:
                line = self.response_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if line.startswith("ERR:"):
                raise RuntimeError(f"{self.expected_id} reported: {line}")
            return line

        raise TimeoutError(f"No ACK from {self.expected_id} for command: {command}")

    def is_connected(self):
        return self.ser is not None and self._running

    def close(self):
        self._running = False
        if self.ser:
            try:
                self.ser.close()
            except OSError:
                pass
            self.ser = None
        if self.thread:
            self.thread.join(timeout=1.0)


class RobotInterface:
    """High-level facade combining the three boards into one clean API
    for the rest of the application (chess_logic.py / main.py)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.mega = BoardConnection("MEGA_CHESSBOARD_V1", cfg.BAUD_RATE, cfg.SERIAL_TIMEOUT_S, cfg.PORT_MEGA)
        self.uno = BoardConnection("UNO_GANTRY_V1", cfg.BAUD_RATE, cfg.SERIAL_TIMEOUT_S, cfg.PORT_UNO)
        self.esp32 = BoardConnection("ESP32_TUTOR_V1", cfg.BAUD_RATE, cfg.SERIAL_TIMEOUT_S, cfg.PORT_ESP32)

    def connect_all(self):
        """
        Establishes serial connections for all three microcontrollers.
        Ports already claimed by an earlier board in this call are skipped
        by later boards, so auto-detection can't accidentally try to
        re-open a port that's already in use.
        """
        claimed_ports = set()
        results = {}
        for name, board in (("mega", self.mega), ("uno", self.uno), ("esp32", self.esp32)):
            results[name] = board.connect(claimed_ports=claimed_ports)

        for board, success in results.items():
            if success:
                print(f"[SYSTEM] {board.upper()} successfully connected.")
            else:
                print(f"[ERROR] {board.upper()} connection failed.")

        return results

    # ---------------- Chessboard (Mega) ----------------
    def show_moves(self, blue_squares, red_squares):
        blue = ",".join(blue_squares)
        red = ",".join(red_squares)
        self.mega.send(f"SHOWMOVES:{blue}:{red}")

    def clear_leds(self):
        self.mega.send("CLEARLEDS")

    def win_green(self):
        self.mega.send("WINGREEN")

    def board_state(self):
        """Returns the 64-bit occupancy snapshot as a hex string."""
        line = self.mega.send("GETSTATE")
        return line.split(":", 1)[1] if ":" in line else None

    def poll_board_events(self):
        """Non-blocking drain of any pending SQEVT events from the Mega."""
        events = []
        while not self.mega.event_queue.empty():
            try:
                line = self.mega.event_queue.get_nowait()
            except queue.Empty:
                break
            if line.startswith("SQEVT:"):
                parts = line.split(":")
                if len(parts) == 3:
                    sq, state = parts[1], parts[2]
                    events.append((sq, state))
        return events

    # ---------------- Gantry (Uno) ----------------
    def gantry_home(self):
        self.uno.send("HOME", ack_timeout=30)

    def gantry_setpos(self, square):
        self.uno.send(f"SETPOS:{square}")

    def gantry_move_to(self, square):
        self.uno.send(f"MOVETO:{square}", ack_timeout=60)

    def gantry_pick(self, piece_type_letter):
        self.uno.send(f"PICK:{piece_type_letter}", ack_timeout=60)

    def gantry_place(self, piece_type_letter):
        self.uno.send(f"PLACE:{piece_type_letter}", ack_timeout=60)

    def gantry_jog(self, axis, steps):
        self.uno.send(f"JOG:{axis}:{steps}", ack_timeout=15)

    # ---------------- Tutor (ESP32) ----------------
    def eyes(self, color):
        self.esp32.send(f"EYES:{color}")

    def gesture(self, name):
        self.esp32.send(f"GESTURE:{name}")

    def speak_pcm(self, pcm_bytes: bytes):
        """Streams raw 16-bit mono PCM audio to the ESP32 for playback.
        Splits into chunks no larger than the firmware's AUDIO_BUF_MAX."""
        max_chunk = self.cfg.AUDIO_CHUNK_MAX_BYTES
        for i in range(0, len(pcm_bytes), max_chunk):
            chunk = pcm_bytes[i:i + max_chunk]
            self.esp32.send(f"AUDIO:{len(chunk)}", wait_ack=False)
            self.esp32.ser.write(chunk)
            self._wait_for_audio_ack()

    def _wait_for_audio_ack(self, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.esp32.response_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if line.startswith("ACK:AUDIO"):
                return
            if line.startswith("ERR:"):
                raise RuntimeError(f"ESP32 audio error: {line}")
        raise TimeoutError("No ACK:AUDIO from ESP32")

    def close_all(self):
        self.mega.close()
        self.uno.close()
        self.esp32.close()

    def send_command(self, command):
        """Generic passthrough to the Mega (used by main.py for ad-hoc
        commands like COLOR_GREEN / COLOR_RED)."""
        if self.mega.is_connected():
            self.mega.send(command)
        else:
            print(f"[ERROR] Cannot send '{command}': Mega connection is not active.")
