import json
import threading
import time
import chess
import config
import berserk
import tts_audio
from chess_logic import ChessSession
from database import Database
from serial_comm import RobotInterface
import google.generativeai as genai

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle, Line

# --- UI Theme Colors (Sleek & Modern) ---
Window.clearcolor = (0.92, 0.96, 0.98, 1) # Ice Blue Background
TEXT_COLOR = (0.1, 0.2, 0.3, 1)

# Base Colors
BLUE_NORMAL = (0.15, 0.55, 0.85, 1)
BLUE_PRESSED = (0.1, 0.45, 0.75, 1)

GREEN_NORMAL = (0.18, 0.75, 0.45, 1)
GREEN_PRESSED = (0.12, 0.65, 0.35, 1)

RED_NORMAL = (0.9, 0.3, 0.35, 1)
RED_PRESSED = (0.75, 0.2, 0.25, 1)

PURPLE_NORMAL = (0.5, 0.3, 0.8, 1)
PURPLE_PRESSED = (0.4, 0.2, 0.7, 1)

# --- Custom Interactive Rounded Button ---
class RoundedButton(Button):
    def __init__(self, bg_color=BLUE_NORMAL, pressed_color=BLUE_PRESSED, radius=20, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_down = ''
        self.background_color = (0, 0, 0, 0)
        self.bg_color = bg_color
        self.pressed_color = pressed_color
        self.color = (1, 1, 1, 1)
        self.bold = True
        self.font_size = 22

        with self.canvas.before:
            self.rect_color = Color(*self.bg_color)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[radius])

        self.bind(pos=self.update_rect, size=self.update_rect, state=self.update_state)

    def update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size

    def update_state(self, *args):
        if self.state == 'down':
            self.rect_color.rgba = self.pressed_color
        else:
            self.rect_color.rgba = self.bg_color

class ModernLabel(Label):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.color = TEXT_COLOR

# --- Custom Empty Graph Widget ---
class EmptyGraphWidget(RelativeLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        with self.canvas:
            Color(0.4, 0.5, 0.6, 1) # Axis Line Color (Grey-Blue)
            self.axes = Line(points=[], width=2)
            
        self.bind(pos=self.update_canvas, size=self.update_canvas)
        
        # Labels for the Graph
        self.y_label = ModernLabel(text="Accuracy (%)", size_hint=(None, None), size=(100, 30), bold=True)
        self.x_label = ModernLabel(text="Time (Days)", size_hint=(None, None), size=(100, 30), bold=True)
        self.no_data_label = ModernLabel(
            text="No Data Available Yet\n(Play a game to generate stats)", 
            font_size=25, 
            halign="center", 
            color=(0.5, 0.6, 0.7, 1)
        )
        
        self.add_widget(self.y_label)
        self.add_widget(self.x_label)
        self.add_widget(self.no_data_label)
        
    def update_canvas(self, *args):
        pad_x = 80
        pad_y = 60
        max_y = self.height - 30
        max_x = self.width - 30
        
        # Draw L-shape for X and Y axes
        self.axes.points = [
            pad_x, max_y, 
            pad_x, pad_y, 
            max_x, pad_y
        ]
        
        # Position Labels properly along the axes
        self.y_label.center_x = pad_x
        self.y_label.center_y = max_y + 15
        
        self.x_label.center_x = max_x - 30
        self.x_label.center_y = pad_y - 20
        
        # Center the "No Data" text
        self.no_data_label.center_x = self.width / 2
        self.no_data_label.center_y = self.height / 2


# ==================== CONTROLLER LOGIC ====================

class AppController:
    def __init__(self):
        self.cfg = config
        self.db = Database(config.DB_PATH)
        self.robot = RobotInterface(config)
        self.session = None
        genai.configure(api_key="AQ.Ab8RN6KTnqJbrI-wQdoZi8oGGeva4jWuWamCAR6yFN859eeJ4Q")
        self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
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

    def connect_hardware(self):
        results = self.robot.connect_all()
        if all(results.values()):
            self.status_text = "All systems connected."
        else:
            missing = [k for k, v in results.items() if not v]
            self.status_text = f"WARNING: could not connect to: {', '.join(missing)}"
            return
        try:
            self.robot.gantry_setpos("a8")
        except Exception as e:
            self.status_text += f" | gantry SETPOS failed: {e}"

    def select_profile(self, name):
        self.profile_id = self.db.get_or_create_profile(name)

    def get_profiles(self):
        try:
            return self.db.get_all_profiles()
        except AttributeError:
            return ["Player 1", "Guest"]

    def delete_profile(self, name):
        try:
            self.db.delete_profile(name)
        except AttributeError:
            pass

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
        self.selected_mode = "Puzzle"
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

    def _standard_game_loop(self, level):
        self.session = ChessSession(self.cfg, level=level)
        self.robot.eyes("BLUE")
        
        while self._running and not self.session.board.is_game_over():
            try:
                # ක්‍රීඩාවේ එක් වටයක් සඳහා Try බ්ලොක් එක ආරම්භ කිරීම
                if self.session.board.turn == chess.WHITE:
                    self._handle_human_turn()
                else:
                    self._handle_robot_turn()
            except Exception as e:
                # දෝෂයක් සිදුවුවහොත් එය මෙහිදී අල්ලාගෙන පද්ධතිය Crash වීම වළක්වයි
                print(f"[CRITICAL ERROR] At move {self.session.board.fullmove_number}: {e}")
                self.status_text = "System error, attempting to recover..."
                time.sleep(2) # පද්ධතිය නැවත ස්ථාපිත වීමට තත්පර 2ක විරාමයක්
                
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

    def _wait_for_pickup(self, timeout=300):
        deadline = time.time() + timeout
        while self._running and time.time() < deadline:
            for sq, state in self.robot.poll_board_events():
                if state == "OPEN":
                    return sq
            time.sleep(0.01)
        return None

    def _wait_for_dropoff(self, timeout=300):
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
        san_move = self.session.board.san(move)
        
        # Audio සහ Instructions තර්කනය
        if App.get_running_app().current_mode != "Normal Chess Match":
            prompt = (
                f"You are a friendly and encouraging chess tutor robot playing against a human. "
                f"You just decided to play the move '{san_move}'. "
                f"Explain to the human in one short, conversational sentence why this is a good move. "
                f"Do not use complex chess notation, keep it natural and simple."
            )
            try:
                response = self.gemini_model.generate_content(prompt)
                explanation = response.text.replace('*', '').strip()
            except Exception as e:
                explanation = self.session.describe_move(move)

            self.status_text = explanation
            self.move_log_text += f"Tutor: {explanation}\n"
            
            try:
                pcm = tts_audio.synthesize_to_pcm(explanation, self.cfg.TTS_SAMPLE_RATE)
                self.robot.speak_pcm(pcm)
            except Exception as e:
                self.status_text += f" (speech failed: {e})"
        else:
            self.status_text = "Tutor is making a move..."
            self.move_log_text += f"Tutor: {san_move}\n"

        # රොබෝගේ මනෝභාවය (Color Feedback) තීරණය කිරීම
        # හොඳ move එකක් නම් GREEN, නැතිනම් RED
        if self.session.board.is_capture(move): 
            self.robot.send_command("COLOR_GREEN")
        else:
            self.robot.send_command("COLOR_RED")
            
        # ගෑන්ට්‍රි පාලනය සහ ඉත්තා ඇදීම
        plan = self.session.physical_plan_for_move(move)   
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
            if board.turn == chess.BLACK:
                result = "win"     
                self.robot.win_green()
                self.robot.gesture("WIN_PLAYER")
            else:
                result = "loss"
        accuracy = 100.0   
        self.db.record_game(self.profile_id, "Standard", self.session.level, result, accuracy)
        self.status_text = f"Game over: {result}"
        self.session.quit()

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

    # ඉහළින්ම import berserk යන්න එකතු කරන්න
    # import berserk

    def start_lichess_mode(self):
        self.selected_mode = "Lichess"
        self.status_text = "Connecting to Lichess..."
        self._running = True
        
        # ඔබගේ Lichess Token එක මෙහි ලබා දෙන්න
        API_TOKEN = "lip_tBMBXzClanwFVl8TRXby" 
        
        try:
            session = berserk.TokenSession(API_TOKEN)
            self.lichess_client = berserk.Client(session)
            self.status_text = "Lichess Connected! Waiting for challenge..."
            
            # වෙනම Background Thread එකකින් Lichess එකත් එක්ක සම්බන්ධ වීම
            self._game_thread = threading.Thread(target=self._lichess_listener_loop, daemon=True)
            self._game_thread.start()
        except Exception as e:
            self.status_text = f"Lichess Error: {e}"

    def _lichess_listener_loop(self):
        # 1. අන්තර්ජාලයෙන් එන Challenges බලාපොරොත්තුවෙන් සිටීම
        for event in self.lichess_client.board.stream_incoming_events():
            if event['type'] == 'challenge':
                game_id = event['challenge']['id']
                
                # Challenge එක Accept කිරීම
                self.lichess_client.board.accept_challenge(game_id)
                self.status_text = "Online Match Started!"
                
                # ගේම් එක Play කිරීමේ කොටසට යොමු කිරීම
                self._play_lichess_game(game_id)
                break # එක ගේම් එකකින් පසු Loop එකෙන් ඉවත් වීම

    def _play_lichess_game(self, game_id):
        self.session = ChessSession(self.cfg, level="Hard") # Local Chess Board එක Update කරගැනීමට
        
        # 2. අන්තර්ජාලයෙන් එන ඇදීම් (Moves) කියවීම
        for event in self.lichess_client.board.stream_game_state(game_id):
            if not self._running:
                break
                
            if event['type'] == 'gameState' or event['type'] == 'gameFull':
                state = event.get('state', event)
                moves = state.get('moves', '').split()
                
                # Local Board එකෙයි Internet Board එකෙයි ඇදීම් ගණන අසමාන නම්, 
                # ඒ කියන්නේ Internet එකේ ඉන්න කෙනා අලුත් ඇදීමක් කරලා!
                if len(moves) > len(self.session.board.move_stack):
                    latest_move_uci = moves[-1] # අන්තිමට ආපු ඇදීම (උදා: e2e4)
                    move = chess.Move.from_uci(latest_move_uci)
                    
                    self.status_text = f"Opponent played: {latest_move_uci}"
                    
                    # රොබෝ අත මගින් භෞතිකව ඉත්තා ඇදීම
                    plan = self.session.physical_plan_for_move(move)   
                    for step in plan:
                        self.robot.gantry_move_to(step["square"])
                        if step["type"] == "PICK":
                            self.robot.gantry_pick(step["piece"])
                        else:
                            self.robot.gantry_place(step["piece"])
                    self.robot.gantry_home()
                    
                    # Local Board එක Update කිරීම
                    self.session.push(move)
                    
                    # මීළඟට අපේ වාරය (Human Turn)
                    self._lichess_human_turn(game_id)

    def _lichess_human_turn(self, game_id):
        self.status_text = "Your turn (Physical Board)"
        from_square = self._wait_for_pickup()
        if from_square is None: return
        
        to_square = self._wait_for_dropoff()
        if to_square is None: return
        
        move = self.session.find_move(from_square, to_square)
        if move is not None:
            self.session.push(move)
            # අපි භෞතිකව කරපු ඇදීම අන්තර්ජාලයට යැවීම! (Send to Lichess)
            self.lichess_client.board.make_move(game_id, move.uci())
            self.status_text = "Move sent to Lichess!"
        else:
            self.robot.gesture("ILLEGAL")
            self.status_text = "Illegal move - try again."


# ==================== KIVY GUI SCREENS ====================

class ProfileScreen(Screen):
    def __init__(self, app_ctrl, **kwargs):
        super().__init__(**kwargs)
        self.app_ctrl = app_ctrl
        self.layout = BoxLayout(orientation='vertical', spacing=20, padding=40)
        self.add_widget(self.layout)
        self.refresh_profiles()

    def refresh_profiles(self):
        self.layout.clear_widgets()
        self.layout.add_widget(ModernLabel(text="Select or Create Profile", font_size=40, bold=True, size_hint=(1, 0.2)))
        
        input_row = BoxLayout(orientation='horizontal', size_hint=(1, 0.2), spacing=15)
        self.new_profile_input = TextInput(
            hint_text="Enter new player name...", 
            multiline=False, font_size=25,
            padding_y=[15, 15],
            background_color=(1, 1, 1, 1),
            foreground_color=TEXT_COLOR
        )
        add_btn = RoundedButton(text="Create", size_hint=(0.3, 1), bg_color=GREEN_NORMAL, pressed_color=GREEN_PRESSED)
        add_btn.bind(on_press=self.create_profile)
        input_row.add_widget(self.new_profile_input)
        input_row.add_widget(add_btn)
        self.layout.add_widget(input_row)

        profiles = self.app_ctrl.get_profiles()
        for p in profiles:
            row = BoxLayout(orientation='horizontal', size_hint=(1, 0.2), spacing=15)
            
            btn = RoundedButton(text=p, bg_color=BLUE_NORMAL, pressed_color=BLUE_PRESSED)
            btn.bind(on_press=self.select_profile)
            
            btn_graph = RoundedButton(text="Stats", size_hint=(0.3, 1), bg_color=PURPLE_NORMAL, pressed_color=PURPLE_PRESSED)
            btn_graph.bind(on_press=lambda instance, name=p: self.view_progress(name))
            
            del_btn = RoundedButton(text="Delete", size_hint=(0.3, 1), bg_color=RED_NORMAL, pressed_color=RED_PRESSED)
            del_btn.bind(on_press=lambda instance, name=p: self.delete_profile(name))
            
            row.add_widget(btn)
            row.add_widget(btn_graph)
            row.add_widget(del_btn)
            self.layout.add_widget(row)

    def create_profile(self, instance):
        name = self.new_profile_input.text.strip()
        if name:
            self.app_ctrl.select_profile(name)
            self.refresh_profiles()

    def select_profile(self, instance):
        App.get_running_app().current_profile = instance.text
        self.manager.transition = SlideTransition(direction='left')
        self.manager.current = 'mode_screen'

    def view_progress(self, name):
        App.get_running_app().current_profile = name
        self.manager.transition = SlideTransition(direction='left')
        self.manager.current = 'graph_screen'

    def delete_profile(self, name):
        self.app_ctrl.delete_profile(name)
        self.refresh_profiles()

class GraphScreen(Screen):
    def __init__(self, app_ctrl, **kwargs):
        super().__init__(**kwargs)
        self.app_ctrl = app_ctrl
        layout = BoxLayout(orientation='vertical', padding=40, spacing=20)
        
        layout.add_widget(ModernLabel(text="30-Day Performance", font_size=40, bold=True, size_hint=(1, 0.2)))
        
        # --- The Custom Empty Graph Widget ---
        self.graph_widget = EmptyGraphWidget(size_hint=(1, 0.6))
        layout.add_widget(self.graph_widget)
        
        btn_back = RoundedButton(text="Go Back", size_hint=(1, 0.2), bg_color=(0.5, 0.5, 0.5, 1), pressed_color=(0.4, 0.4, 0.4, 1))
        btn_back.bind(on_press=self.go_back)
        layout.add_widget(btn_back)
        self.add_widget(layout)

    def go_back(self, instance):
        self.manager.transition = SlideTransition(direction='right')
        self.manager.current = 'profile_screen'

class ModeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', spacing=20, padding=50)
        layout.add_widget(ModernLabel(text="Select Game Mode", font_size=45, bold=True))
        
        # අලුත් Lichess mode එක මෙහි එකතු කර ඇත (තැඹිලි වර්ණයෙන්)
        modes = [
            ("Normal Chess Match", BLUE_NORMAL, BLUE_PRESSED), 
            ("Training Mode", GREEN_NORMAL, GREEN_PRESSED), 
            ("Puzzle Mode", PURPLE_NORMAL, PURPLE_PRESSED),
            ("Lichess Online Mode", (0.9, 0.5, 0.1, 1), (0.8, 0.4, 0.1, 1))
        ]
        
        for m_text, m_bg, m_pr in modes:
            btn = RoundedButton(text=m_text, size_hint=(1, 0.25), bg_color=m_bg, pressed_color=m_pr)
            btn.bind(on_press=self.handle_mode_selection)
            layout.add_widget(btn)
            
        btn_back = RoundedButton(text="Back", size_hint=(1, 0.15), bg_color=(0.5, 0.5, 0.5, 1), pressed_color=(0.4, 0.4, 0.4, 1), radius=15)
        btn_back.bind(on_press=self.go_back)
        layout.add_widget(btn_back)
        
        self.add_widget(layout)

    def handle_mode_selection(self, instance):
        mode = instance.text
        app = App.get_running_app()
        app.current_mode = mode
        self.manager.transition = SlideTransition(direction='left')
        
        # Lichess තේරූ විට Difficulty අසන්නේ නැතිව කෙලින්ම Game Screen එකට යයි
        if mode == "Lichess Online Mode":
            app.app_ctrl.start_lichess_mode()
            self.manager.current = 'game_screen'
        elif mode == "Puzzle Mode":
            self.manager.current = 'game_screen'
        else:
            self.manager.current = 'difficulty_screen'
            
    def go_back(self, instance):
        self.manager.transition = SlideTransition(direction='right')
        self.manager.current = 'profile_screen'

class DifficultyScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', spacing=20, padding=50)
        layout.add_widget(ModernLabel(text="Select Difficulty", font_size=45, bold=True))
        
        diffs = [
            ("Easy", GREEN_NORMAL, GREEN_PRESSED), 
            ("Medium", BLUE_NORMAL, BLUE_PRESSED), 
            ("Hard", RED_NORMAL, RED_PRESSED)
        ]
        
        for d_text, d_bg, d_pr in diffs:
            btn = RoundedButton(text=d_text, size_hint=(1, 0.25), bg_color=d_bg, pressed_color=d_pr)
            btn.bind(on_press=self.start_game)
            layout.add_widget(btn)

        btn_back = RoundedButton(text="Back", size_hint=(1, 0.15), bg_color=(0.5, 0.5, 0.5, 1), pressed_color=(0.4, 0.4, 0.4, 1), radius=15)
        btn_back.bind(on_press=self.go_back)
        layout.add_widget(btn_back)
        self.add_widget(layout)

    def start_game(self, instance):
        App.get_running_app().current_difficulty = instance.text
        self.manager.transition = SlideTransition(direction='left')
        self.manager.current = 'game_screen'
        
    def go_back(self, instance):
        self.manager.transition = SlideTransition(direction='right')
        self.manager.current = 'mode_screen'


class GameScreen(Screen):
    def __init__(self, app_ctrl, **kwargs):
        super().__init__(**kwargs)
        self.app_ctrl = app_ctrl
        layout = BoxLayout(orientation='vertical', padding=30, spacing=15)
        
        self.header_label = ModernLabel(text="Loading...", font_size=22, size_hint=(1, 0.1), color=BLUE_NORMAL, bold=True)
        self.status_label = ModernLabel(text="Ready to Play", font_size=32, size_hint=(1, 0.2), bold=True)
        self.log_label = ModernLabel(text="", font_size=20, size_hint=(1, 0.6), halign="left", valign="top", color=(0.4, 0.5, 0.6, 1))
        self.log_label.bind(size=self.log_label.setter('text_size')) 
        
        layout.add_widget(self.header_label)
        layout.add_widget(self.status_label)
        layout.add_widget(self.log_label)
        self.add_widget(layout)

    def on_enter(self):
        app = App.get_running_app()
        profile = app.current_profile
        mode = app.current_mode
        diff = app.current_difficulty
        self.app_ctrl.select_profile(profile)
        self.header_label.text = f"👤 {profile}   |   🎮 {mode}" + (f"   |   ⚙️ {diff}" if diff else "")
        if mode == "Puzzle Mode":
            self.app_ctrl.start_puzzle_mode()
        else:
            self.app_ctrl.start_standard_game(level=diff)
        Clock.schedule_interval(self.update_ui, 0.5)

    def update_ui(self, dt):
        self.status_label.text = self.app_ctrl.status_text
        self.log_label.text = self.app_ctrl.move_log_text


class ChessTutorApp(App):
    def __init__(self, app_ctrl, **kwargs):
        super().__init__(**kwargs)
        self.app_ctrl = app_ctrl
        self.current_profile = None
        self.current_mode = None
        self.current_difficulty = None

    def build(self):
        sm = ScreenManager()
        sm.add_widget(ProfileScreen(app_ctrl=self.app_ctrl, name='profile_screen'))
        sm.add_widget(GraphScreen(app_ctrl=self.app_ctrl, name='graph_screen'))
        sm.add_widget(ModeScreen(name='mode_screen'))
        sm.add_widget(DifficultyScreen(name='difficulty_screen'))
        sm.add_widget(GameScreen(app_ctrl=self.app_ctrl, name='game_screen'))
        return sm

    def on_stop(self):
        self.app_ctrl.end_session()

def main():
    app_ctrl = AppController()
    app_ctrl.connect_hardware()
    ChessTutorApp(app_ctrl).run()
    app_ctrl.robot.close_all()

if __name__ == "__main__":
    main()