"""知识问答（RAG）测试：KG 节点检索 + 自由提问作答"""
import json
from pathlib import Path

import pytest

from src.agent.orchestrator import Orchestrator
from src.agent.state import AgentState, TEACHING
from src.kg.loader import KnowledgeGraph
from src.llm.mock import MockLLM
from src.memory.db import MemoryStore
from src.memory.retrieve import retrieve_node
from src.path.planner import PathPlanner
from src.student.profile import StudentProfile

ROOT = Path(__file__).resolve().parent.parent
KG_PATH = ROOT / "data" / "kg" / "ml_kg.json"
Q_PATH = ROOT / "data" / "kg" / "questions.json"


@pytest.fixture(scope="module")
def kg():
    return KnowledgeGraph.load(str(KG_PATH))


def test_retrieve_node_hit(kg):
    hits = retrieve_node(kg, "什么是反向传播")
    assert hits and hits[0] == "d02"


def test_retrieve_node_miss(kg):
    assert retrieve_node(kg, "今天天气怎么样") == []


def test_retrieve_node_comparison_multi(kg):
    """跨知识点对比问题应命中多个节点（如「线性回归 vs 逻辑回归」）"""
    hits = retrieve_node(kg, "线性回归和逻辑回归有什么区别", top_k=3)
    assert len(hits) >= 2


def test_answer_question_in_teaching(kg, tmp_path):
    qbank = json.loads(Q_PATH.read_text(encoding="utf-8"))["questions"]
    mem = MemoryStore(str(tmp_path / "qa.db"))
    try:
        orch = Orchestrator(kg, MockLLM(kg, qbank), mem, PathPlanner(kg), qbank)
        state = AgentState(student_id="qauser")
        state.profile = StudentProfile(student_id="qauser")
        state.phase = TEACHING
        state.current_node = "d02"
        state.session_id = 1
        reply, payload = orch.handle(state, "什么是反向传播？")
        assert "反向传播" in reply
        assert state.phase == TEACHING          # 问答不打断教学状态机
        row = mem.conn.execute(
            "SELECT COUNT(*) AS n FROM interactions WHERE kind='qa'").fetchone()
        assert row["n"] >= 1
    finally:
        mem.close()
