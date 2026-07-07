import sqlite3
import os
import json


class Database:
    def __init__(self, db_path: str = "data/users.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id        INTEGER PRIMARY KEY,
                    api_id         INTEGER NOT NULL,
                    api_hash       TEXT    NOT NULL,
                    phone          TEXT    NOT NULL,
                    session_string TEXT    NOT NULL,
                    prefix         TEXT    DEFAULT '.',
                    is_active      INTEGER DEFAULT 1,
                    process_pid    INTEGER DEFAULT 0,
                    created_at     TEXT DEFAULT (datetime('now')),
                    updated_at     TEXT DEFAULT (datetime('now'))
                )
            """)

    def save_user(self, user_id: int, api_id: int, api_hash: str,
                  phone: str, session_string: str, prefix: str = "."):
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO users
                    (user_id, api_id, api_hash, phone, session_string,
                     prefix, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'))
            """, (user_id, api_id, api_hash, phone, session_string, prefix))

    def get_user(self, user_id: int):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_active(self):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE is_active = 1"
            ).fetchall()
            return [dict(r) for r in rows]

    def deactivate_user(self, user_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET is_active=0, process_pid=0, "
                "updated_at=datetime('now') WHERE user_id=?",
                (user_id,),
            )

    def set_pid(self, user_id: int, pid: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET process_pid=?, updated_at=datetime('now') "
                "WHERE user_id=?",
                (pid, user_id),
            )

    def update_prefix(self, user_id: int, prefix: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET prefix=?, updated_at=datetime('now') "
                "WHERE user_id=?",
                (prefix, user_id),
            )