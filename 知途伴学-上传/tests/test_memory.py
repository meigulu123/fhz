"""P3 验证：记忆库 7 表读写、检索排序（关键词+时间衰减）、反思触发条件"""
import time
from pathlib import Path

import pytest

from src.kg.loader import KnowledgeGraph
from src.llm.mock import MockLLM
from src.memory.db import MemoryStore
from src.memory.reflection import maybe_reflect
from src.memory.retrieve import retrieve
from src.student.profile import StudentProfile, init_mastery

KG_PATH = Path(__file__).resolve().parent.parent / "data" / "kg" / "ml_kg.json"


def _qbank():
    return [{
        "id": "q_b01_01", "node_id": "b01", "type": "single", "difficulty": 0.3,
        "stem": "什么是监督学习？", "options": ["A. 一", "B. 二", "C. 三", "D. 四"],
        "answer": "A", "explanation": "解析",
        "hints": {"L0": "h0", "L1": "h1", "L2": "h2", "L3": "h3"},
    }]


@pytest.fixture(scope="module")
def kg():
    return KnowledgeGraph.load(str(KG_PATH))


@pytest.fixture()
def mem(tmp_path):
    m = MemoryStore(str(tmp_path / "test_memory.db"))
    yield m
    m.close()


@pytest.fixture()
def profile(kg):
    p = StudentProfile(student_id="s001", name="小明")
    init_mastery(p, kg)
    return p


# ---------- 学生与画像 ----------
def test_student_roundtrip(mem, profile):
    mem.save_student(profile)
    data = mem.load_student("s001")
    assert data["name"] == "小明"
    assert data["student_id"] == "s001"
    # 掌握度快照恢复
    mem.snapshot_mastery("s001", "b01", 0.72, 4)
    restored = mem.restore_profile("s001")
    assert restored.mastery["b01"] == 0.72
    assert restored.evidence_count["b01"] == 4
    # 同 id 再次保存走 upsert，不报错
    profile.name = "小明2"
    mem.save_student(profile)
    assert mem.load_student("s001")["name"] == "小明2"


def test_session_lifecycle(mem):
    sid = mem.start_session("s001")
    mem.log_interaction(sid, "s001", "message", "", "你好")
    mem.log_interaction(sid, "s001", "quiz", "b01", "答对了")
    assert mem.interaction_count(sid) == 2
    mem.end_session(sid, "今天学了线性回归")
    assert mem.recent_interactions("s001")[0]["content"] == "答对了"


# ---------- 检索排序 ----------
def test_retrieve_keyword_relevance(mem):
    sid = mem.start_session("s001")
    mem.log_interaction(sid, "s001", "quiz", "s02", "线性回归 损失函数 最小二乘")
    mem.log_interaction(sid, "s001", "quiz", "d08", "Transformer 自注意力 编码器")
    mem.log_interaction(sid, "s001", "message", "", "今天天气不错")
    top = retrieve(mem, "s001", "线性回归损失函数")
    assert len(top) >= 2
    assert "s02" in [t["node_id"] for t in top[:2]]      # 关键词命中优先
    assert top[0]["node_id"] == "s02"


def test_retrieve_recency_boost(mem):
    sid = mem.start_session("s001")
    now = time.time()
    # 同内容两条，一旧一新
    mem.conn.execute(
        "INSERT INTO interactions (session_id, student_id, ts, kind, node_id, content)"
        " VALUES (?,?,?,?,?,?)",
        (sid, "s001", now - 30 * 86400, "quiz", "s02", "线性回归 复习"))
    mem.conn.execute(
        "INSERT INTO interactions (session_id, student_id, ts, kind, node_id, content)"
        " VALUES (?,?,?,?,?,?)",
        (sid, "s001", now, "quiz", "s02", "线性回归 复习"))
    mem.conn.commit()
    top = retrieve(mem, "s001", "线性回归", now=now)
    # 两条都命中，新的（id 更大）排前
    assert top[0]["id"] > top[1]["id"]


# ---------- 反思触发 ----------
def test_reflect_on_session_end(mem, profile, kg):
    llm = MockLLM(kg, _qbank())
    sid = mem.start_session("s001")
    r = maybe_reflect(mem, llm, kg, profile, sid, "session_end", 5)
    assert r is not None
    assert set(r) >= {"progress_summary", "effective_strategies",
                      "plan_adjustments", "next_session_preview"}
    last = mem.last_reflection("s001")
    assert last["progress_summary"] == r["progress_summary"]


def test_reflect_periodic_every_20(mem, profile, kg):
    llm = MockLLM(kg, _qbank())
    sid = mem.start_session("s001")
    assert maybe_reflect(mem, llm, kg, profile, sid, "periodic", 3) is None
    assert maybe_reflect(mem, llm, kg, profile, sid, "periodic", 19) is None
    r = maybe_reflect(mem, llm, kg, profile, sid, "periodic", 20)
    assert r is not None


def test_reflect_no_trigger(mem, profile, kg):
    llm = MockLLM(kg, _qbank())
    sid = mem.start_session("s001")
    assert maybe_reflect(mem, llm, kg, profile, sid, "teach", 1) is None


def test_reflect_failure_does_not_raise(mem, profile, kg):
    class BadLLM:
        def chat_json(self, messages):
            raise RuntimeError("LLM 挂了")

    sid = mem.start_session("s001")
    assert maybe_reflect(mem, BadLLM(), kg, profile, sid, "session_end", 1) is None


# ---------- 计划与提示记录 ----------
def test_plan_and_hint_logs(mem):
    sid = mem.start_session("s001")
    mem.save_plan(sid, "s001", 0.74, {"z_low": 0.3, "z_high": 0.45},
                  {"items": [{"node_id": "b01"}]})
    mem.log_hint(sid, "s001", "b01", "q_b01_01", "L1")
    row = mem.conn.execute(
        "SELECT COUNT(*) AS n FROM hint_usage WHERE student_id='s001'").fetchone()
    assert row["n"] == 1
