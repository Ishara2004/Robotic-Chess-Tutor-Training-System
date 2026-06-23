"""
Chess Robotic Tutor and Training System
Touchscreen GUI (Kivy), designed for the HDMI + USB-touch display that
connects directly to the laptop running this software.

Screens: Profile -> Mode -> Level (Standard only) -> Game -> Graph.
This module only handles presentation; all game logic lives in
AppController (main.py) so the GUI can be swapped out independently if
you'd rather build a different front-end later.
"""

import io

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image as KivyImage
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.textinput import TextInput

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


class ProfileScreen(Screen):
    def __init__(self, app_ctrl, **kw):
        super().__init__(**kw)
        self.app_ctrl = app_ctrl
        root = BoxLayout(orientation="vertical", padding=40, spacing=20)
        root.add_widget(Label(text="Select or Create Profile", font_size=32, size_hint_y=None, height=60))

        self.name_input = TextInput(hint_text="Enter your name", font_size=28,
                                     multiline=False, size_hint_y=None, height=70)
        root.add_widget(self.name_input)

        login_btn = Button(text="Login / Create", font_size=26, size_hint_y=None, height=80)
        login_btn.bind(on_release=self.on_login)
        root.add_widget(login_btn)

        root.add_widget(Label(text="Existing profiles:", font_size=20, size_hint_y=None, height=40))
        self.profile_list = GridLayout(cols=3, spacing=10, size_hint_y=None)
        self.profile_list.bind(minimum_height=self.profile_list.setter("height"))
        root.add_widget(self.profile_list)

        self.add_widget(root)

    def on_pre_enter(self):
        self.profile_list.clear_widgets()
        for name in self.app_ctrl.db.list_profiles():
            b = Button(text=name, font_size=22, size_hint_y=None, height=60)
            b.bind(on_release=lambda inst, n=name: self.select_profile(n))
            self.profile_list.add_widget(b)

    def on_login(self, *_):
        name = self.name_input.text.strip()
        if name:
            self.select_profile(name)

    def select_profile(self, name):
        self.app_ctrl.select_profile(name)
        self.manager.current = "mode"


class ModeScreen(Screen):
    def __init__(self, app_ctrl, **kw):
        super().__init__(**kw)
        self.app_ctrl = app_ctrl
        root = BoxLayout(orientation="vertical", padding=40, spacing=30)
        root.add_widget(Label(text="Select Mode", font_size=32, size_hint_y=None, height=60))

        row = BoxLayout(spacing=30)
        for mode in ("Standard", "Puzzle"):
            b = Button(text=mode, font_size=28)
            b.bind(on_release=lambda inst, m=mode: self.choose(m))
            row.add_widget(b)
        root.add_widget(row)

        graph_btn = Button(text="View My Progress", font_size=22, size_hint_y=None, height=70)
        graph_btn.bind(on_release=lambda *_: setattr(self.manager, "current", "graph"))
        root.add_widget(graph_btn)

        self.add_widget(root)

    def choose(self, mode):
        self.app_ctrl.selected_mode = mode
        if mode == "Standard":
            self.manager.current = "level"
        else:
            self.app_ctrl.start_puzzle_mode()
            self.manager.current = "game"


class LevelScreen(Screen):
    def __init__(self, app_ctrl, **kw):
        super().__init__(**kw)
        self.app_ctrl = app_ctrl
        root = BoxLayout(orientation="vertical", padding=40, spacing=30)
        root.add_widget(Label(text="Select Difficulty", font_size=32, size_hint_y=None, height=60))
        row = BoxLayout(spacing=30)
        for level in ("Easy", "Medium", "Hard"):
            b = Button(text=level, font_size=28)
            b.bind(on_release=lambda inst, lv=level: self.choose(lv))
            row.add_widget(b)
        root.add_widget(row)
        self.add_widget(root)

    def choose(self, level):
        self.app_ctrl.start_standard_game(level)
        self.manager.current = "game"


class GameScreen(Screen):
    def __init__(self, app_ctrl, **kw):
        super().__init__(**kw)
        self.app_ctrl = app_ctrl
        root = BoxLayout(orientation="vertical", padding=20, spacing=10)

        self.status_label = Label(text="Game in progress...", font_size=24,
                                   size_hint_y=None, height=70)
        root.add_widget(self.status_label)

        self.move_log = Label(text="", font_size=18, halign="left", valign="top")
        self.move_log.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        root.add_widget(self.move_log)

        end_btn = Button(text="End Session", size_hint_y=None, height=60, font_size=20)
        end_btn.bind(on_release=lambda *_: self.app_ctrl.end_session())
        root.add_widget(end_btn)

        self.add_widget(root)
        Clock.schedule_interval(self.refresh, 0.5)

    def refresh(self, *_):
        self.status_label.text = self.app_ctrl.status_text
        self.move_log.text = self.app_ctrl.move_log_text


class GraphScreen(Screen):
    def __init__(self, app_ctrl, **kw):
        super().__init__(**kw)
        self.app_ctrl = app_ctrl
        self.layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        self.add_widget(self.layout)

    def on_pre_enter(self):
        self.layout.clear_widgets()

        if self.app_ctrl.profile_id is None:
            self.layout.add_widget(Label(text="No profile selected.", font_size=24))
        else:
            data = self.app_ctrl.db.last_30_days_accuracy(self.app_ctrl.profile_id)
            fig, ax = plt.subplots(figsize=(8, 4.5))
            if data:
                days = [d for d, _ in data]
                vals = [v for _, v in data]
                ax.plot(days, vals, marker="o")
            else:
                ax.text(0.5, 0.5, "No games recorded yet", ha="center", va="center")
            ax.set_title("Improvement - Last 30 Days")
            ax.set_xlabel("Date")
            ax.set_ylabel("Accuracy (%)")
            ax.tick_params(axis="x", rotation=45)
            fig.tight_layout()

            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=120)
            plt.close(fig)
            buf.seek(0)
            core_img = CoreImage(buf, ext="png")
            self.layout.add_widget(KivyImage(texture=core_img.texture))

        back = Button(text="Back", size_hint_y=None, height=60, font_size=20)
        back.bind(on_release=lambda *_: setattr(self.manager, "current", "mode"))
        self.layout.add_widget(back)


class ChessTutorGUI(App):
    def __init__(self, app_ctrl, **kw):
        super().__init__(**kw)
        self.app_ctrl = app_ctrl

    def build(self):
        sm = ScreenManager()
        sm.add_widget(ProfileScreen(self.app_ctrl, name="profile"))
        sm.add_widget(ModeScreen(self.app_ctrl, name="mode"))
        sm.add_widget(LevelScreen(self.app_ctrl, name="level"))
        sm.add_widget(GameScreen(self.app_ctrl, name="game"))
        sm.add_widget(GraphScreen(self.app_ctrl, name="graph"))
        return sm
