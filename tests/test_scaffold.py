"""P3 验证：脚手架卡住判定（OR 信号）、L0→L3 升级、L3 重规划信号、退出记录"""
from pathlib import Path

import pytest

from src.kg.loader import KnowledgeGraph
from src.llm.mock import MockLLM
from src.student.profile import StudentProfile
from src.tutor.scaffold import ScaffoldState, Scaffolder, detect_stuck

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
def scaffolder(kg):
    return Scaffolder(MockLLM(kg, _qbank()), _qbank())


# ---------- 卡住判定 ----------
def test_detect_stuck_confusion():
    assert detect_stuck(ScaffoldState(), "confusion", "", []) is True


def test_detect_stuck_confusion_words():
    for w in ["不会", "卡住了", "帮帮我", "太难了"]:
        assert detect_stuck(ScaffoldState(), "answer", w, []) is True


def test_detect_stuck_wrong_streak():
    st = ScaffoldState()
    st.wrong_streak = 2
    assert detect_stuck(st, "answer", "这题我再想想", []) is True


def test_detect_stuck_recent_accuracy():
    assert detect_stuck(ScaffoldState(), "answer", "继续", [False, False, False]) is True
    assert detect_stuck(ScaffoldState(), "answer", "继续", [True, False, True]) is False


def test_detect_stuck_help_streak():
    st = ScaffoldState()
    st.help_streak = 2
    assert detect_stuck(st, "answer", "嗯", []) is True


def test_detect_stuck_clean():
    assert detect_stuck(ScaffoldState(), "answer", "我知道了，继续吧", []) is False


# ---------- 升级阶梯 ----------
def test_escalation_ladder_to_replan(scaffolder):
    st = ScaffoldState()
    r0 = scaffolder.engage(st, "q_b01_01", "b01")
    assert r0["level"] == "L0" and st.active and "h0" in r0["text"]
    r1 = scaffolder.on_wrong(st)
    assert r1["level"] == "L1" and "h1" in r1["text"]
    r2 = scaffolder.on_wrong(st)
    assert r2["level"] == "L2" and "h2" in r2["text"]
    r3 = scaffolder.on_wrong(st)
    assert r3["level"] == "L3" and "h3" in r3["text"]
    r4 = scaffolder.on_wrong(st)
    assert r4["replan"] is True  # L3 仍错 → 重规划信号


def test_help_escalates(scaffolder):
    st = ScaffoldState()
    scaffolder.engage(st, "q_b01_01", "b01")
    r = scaffolder.on_help(st)
    assert r["level"] == "L1" and st.help_streak == 1


def test_escalate_without_engage_is_silent(scaffolder):
    st = ScaffoldState()
    r = scaffolder.on_wrong(st)
    assert r == {"level": "L0", "text": None, "replan": False}


# ---------- 退出与记录 ----------
def test_on_correct_records_hint_profile_and_resets(scaffolder):
    st = ScaffoldState()
    scaffolder.engage(st, "q_b01_01", "b01")
    scaffolder.on_wrong(st)
    scaffolder.on_wrong(st)          # 升到 L2
    profile = StudentProfile(student_id="t001")
    scaffolder.on_correct(st, profile)
    assert profile.hint_profile["b01"] == 2
    assert st.active is False and st.level == 0 and st.wrong_streak == 0
