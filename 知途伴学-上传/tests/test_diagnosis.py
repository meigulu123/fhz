"""P2 验证：自适应测验导航（主链上跳/先修下钻）与终止条件、诊断报告"""
from pathlib import Path

import pytest

from src.kg.loader import KnowledgeGraph
from src.path.planner import PathPlanner
from src.student.diagnosis import AdaptiveQuiz, build_report
from src.student.profile import StudentProfile, init_mastery

KG_PATH = Path(__file__).resolve().parent.parent / "data" / "kg" / "ml_kg.json"
CHAIN = ["b01", "s02", "s03", "e01", "e04", "d01", "d02", "d08"]


def synth_qbank():
    """合成题库：主链 8 节点 × 3 题（测试不依赖数据生成任务）"""
    qs = []
    for nid in CHAIN:
        for i in range(1, 4):
            qs.append({
                "id": f"q_{nid}_{i:02d}", "node_id": nid, "type": "single",
                "difficulty": 0.4, "stem": f"{nid} 测试题 {i}",
                "options": ["A. 一", "B. 二", "C. 三", "D. 四"], "answer": "A",
                "explanation": "解析", "hints": {"L0": "h0", "L1": "h1", "L2": "h2", "L3": "h3"},
                "variant": {"stem": "变式", "options": ["A. 一", "B. 二", "C. 三", "D. 四"],
                            "answer": "B", "explanation": "变式解析"},
            })
    return qs


@pytest.fixture(scope="module")
def kg():
    return KnowledgeGraph.load(str(KG_PATH))


def test_navigation_correct_moves_up_chain(kg):
    quiz = AdaptiveQuiz(kg, synth_qbank())
    st = quiz.new_state()
    assert st.current_node == "b01"
    quiz.record(st, quiz.next_question(st), True)
    assert st.current_node == "s02"
    quiz.record(st, quiz.next_question(st), True)
    assert st.current_node == "s03"


def test_navigation_wrong_drills_prereq(kg):
    quiz = AdaptiveQuiz(kg, synth_qbank())
    st = quiz.new_state()
    quiz.record(st, quiz.next_question(st), True)   # b01 → s02
    quiz.record(st, quiz.next_question(st), True)   # s02 → s03
    quiz.record(st, quiz.next_question(st), False)  # s03 错 → 下钻先修
    assert st.current_node in kg.prereqs_of("s03")
    assert st.current_node != "s02"  # s02 已覆盖，钻到 b02


def test_terminates_by_question_limit(kg):
    quiz = AdaptiveQuiz(kg, synth_qbank())
    st = quiz.new_state()
    pattern = [True, False]
    while not st.finished and st.questions_asked < 30:
        q = quiz.next_question(st)
        if q["id"] is None:
            break
        quiz.record(st, q, pattern[st.questions_asked % 2])
    assert st.finished
    assert st.stop_reason in ("达到题量上限", "已覆盖足够知识点", "水平边界震荡，诊断收敛", "题库耗尽")
    assert st.questions_asked <= 12 + 3  # 终止后允许最后一次移动


def test_no_repeat_questions(kg):
    quiz = AdaptiveQuiz(kg, synth_qbank())
    st = quiz.new_state()
    ids = []
    for _ in range(6):
        q = quiz.next_question(st)
        if q["id"] is None:
            break
        ids.append(q["id"])
        quiz.record(st, q, True)
    assert len(ids) == len(set(ids))


def test_report_builder(kg):
    p = StudentProfile(student_id="t001")
    init_mastery(p, kg)
    quiz = AdaptiveQuiz(kg, synth_qbank())
    st = quiz.new_state()
    quiz.record(st, quiz.next_question(st), True)
    quiz.record(st, quiz.next_question(st), False)
    quiz.stop(st)
    report = build_report(p, kg, PathPlanner(kg), st)
    assert set(report) >= {"weak", "strong", "band", "suggested", "accuracy"}
    assert report["total_questions"] == 2
    assert report["accuracy"] == 0.5
