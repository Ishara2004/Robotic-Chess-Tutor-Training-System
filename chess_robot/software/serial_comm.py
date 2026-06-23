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
"""

import queue
import threading
import time

import serial
import serial.tools.list_ports


class BoardConnection:
    def __init__(self, expected_id, baud=115200, timeout=1.0, port_name=None):
        self.expected_id = expected_id
        self.baud = baud
        self.timeout = timeout
        self.port_name = port_name
        self.ser = None
        self.event_queue = queue.Queue()
        self._running = False
        self.thread = None
        self._cmd_ack_event = threading.Event()
        self._last_cmd_status = False
        self._last_cmd_reply = ""

    def connect(self):
        candidates = [self.port_name] if self.port_name else \
            [p.device for p in serial.tools.list_ports.comports()]

        for port in candidates:
            try:
                ser = serial.Serial(port, self.baud, timeout=self.timeout)
                time.sleep(2.0)
                ser.reset_input_buffer()
                ser.write(b"PING\n")
                
                deadline = time.time() + 2.0
                connected = False
                while time.time() < deadline:
                    line = ser.readline().decode(errors="ignore").strip()
                    if self.expected_id in line:
                        self.ser = ser
                        self.port_name = port
                        self._start_reader()
                        connected = True
                        break
                
                if connected:
                    return True
                
                ser.close()
            except (serial.SerialException, OSError):
                continue
        return False

    def _start_reader(self):
        self._running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def _read_loop(self):
        while self._running and self.ser:
            try:
                # Windows COM port buffering ගැටලු මඟහරවා ගැනීමට
                line = self.ser.readline().decode(errors="ignore").strip()
                if line:
                    # ලැබෙන දත්ත මොනිටරයේ පෙන්වීම
                    print(f"[{self.expected_id} IN] {line}") 
                    self.event_queue.put(line)
            except OSError:
                self._running = False
                break

    def send(self, command: str, wait_ack=True, ack_timeout=10.0):
        if not self.ser:
            raise ConnectionError(f"Board {self.expected_id} is not connected")
        
        # යවන දත්ත මොනිටරයේ පෙන්වීම
        print(f"[{self.expected_id} OUT] {command}")
        
        # ESP32 එකට දත්ත කියවීමට කුඩා කාලයක් ලබා දීම
        time.sleep(0.1) 
        self.ser.write((command + "\n").encode())
        self.ser.flush()
        
        if not wait_ack:
            return None

        deadline = time.time() + ack_timeout
        while time.time() < deadline:
            try:
                line = self.event_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            # ලැබෙන පිළිතුර Blueprint එකට අනුව පරීක්ෂා කිරීම
            if line.startswith(("ACK:", "ERR:", "PONG:", "STATE:")):
                if line.startswith("ERR:"):
                    raise RuntimeError(f"{self.expected_id} reported: {line}")
                return line
            self.event_queue.put(line)
            
        raise TimeoutError(f"No ACK from {self.expected_id} for command: {command}")
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
        return {
            "mega": self.mega.connect(),
            "uno": self.uno.connect(),
            "esp32": self.esp32.connect(),
        }

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
        while True:
            try:
                line = self.mega.event_queue.get_nowait()
            except queue.Empty:
                break
            if line.startswith("SQEVT:"):
                _, sq, state = line.split(":")
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
                line = self.esp32.event_queue.get(timeout=0.2)
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
