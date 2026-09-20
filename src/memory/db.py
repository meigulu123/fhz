"""记忆库：SQLite（WAL 模式）9 张表

accounts / students / sessions / interactions / mastery_snapshots /
reflections / study_plans / hint_usage / profile_observations

线程安全说明：Streamlit 每次交互 rerun 可能切换执行线程，连接以
check_same_thread=False 打开，所有读写经 RLock 串行化。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    name TEXT DEFAULT '同学',
    major TEXT DEFAULT '',
    goals_json TEXT DEFAULT '[]',
    goal_keywords_json TEXT DEFAULT '[]',
    style_tags_json TEXT DEFAULT '[]',
    prior_json TEXT DEFAULT '{}',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    started_at REAL,
    ended_at REAL,
    summary TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    student_id TEXT,
    ts REAL,
    kind TEXT,               -- message | quiz | scaffold | teach | plan | report
    node_id TEXT,
    content TEXT,
    mastery_delta_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS mastery_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,
    node_id TEXT,
    theta REAL,
    evidence_count INTEGER,
    ts REAL
);
CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    student_id TEXT,
    ts REAL,
    trigger TEXT,            -- session_end | node_done | stuck_l3 | periodic
    content_json TEXT
);
CREATE TABLE IF NOT EXISTS study_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    student_id TEXT,
    ts REAL,
    pace REAL,
    band_json TEXT,
    plan_json TEXT
);
CREATE TABLE IF NOT EXISTS hint_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    student_id TEXT,
    node_id TEXT,
    question_id TEXT,
    level TEXT,              -- L0~L3
    ts REAL
);
CREATE TABLE IF NOT EXISTS profile_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,
    ts REAL,
    reason TEXT,             -- session_end | idle
    content_json TEXT        -- 风格标签增量/目标变化/一句话认知观察
);
CREATE INDEX IF NOT EXISTS idx_interactions_student ON interactions(student_id, ts);
CREATE INDEX IF NOT EXISTS idx_snapshots_student ON mastery_snapshots(student_id, ts);
"""

# 活跃时长口径：相邻交互间隔超过 10 分钟视为离开，单条交互至少计 1 分钟
_ACTIVE_GAP = 600
_MIN_TICK = 60


def _active_seconds(ts_list) -> float:
    """活跃学习时长（秒）：按交互时间戳累计

    相邻交互的间隔 ≤ _ACTIVE_GAP 全部计入（即连续操作期间算作在学习）；
    超过视为挂机/离开，间隙不计时长，新段起点补 _MIN_TICK（保证只看一道
    题也有合理的最小时长）。
    """
    if not ts_list:
        return 0.0
    ts_list = sorted(ts_list)
    total = float(_MIN_TICK)
    prev = ts_list[0]
    for b in ts_list[1:]:
        gap = b - prev
        total += gap if gap <= _ACTIVE_GAP else _MIN_TICK
        prev = b
    return total


class MemoryStore:
    """记忆库统一入口（线程安全；单进程应用够用）"""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ---------- 账户 ----------
    @staticmethod
    def _hash_password(password: str, salt: bytes | None = None) -> str:
        """PBKDF2-SHA256 加盐哈希（标准库实现，无外部依赖）"""
        salt = salt or os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     salt, 100_000)
        return salt.hex() + "$" + digest.hex()

    def create_account(self, username: str, password: str) -> bool:
        """注册账户；用户名已存在返回 False"""
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO accounts (username, password_hash, created_at)"
                    " VALUES (?,?,?)",
                    (username, self._hash_password(password), time.time()))
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def account_exists(self, username: str) -> bool:
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone()
        return row is not None

    def check_account(self, username: str, password: str) -> bool:
        """校验账户密码（常量时间比较不在此层做——本地单机应用）"""
        with self._lock:
            row = self.conn.execute(
                "SELECT password_hash FROM accounts WHERE username=?",
                (username,)).fetchone()
        if row is None:
            return False
        salt_hex, sep, digest_hex = row["password_hash"].partition("$")
        try:
            salt = bytes.fromhex(salt_hex)
        except ValueError:
            return False
        return sep == "$" and self._hash_password(password, salt).split("$")[1] == digest_hex

    def change_password(self, username: str, old_password: str,
                        new_password: str) -> bool:
        """修改密码：原密码校验通过才更新（返回是否成功）"""
        if not self.check_account(username, old_password):
            return False
        with self._lock:
            self.conn.execute(
                "UPDATE accounts SET password_hash=? WHERE username=?",
                (self._hash_password(new_password), username))
            self.conn.commit()
        return True

    def account_info(self, username: str) -> dict | None:
        """账户基础信息（注册时间等）"""
        with self._lock:
            row = self.conn.execute(
                "SELECT username, created_at FROM accounts WHERE username=?",
                (username,)).fetchone()
        return dict(row) if row else None

    def account_stats(self, student_id: str) -> dict:
        """账户下的学习数据规模（账户管理页展示）"""
        with self._lock:
            def count(sql, *args):
                return self.conn.execute(sql, args).fetchone()["n"]
            return {
                "sessions": count(
                    "SELECT COUNT(*) AS n FROM sessions WHERE student_id=?", student_id),
                "interactions": count(
                    "SELECT COUNT(*) AS n FROM interactions WHERE student_id=?", student_id),
                "reflections": count(
                    "SELECT COUNT(*) AS n FROM reflections WHERE student_id=?", student_id),
                "snapshots": count(
                    "SELECT COUNT(*) AS n FROM mastery_snapshots WHERE student_id=?", student_id),
                "plans": count(
                    "SELECT COUNT(*) AS n FROM study_plans WHERE student_id=?", student_id),
            }

    def clear_student_data(self, student_id: str) -> int:
        """清空该账户的学习数据（保留账户本身），返回删除的记录条数"""
        tables = ("interactions", "mastery_snapshots", "reflections",
                  "study_plans", "hint_usage", "sessions", "students")
        removed = 0
        with self._lock:
            for table in tables:
                cur = self.conn.execute(
                    f"DELETE FROM {table} WHERE student_id=?", (student_id,))
                removed += cur.rowcount if cur.rowcount > 0 else 0
            self.conn.commit()
        return removed

    # ---------- 学生 ----------
    def save_student(self, profile) -> None:
        # 用鸭子类型而非 isinstance：Streamlit 热重载模块后，缓存里的旧类实例
        # 与重新导入的新类不是同一个类对象，isinstance 会误判（线上实测触发过）
        p = profile.to_dict() if hasattr(profile, "to_dict") else profile
        with self._lock:
            self.conn.execute(
                """INSERT INTO students (student_id, name, major, goals_json, goal_keywords_json,
                   style_tags_json, prior_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(student_id) DO UPDATE SET
                   name=excluded.name, major=excluded.major, goals_json=excluded.goals_json,
                   goal_keywords_json=excluded.goal_keywords_json,
                   style_tags_json=excluded.style_tags_json, prior_json=excluded.prior_json""",
                (p["student_id"], p.get("name", "同学"), p.get("major", ""),
                 json.dumps(p.get("goals", []), ensure_ascii=False),
                 json.dumps(p.get("goal_keywords", []), ensure_ascii=False),
                 json.dumps(p.get("style_tags", []), ensure_ascii=False),
                 json.dumps(p.get("prior", {}), ensure_ascii=False),
                 p.get("created_at", time.time())),
            )
            self.conn.commit()

    def load_student(self, student_id) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM students WHERE student_id=?", (student_id,)).fetchone()
        if row is None:
            return None
        return {
            "student_id": row["student_id"], "name": row["name"], "major": row["major"],
            "goals": json.loads(row["goals_json"]),
            "goal_keywords": json.loads(row["goal_keywords_json"]),
            "style_tags": json.loads(row["style_tags_json"]),
            "prior": json.loads(row["prior_json"]),
            "created_at": row["created_at"],
        }

    def restore_profile(self, student_id):
        """从库恢复画像（含掌握度快照），返回 StudentProfile 或 None"""
        from src.student.profile import StudentProfile
        data = self.load_student(student_id)
        if data is None:
            return None
        profile = StudentProfile(**data)
        with self._lock:
            rows = self.conn.execute(
                """SELECT node_id, theta, evidence_count FROM mastery_snapshots
                   WHERE student_id=? AND (node_id, ts) IN
                     (SELECT node_id, MAX(ts) FROM mastery_snapshots
                      WHERE student_id=? GROUP BY node_id)""",
                (student_id, student_id)).fetchall()
        for r in rows:
            profile.mastery[r["node_id"]] = r["theta"]
            profile.evidence_count[r["node_id"]] = r["evidence_count"]
        return profile

    # ---------- 会话 ----------
    def start_session(self, student_id: str) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO sessions (student_id, started_at) VALUES (?,?)",
                (student_id, time.time()))
            self.conn.commit()
            return cur.lastrowid

    def end_session(self, session_id: int, summary: str = "") -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET ended_at=?, summary=? WHERE session_id=?",
                (time.time(), summary, session_id))
            self.conn.commit()

    # ---------- 记录 ----------
    def log_interaction(self, session_id, student_id, kind, node_id, content,
                        mastery_delta=None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO interactions (session_id, student_id, ts, kind, node_id, content, mastery_delta_json)"
                " VALUES (?,?,?,?,?,?,?)",
                (session_id, student_id, time.time(), kind, node_id, content,
                 json.dumps(mastery_delta or {}, ensure_ascii=False)))
            self.conn.commit()

    def snapshot_mastery(self, student_id, node_id, theta, evidence_count) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO mastery_snapshots (student_id, node_id, theta, evidence_count, ts)"
                " VALUES (?,?,?,?,?)",
                (student_id, node_id, theta, evidence_count, time.time()))
            self.conn.commit()

    def save_reflection(self, session_id, student_id, trigger, content: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO reflections (session_id, student_id, ts, trigger, content_json)"
                " VALUES (?,?,?,?,?)",
                (session_id, student_id, time.time(), trigger,
                 json.dumps(content, ensure_ascii=False)))
            self.conn.commit()

    def save_plan(self, session_id, student_id, pace, band, plan) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO study_plans (session_id, student_id, ts, pace, band_json, plan_json)"
                " VALUES (?,?,?,?,?,?)",
                (session_id, student_id, time.time(), pace,
                 json.dumps(band, ensure_ascii=False),
                 json.dumps(plan, ensure_ascii=False)))
            self.conn.commit()

    def log_hint(self, session_id, student_id, node_id, question_id, level) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO hint_usage (session_id, student_id, node_id, question_id, level, ts)"
                " VALUES (?,?,?,?,?,?)",
                (session_id, student_id, node_id, question_id, level, time.time()))
            self.conn.commit()

    # ---------- 查询 ----------
    def last_reflection(self, student_id) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT content_json FROM reflections WHERE student_id=? ORDER BY id DESC LIMIT 1",
                (student_id,)).fetchone()
        return json.loads(row["content_json"]) if row else None

    def has_study_history(self, student_id) -> bool:
        """是否真正学过内容（teach/scaffold 交互），区别于仅完成学情诊断"""
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM interactions WHERE student_id=?"
                " AND kind IN ('teach','scaffold') LIMIT 1",
                (student_id,)).fetchone()
        return row is not None

    def list_students_with_data(self) -> list:
        """库内全部有画像的学生 ID（画像页学生切换器数据源）"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT DISTINCT student_id FROM students ORDER BY created_at"
            ).fetchall()
        return [r["student_id"] for r in rows]

    def recent_interactions(self, student_id, limit=20) -> list:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM interactions WHERE student_id=? ORDER BY id DESC LIMIT ?",
                (student_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def snapshot_history(self, student_id) -> list:
        """该学生按时间排序的掌握度快照（画像页趋势图用）"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT node_id, theta, ts FROM mastery_snapshots WHERE student_id=? ORDER BY ts",
                (student_id,)).fetchall()
        return [dict(r) for r in rows]

    def plan_history(self, student_id, limit=10) -> list:
        """历史学习计划（路径页版本对比用）"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT ts, pace, band_json, plan_json FROM study_plans"
                " WHERE student_id=? ORDER BY id DESC LIMIT ?",
                (student_id, limit)).fetchall()
        out = []
        for r in rows:
            try:
                out.append({"ts": r["ts"], "pace": r["pace"],
                            "band": json.loads(r["band_json"]),
                            "plan": json.loads(r["plan_json"])})
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def interaction_count(self, session_id) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM interactions WHERE session_id=?",
                (session_id,)).fetchone()
        return row["n"]

    def list_sessions(self, student_id, limit=50) -> list:
        """该学生的会话列表（新的在前），供历史对话页展示"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT session_id, started_at, ended_at, summary FROM sessions"
                " WHERE student_id=? ORDER BY session_id DESC LIMIT ?",
                (student_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def session_interactions(self, session_id, limit=20) -> list:
        """某会话内的交互记录（历史对话页展开用）"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT ts, kind, content FROM interactions WHERE session_id=?"
                " ORDER BY id LIMIT ?", (session_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def quiz_stats(self, student_id) -> dict:
        """测验统计：总数/正确/错误（从 interactions 的 quiz 记录解析）"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT mastery_delta_json FROM interactions"
                " WHERE student_id=? AND kind='quiz'", (student_id,)).fetchall()
        total = correct = 0
        for r in rows:
            try:
                d = json.loads(r["mastery_delta_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            total += 1
            if d.get("correct"):
                correct += 1
        return {"total": total, "correct": correct, "wrong": total - correct}

    def wrong_attempts(self, student_id) -> list:
        """答错的题（新的在前），供错题本展示"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT session_id, node_id, content, ts, mastery_delta_json"
                " FROM interactions WHERE student_id=? AND kind='quiz'"
                " ORDER BY id DESC", (student_id,)).fetchall()
        out = []
        for r in rows:
            try:
                d = json.loads(r["mastery_delta_json"])
            except (json.JSONDecodeError, TypeError):
                d = {}
            if not d.get("correct"):
                out.append({"session_id": r["session_id"],
                            "node_id": r["node_id"],
                            "content": r["content"], "ts": r["ts"]})
        return out

    def total_duration(self, student_id) -> float:
        """活跃学习时长（秒）：按交互时间间隔累计，挂机不累计

        相邻交互间隔 ≤ _ACTIVE_GAP 计入学习时长，超过视为离开；单条交互
        计 _MIN_TICK。基于 interactions 而非 sessions，反映真实使用时长。
        """
        with self._lock:
            rows = self.conn.execute(
                "SELECT ts FROM interactions WHERE student_id=? ORDER BY ts",
                (student_id,)).fetchall()
        return _active_seconds([r["ts"] for r in rows])

    def duration_by_day(self, student_id, days=7) -> list:
        """近 N 天每日活跃学习时长（秒），按交互时间折算到当天"""
        now = time.time()
        day0 = now - now % 86400
        start = day0 - (days - 1) * 86400
        with self._lock:
            rows = self.conn.execute(
                "SELECT ts FROM interactions WHERE student_id=? ORDER BY ts",
                (student_id,)).fetchall()
        by_day = {i: [] for i in range(days)}
        for r in rows:
            ts = r["ts"]
            if ts < start:
                continue
            idx = int((ts - start) // 86400)
            if idx < days:
                by_day[idx].append(ts)
        return [{"day_offset": i, "seconds": _active_seconds(by_day[i])}
                for i in range(days)]

    # ---------- 画像观察（对话驱动的画像持续更新） ----------
    def save_profile_observation(self, student_id, reason, content: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO profile_observations (student_id, ts, reason, content_json)"
                " VALUES (?,?,?,?)",
                (student_id, time.time(), reason,
                 json.dumps(content, ensure_ascii=False)))
            self.conn.commit()

    def list_observations(self, student_id, limit=8) -> list:
        """画像观察记录（新的在前），画像页「大模型观察」区展示"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT ts, reason, content_json FROM profile_observations"
                " WHERE student_id=? ORDER BY id DESC LIMIT ?",
                (student_id, limit)).fetchall()
        out = []
        for r in rows:
            try:
                content = json.loads(r["content_json"])
            except (json.JSONDecodeError, TypeError):
                content = {}
            out.append({"ts": r["ts"], "reason": r["reason"], "content": content})
        return out

    def latest_observation_ts(self, student_id) -> float:
        with self._lock:
            row = self.conn.execute(
                "SELECT MAX(ts) AS ts FROM profile_observations WHERE student_id=?",
                (student_id,)).fetchone()
        return row["ts"] or 0.0

    def latest_interaction_ts(self, student_id) -> float:
        with self._lock:
            row = self.conn.execute(
                "SELECT MAX(ts) AS ts FROM interactions WHERE student_id=?",
                (student_id,)).fetchone()
        return row["ts"] or 0.0

    def close(self):
        with self._lock:
            self.conn.close()
