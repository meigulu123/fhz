"""P5 验证：本轮新增能力的回归基线

覆盖：错因判定与靶向反问（C1）、间隔重复复习排程（B1）、诊断置信度与熟练度（A1/A3）、
路径评分六因子（B2）、脚手架按错因/依赖度起步（C1/C2）、学习投入口径，
以及「内存字段跨会话派生回填」与「反思调整先修门槛」（P0/P1 修复项）。
"""
import time
from pathlib import Path

import pytest

from src.agent.orchestrator import GEN_CAP_PER_NODE, Orchestrator
from src.agent.state import QUIZZING, AgentState
from src.kg.loader import KnowledgeGraph
from src.llm.mock import MockLLM
from src.memory.db import MemoryStore
from src.path.planner import PathPlanner
from src.path.review import INTERVALS, due_reviews, urgency
from src.student.diagnosis import (confidence_summary, effort_score,
                                   node_confidence, proficiency)
from src.student.error_cause import ADVICE, CAUSES, PROBES, cause_note, cause_probe, error_cause
from src.student.profile import StudentProfile, init_mastery
from src.student.question_gen import gen_question, rule_question
from src.student.update import mastery_update
from src.tutor.scaffold import ScaffoldState, Scaffolder
from src.ui.components import growth_figure, kg_figure
from src.ui.env import build_env
from src.ui.report_export import build_html_report

KG_PATH = Path(__file__).resolve().parent.parent / "data" / "kg" / "ml_kg.json"
DAY = 86400.0


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
    m = MemoryStore(str(tmp_path / "caps.db"))
    yield m
    m.close()


@pytest.fixture()
def profile(kg):
    p = StudentProfile(student_id="s001", name="小明")
    init_mastery(p, kg)
    for nid in p.mastery:
        p.mastery[nid] = 0.0
    return p


@pytest.fixture()
def env(tmp_path, kg):
    m = MemoryStore(str(tmp_path / "caps_orch.db"))
    qbank = _qbank()
    orch = Orchestrator(kg, MockLLM(kg, qbank), m, PathPlanner(kg), qbank)
    yield orch, m, kg
    m.close()


# ---------- C1 错因判定 ----------
def test_error_cause_four_classes(kg, profile):
    """反复出错 / 基础薄弱 / 粗心审题 / 理解偏差 四类判据"""
    profile.mastery["b01"] = 0.8
    assert error_cause({"node_id": "b01", "difficulty": 0.3}, profile, count=2)[0] == CAUSES[0]
    profile.mastery["b01"] = 0.2
    assert error_cause({"node_id": "b01", "difficulty": 0.3}, profile, count=1)[0] == CAUSES[1]
    profile.mastery["b01"] = 0.7
    assert error_cause({"node_id": "b01", "difficulty": 0.8}, profile, count=1)[0] == CAUSES[2]
    assert error_cause({"node_id": "b01", "difficulty": 0.5}, profile, count=1)[0] == CAUSES[3]


def test_error_cause_hint_and_probe_cover_all(kg, profile):
    for cause in CAUSES:
        assert ADVICE[cause] and PROBES[cause]
    assert error_cause({"node_id": "b01", "difficulty": 0.3}, None, 1)[0] in CAUSES
    assert cause_probe("未知错因")            # 兜底引导非空
    assert CAUSES[0] in cause_note(CAUSES[0])


# ---------- C1/C2 脚手架靶向与依赖度 ----------
def test_scaffold_targeted_probe_at_l0(kg):
    qb = _qbank()
    sc = Scaffolder(MockLLM(kg, qb), qb)
    st = ScaffoldState()
    r = sc.engage(st, "q_b01_01", "b01", cause="概念混淆")
    assert r["level"] == "L0"
    assert "概念混淆" in r["text"]            # L0 按错因反问，而非统一提示


def test_scaffold_start_level_from_dependency(kg):
    qb = _qbank()
    sc = Scaffolder(MockLLM(kg, qb), qb)
    st = ScaffoldState()
    r = sc.engage(st, "q_b01_01", "b01", cause="基础薄弱", start_level=1)
    assert r["level"] == "L1" and st.level == 1
    st2 = ScaffoldState()
    assert sc.engage(st2, "q_b01_01", "b01", start_level=9)["level"] == "L2"  # 上限裁剪


# ---------- B1 间隔重复复习排程 ----------
def test_urgency_bounds():
    assert urgency(0.0) == 1.0 and urgency(-10.0) == 1.0
    assert urgency(3.0) == 0.0 and urgency(99.0) == 0.0
    assert 0.0 < urgency(1.5) < 1.0


def test_due_reviews_interval_and_overdue(kg, profile):
    now = 1_000_000.0
    profile.mastery["b01"] = 0.5
    rows = due_reviews(profile, kg, hits={"b01": 0},
                       last_map={"b01": now - 5 * DAY}, now=now)
    r = next(x for x in rows if x["node_id"] == "b01")
    assert r["interval_days"] == INTERVALS[0]      # 答对 0 次 → 1 天档
    assert r["overdue"] is True and r["urgency"] == 1.0


def test_due_reviews_interval_grows_with_correct_hits(kg, profile):
    now = 1_000_000.0
    profile.mastery["b01"] = 0.5
    rows = due_reviews(profile, kg, hits={"b01": 3},
                       last_map={"b01": now - 5 * DAY}, now=now)
    r = next(x for x in rows if x["node_id"] == "b01")
    assert r["interval_days"] == INTERVALS[-1]     # 答对 3+ 次 → 15 天档
    assert r["overdue"] is False


def test_due_reviews_skips_mastered_and_untouched(kg, profile):
    now = 1_000_000.0
    profile.mastery["b01"] = 0.9                    # 已掌握
    assert not [x for x in due_reviews(profile, kg, last_map={"b01": now},
                                       now=now) if x["node_id"] == "b01"]
    profile.mastery["b01"] = 0.5                    # 无接触记录
    assert not [x for x in due_reviews(profile, kg, last_map={}, now=now)
                if x["node_id"] == "b01"]


# ---------- A1/A3 置信度与熟练度 ----------
def test_node_confidence_tiers(kg, profile):
    profile.mastery["b01"], profile.evidence_count["b01"] = 0.9, 3
    assert node_confidence(profile, "b01") == 100
    profile.mastery["b01"] = 0.5                    # 判定不明确
    assert node_confidence(profile, "b01") == 0
    profile.mastery["b01"], profile.evidence_count["b01"] = 0.9, 1
    assert node_confidence(profile, "b01") == 33    # 证据不足
    assert node_confidence(profile, "never_seen") == 0


def test_confidence_summary_flags_low(kg, profile):
    profile.mastery["b01"], profile.evidence_count["b01"] = 0.5, 3
    summary = confidence_summary(profile, kg)
    assert "b01" in summary["low"] and summary["low_names"]


def test_proficiency():
    assert proficiency(1.0, 40) == 1.0
    assert proficiency(0.8, None) == 0.56
    assert proficiency(1.0, 200) == 0.4             # 速度系数下限
    assert proficiency(0.0, 30) == 0.0


def test_effort_only_counts_correct(mem):
    """学习投入只认答对：答错与时长都不计入"""
    mem.log_interaction(1, "s1", "quiz", "b01", "✓ 对", {"correct": True})
    mem.log_interaction(1, "s1", "quiz", "b01", "✗ 错", {"correct": False})
    assert effort_score(mem, "s1") == pytest.approx(1 / 60)
    for _ in range(80):
        mem.log_interaction(1, "s1", "quiz", "b01", "✓ 对", {"correct": True})
    assert effort_score(mem, "s1") == 1.0


# ---------- B2 路径评分六因子 ----------
def test_score_terms_weights_and_review_factor(kg):
    planner = PathPlanner(kg)
    p = StudentProfile(student_id="t_sc")
    init_mastery(p, kg)
    for nid in p.mastery:
        p.mastery[nid] = 0.3
    band = planner.zpd_band(p)
    terms = planner.score_terms("m01", p, band)
    assert sum(terms.values()) == pytest.approx(planner.score("m01", p, band), abs=1e-4)
    assert terms["复习紧迫"] == 0.0
    s0 = planner.score("m01", p, band)
    s1 = planner.score("m01", p, band, review={"m01": 1.0})
    assert s1 == pytest.approx(s0 + 0.10, abs=1e-4)   # 第 6 因子权重 0.10


def test_plan_items_expose_terms_and_keep_order(kg):
    planner = PathPlanner(kg)
    p = StudentProfile(student_id="t_pt")
    init_mastery(p, kg)
    for nid in p.mastery:
        p.mastery[nid] = 0.3
    plan = planner.plan(p, batch=10, review={"m01": 1.0})
    scores = [it["score"] for it in plan["items"]]
    assert scores == sorted(scores, reverse=True)
    assert all("terms" in it for it in plan["items"])


# ---------- P0 跨会话派生回填 ----------
def test_hint_levels_derived_from_usage(mem):
    mem.log_hint(1, "s1", "b01", "q1", "L1")
    mem.log_hint(1, "s1", "b01", "q1", "L3")
    mem.log_hint(1, "s1", "s03", "q2", "L2")
    assert mem.hint_levels_by_node("s1") == {"b01": 3, "s03": 2}


def test_wrong_node_ids_only_wrong(mem):
    mem.log_interaction(1, "s1", "quiz", "b01", "✗", {"correct": False})
    mem.log_interaction(1, "s1", "quiz", "s02", "✓", {"correct": True})
    assert mem.wrong_node_ids("s1") == {"b01"}


def test_session_backfills_hint_and_review(env, kg):
    orch, mem, _ = env
    sid = "stu_backfill"
    mem.save_student(StudentProfile(student_id=sid, name="阿回"))
    mem.log_hint(1, sid, "b01", "q1", "L2")
    target = "s03"
    prereqs = kg.prereqs_of(target)
    assert prereqs, "测试前提：s03 有先修"
    mem.log_interaction(1, sid, "quiz", target, "✗", {"correct": False})
    state = AgentState(student_id=sid)
    orch.start_session(state)
    assert state.profile.hint_profile.get("b01") == 2
    assert set(prereqs) <= state.profile.needs_review


# ---------- P1 反思调整的先修门槛 ----------
def test_apply_adjust_gates_by_frontier(env, kg):
    orch, _, _ = env
    state = AgentState(student_id="t_adj")
    p = StudentProfile(student_id="t_adj")
    init_mastery(p, kg)
    for nid in p.mastery:
        p.mastery[nid] = 0.0
    state.profile = p
    state.plan = {"items": []}
    blocked = next(nid for nid in kg.nodes if kg.prereqs_of(nid))
    note = orch._apply_adjust(state, {"review_nodes": [blocked], "note": "先补薄弱点"})
    assert state.plan["items"] == []                 # 先修未达标 → 不入批次
    assert "前置还没打牢" in note
    for q in kg.prereqs_of(blocked):
        p.mastery[q] = 0.8                           # 先修达标 → 放行
    orch._apply_adjust(state, {"review_nodes": [blocked], "note": "x"})
    assert [i["node_id"] for i in state.plan["items"]] == [blocked]
    assert state.plan["items"][0]["tier"] == "复习"


# ---------- 图谱探索视图 ----------
def test_kg_figure_highlight_and_emphasis(kg, profile):
    fig = kg_figure(kg, mastery=profile.mastery, highlight={"b01", "m01"},
                    emphasis="b01")
    names = {t.name for t in fig.data}
    assert "关联节点（先修/后继）" in names and "定位知识点" in names
    assert "关联节点（先修/后继）" not in {
        t.name for t in kg_figure(kg, mastery=profile.mastery).data}


# ---------- 成长曲线 ----------
def _snap(mem, sid, nid, theta, ev, ts):
    mem.conn.execute(
        "INSERT INTO mastery_snapshots (student_id, node_id, theta, evidence_count, ts)"
        " VALUES (?,?,?,?,?)", (sid, nid, theta, ev, ts))
    mem.conn.commit()


def test_mastery_growth_buckets_by_day(mem):
    """按自然日重放快照：同一天取最新值，每天一点，均值/已掌握数口径正确"""
    now = time.time()
    _snap(mem, "s1", "b01", 0.30, 1, now - 2 * DAY)
    _snap(mem, "s1", "b01", 0.90, 3, now - 2 * DAY + 1)   # 同一天稍后，覆盖前值
    _snap(mem, "s1", "s02", 0.40, 1, now - DAY)
    _snap(mem, "s1", "b01", 0.95, 4, now)
    rows = mem.mastery_growth("s1")
    assert len(rows) == 3                                  # 三天各一点
    assert rows[0]["nodes"] == 1 and rows[0]["mastered"] == 1
    assert rows[1]["nodes"] == 2 and rows[1]["mastered"] == 1
    assert rows[2]["mean"] == pytest.approx(0.675, abs=1e-3)   # (0.95+0.40)/2
    assert rows[2]["mastered"] == 1 and rows[2]["evidence"] == 5  # 仅 b01≥0.75
    assert mem.mastery_growth("nobody") == []


def test_growth_figure_handles_empty_and_rows(mem):
    empty = growth_figure([])
    assert any("成长曲线" in (a.text or "") for a in empty.layout.annotations)
    _snap(mem, "s1", "b01", 0.9, 3, time.time())
    fig = growth_figure(mem.mastery_growth("s1"))
    assert len(fig.data) == 2                              # 折线 + 柱状


# ---------- 报告导出（自包含 HTML） ----------
def test_html_report_self_contained(tmp_path):
    env = build_env({"paths": {"db": str(tmp_path / "report.db")}})
    state = AgentState(student_id="stu_rep")
    env["orch"].start_session(state)
    for msg in ["小报", "计算机专业", "学过线性代数", "想学深度学习", "确认"]:
        env["orch"].handle(state, msg)
    for i in range(20):
        if state.phase != "quizzing":
            break
        env["orch"].handle(state, "A" if i % 2 == 0 else "B")
    doc = build_html_report(env, env["kg"], state.profile, state)
    env["mem"].close()
    assert doc.startswith("<!DOCTYPE html>") and doc.rstrip().endswith("</html>")
    assert "小报 的学习报告" in doc and "<table" in doc
    assert "plotly" in doc                                  # plotly.js 已内嵌，离线可看
    assert "成长曲线" in doc                                # 摸底答题已产生快照
    assert "打印 / 另存为 PDF" in doc


# ---------- 动态出题 ----------
def test_rule_question_grounded_and_deterministic(kg, profile):
    """规则题：正确项=该知识点概述，带满 L0~L3 提示，同 variant 必得同题"""
    q = rule_question(kg, "b01", profile, variant=0)
    assert q["node_id"] == "b01" and q["generated"] is True
    assert len(q["options"]) == 4 and q["answer"] in "ABCD"
    assert kg.nodes["b01"].summary[:20] in q["options"][ord(q["answer"]) - 65]
    assert all(q["hints"][f"L{i}"] for i in range(4))
    assert rule_question(kg, "b01", profile, variant=0) == q
    assert rule_question(kg, "b01", profile, variant=1)["answer"] != q["answer"]
    assert rule_question(kg, "no_such_node") is None


def test_gen_question_via_mock_llm(kg):
    q = gen_question(MockLLM(kg, _qbank()), kg, "b01")
    assert q["id"].startswith("gen_b01_") and q["options"]
    assert q["answer"] in "ABCD" and q["hints"]["L0"]


def test_orchestrator_generates_on_pool_exhaustion(env, kg):
    """题库耗尽 → 现场生成；同节点限额内逐题生成，超限返回 None"""
    orch, _, _ = env
    state = AgentState(student_id="t_gen", current_node="b01")
    state.profile = StudentProfile(student_id="t_gen")
    init_mastery(state.profile, kg)
    state.used_qids = ["q_b01_01"]            # 该节点唯一静态题已用掉
    for i in range(GEN_CAP_PER_NODE):
        q = orch._next_question_for(state)
        assert q and q["id"] == f"gen_b01_{i}" and q["node_id"] == "b01"
        state.used_qids.append(q["id"])           # 出过的题才计入限额
    assert orch._next_question_for(state) is None


# ---------- 摸底测验：回看改答 ----------
def test_quiz_edit_answer_recomputes_mastery(env, kg):
    """回看改答：重写记录，并以该节点作答前 θ/证据为基准重算画像"""
    orch, _, _ = env
    state = AgentState(student_id="t_edit")
    p = StudentProfile(student_id="t_edit")
    init_mastery(p, kg)
    state.profile = p
    state.phase = QUIZZING
    qs = orch.quiz.new_state(p)
    state.quiz_state = qs
    q = orch.q_by_id["q_b01_01"]
    p.mastery["b01"], p.evidence_count["b01"] = 0.30, 0
    theta_wrong = mastery_update(p, kg, "b01", False, kind="quiz")
    orch.quiz.record(qs, q, False, "B", 0.30, 0)
    orch.quiz_edit_answer(state, 0, "A. 一")          # 错 → 对
    assert qs.answers[0][2] is True and qs.answers[0][3] == "A"
    assert p.mastery["b01"] > theta_wrong and p.evidence_count["b01"] == 1
    orch.quiz_edit_answer(state, 0, "B. 二")          # 对 → 错（回到原值）
    assert qs.answers[0][2] is False and qs.answers[0][3] == "B"
    assert p.mastery["b01"] == pytest.approx(theta_wrong, abs=1e-6)


def test_quiz_edit_answer_ignores_same_choice(env, kg):
    """选回同一选项不改动，也不越界报错"""
    orch, _, _ = env
    state = AgentState(student_id="t_edit2")
    p = StudentProfile(student_id="t_edit2")
    init_mastery(p, kg)
    state.profile = p
    state.phase = QUIZZING
    state.quiz_state = orch.quiz.new_state(p)
    orch.quiz_edit_answer(state, 9, "A. 一")           # 无此作答 → 直接返回
    assert state.quiz_state.answers == []


def test_mem_revise_attempt_flips_wrongbook(mem):
    """改答后同步错题本口径：错误记录被改写为正确，不再出现在错题本"""
    mem.log_interaction(1, "s1", "quiz", "b01", "✗ 题干", {"correct": False, "qid": "q1"})
    assert mem.wrong_node_ids("s1") == {"b01"}
    mem.revise_attempt("s1", "q1", True, 0.8)
    assert mem.wrong_node_ids("s1") == set()
    assert mem.wrong_attempts("s1") == []


