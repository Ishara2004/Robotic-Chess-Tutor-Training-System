"""
Chess Robotic Tutor and Training System
Local SQLite storage for player profiles and game history, including the
data backing the "improvement over the last 30 days" graph shown on the
touchscreen.
"""

import datetime
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    mode TEXT NOT NULL,          -- 'Standard' or 'Puzzle'
    level TEXT,                  -- 'Easy' / 'Medium' / 'Hard' (Standard only)
    result TEXT,                 -- 'win' / 'loss' / 'draw' / 'solved' / 'failed'
    accuracy REAL,               -- 0-100 estimate, see chess_logic.evaluate_centipawns()
    played_at TEXT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES profiles(id)
);
"""


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------------- Profiles ----------------
    def get_or_create_profile(self, name):
        cur = self.conn.execute("SELECT id FROM profiles WHERE name=?", (name,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur = self.conn.execute(
            "INSERT INTO profiles (name, created_at) VALUES (?, ?)",
            (name, datetime.datetime.utcnow().isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_profiles(self):
        return [r[0] for r in self.conn.execute("SELECT name FROM profiles ORDER BY name")]

    # ---------------- Games ----------------
    def record_game(self, profile_id, mode, level, result, accuracy):
        self.conn.execute(
            "INSERT INTO games (profile_id, mode, level, result, accuracy, played_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (profile_id, mode, level, result, accuracy, datetime.datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    def last_30_days_accuracy(self, profile_id):
        """Returns [(date_str, avg_accuracy), ...] for the last 30 days,
        one point per day that has at least one recorded game - this feeds
        the x-y improvement graph directly."""
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).isoformat()
        rows = self.conn.execute(
            "SELECT played_at, accuracy FROM games WHERE profile_id=? AND played_at>=? "
            "ORDER BY played_at",
            (profile_id, cutoff),
        ).fetchall()
        daily = {}
        for played_at, acc in rows:
            day = played_at[:10]
            daily.setdefault(day, []).append(acc)
        return [(day, sum(vals) / len(vals)) for day, vals in sorted(daily.items())]

    def close(self):
        self.conn.close()

    def get_all_profiles(self):
        """දැනට Database එකේ ඇති සියලුම Profile නම් ලබා දෙයි"""
        cursor = self.conn.cursor()
        # ඔබගේ table එකේ නම 'profiles' නොවේ නම් එය නිවැරදි කරගන්න
        cursor.execute("SELECT name FROM profiles") 
        rows = cursor.fetchall()
        return [row[0] for row in rows] if rows else []

    def delete_profile(self, name):
        """ලබා දෙන නමට අදාළ Profile එක Database එකෙන් මකා දමයි"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM profiles WHERE name = ?", (name,))
        self.conn.commit()