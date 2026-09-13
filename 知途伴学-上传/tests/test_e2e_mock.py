"""P4 验证：Mock 离线模式下 8 幕剧本端到端

剧本：注册开场 → 4 问对话诊断 → 自适应测验 → 教学对话（[ASK:] 推进）→
答错进 L0 脚手架 → 连错升级 L1→L2→L3 → 变式检验 → 答对退出 → 结束会话反思 →
说「继续」开新会话验证记忆开场白。题库用合成数据（每节点 3 题，answer=A、
变式 answer=B），不依赖数据生成任务。
"""
from pathlib import Path

import pytest

from src.agent.orchestrator import Orchestrator
from src.agent.state import (AgentState, DIAGNOSING, INTERVENING,
                             PRACTICING, QUIZZING, REFLECTING, TEACHING)
from src.kg.loader import KnowledgeGraph
from src.llm.mock import MockLLM
from src.memory.db import MemoryStore
from src.path.planner import PathPlanner

KG_PATH = Path(__file__).resolve().parent.parent / "data" / "kg" / "ml_kg.json"

# 两段式讲义：第二段以 [ASK:] 结尾，测试讲义进度推进
LECTURE = ("第一段：损失函数衡量模型预测与真实标签之间的差异，是优化的目标。\n\n"
           "[ASK:] 为什么线性回归常用平方损失？\n\n"
           "第二段：因为平方损失可导且是凸函数，便于用梯度下降优化。")


def full_qbank(kg):
    """合成题库：50 节点 × 3 题（测试不依赖数据生成任务）"""
    qs = []
    for nid in sorted(kg.nodes):
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


@pytest.fixture()
def env(tmp_path, kg):
    mem = MemoryStore(str(tmp_path / "e2e.db"))
    qbank = full_qbank(kg)
    orch = Orchestrator(kg, MockLLM(kg, qbank), mem, PathPlanner(kg), qbank)
    yield orch, mem, kg
    mem.close()


def _run_diagnosis(orch, state):
    orch.start_session(state)
    orch.handle(state, "小明")
    orch.handle(state, "广东理工学院 计算机专业")
    orch.handle(state, "学过线性代数和概率统计")
    orch.handle(state, "想重点学深度学习方向")


def _run_quiz_until_plan(orch, state, max_turns=20):
    i = 0
    while state.phase == QUIZZING and i < max_turns:
        orch.handle(state, "A" if i % 2 == 0 else "B")
        i += 1
    assert state.phase == TEACHING, f"测验未在 {max_turns} 轮内收敛：{state.quiz_state}"
    assert state.plan.get("items") and state.current_node


# ---------- 8 幕剧本 ----------
def test_full_script_8_scenes(env):
    orch, mem, kg = env
    state = AgentState(student_id="xiaoming")

    # 幕1 注册开场（开场白直接带第一问，进入诊断）
    reply, _ = orch.start_session(state)
    assert "知途" in reply and "怎么称呼" in reply
    assert state.phase == DIAGNOSING

    # 幕2 4 问对话诊断
    reply, _ = orch.handle(state, "小明")
    assert "小明" in reply and state.phase == DIAGNOSING
    orch.handle(state, "广东理工学院 计算机专业")
    assert state.profile.major == "广东理工学院 计算机专业"
    orch.handle(state, "学过线性代数和概率统计")
    assert state.profile.prior.get("m01") == 1.0
    assert state.profile.prior.get("m04") == 1.0
    orch.handle(state, "想重点学深度学习方向")
    assert state.phase == QUIZZING and state.current_question
    assert "深度学习" in state.profile.goals[0]
    assert state.session_id > 0

    # 幕3 自适应测验（对错交替，自动收敛）
    _run_quiz_until_plan(orch, state)
    assert state.report.get("total_questions", 0) > 0

    # 幕4 教学对话：注入讲义 → 回应 [ASK:] 推进分段 → 出巩固题
    cur = state.current_node
    kg.nodes[cur].lecture = LECTURE
    reply, _ = orch.handle(state, "我觉得平方损失可导所以好优化")
    assert "第二段" in reply and state.lecture_para == 1
    state.used_qids = []  # 测试隔离：确保巩固题有可用题目
    reply, _ = orch.handle(state, "明白了，凸函数局部最优就是全局最优")
    assert state.current_question is not None
    assert state.current_question["node_id"] == cur

    # 幕5 巩固题答错 → 进入 L0 脚手架
    reply, payload = orch.handle(state, "B")
    assert state.phase == INTERVENING
    assert payload["scaffold"]["level"] == "L0"
    assert "h0" in reply

    # 幕6 连错升级 L1→L2→L3
    reply, _ = orch.handle(state, "B")
    assert "h1" in reply and state.scaffold.level == 1
    reply, _ = orch.handle(state, "B")
    assert "h2" in reply and state.scaffold.level == 2
    reply, _ = orch.handle(state, "B")
    assert "h3" in reply and state.scaffold.level == 3

    # L3 仍错 → 变式题检验
    reply, _ = orch.handle(state, "B")
    assert "换个形式" in reply and state.scaffold.variant_tried
    assert state.current_question.get("stem") == "变式"

    # 幕7 变式答对 → 退出脚手架，节点完成
    reply, payload = orch.handle(state, "B")   # 变式 answer=B
    assert payload["scaffold"]["active"] is False
    assert cur in state.done_nodes
    assert state.phase == TEACHING

    # 幕8 结束会话 → 反思落库；「继续」→ 记忆开场白 + 新会话
    sid_old = state.session_id
    reply, payload = orch.handle(state, "结束")
    assert state.phase == REFLECTING
    assert mem.last_reflection("xiaoming") is not None
    reply, payload = orch.handle(state, "继续")
    assert state.phase == TEACHING
    assert "欢迎回来" in reply
    assert state.session_id != sid_old


# ---------- 变式仍错 → 重规划 ----------
def test_variant_wrong_triggers_replan(env):
    orch, mem, kg = env
    state = AgentState(student_id="student2")
    _run_diagnosis(orch, state)
    _run_quiz_until_plan(orch, state)
    cur = state.current_node
    kg.nodes[cur].lecture = LECTURE
    orch.handle(state, "嗯嗯")
    state.used_qids = []
    orch.handle(state, "好的")
    assert state.current_question is not None
    # 连错 4 次：进 L0 → L1 → L2 → L3
    for _ in range(4):
        orch.handle(state, "B")
    assert state.scaffold.level == 3
    reply, _ = orch.handle(state, "B")   # L3 错 → 出变式题
    assert state.scaffold.variant_tried
    reply, payload = orch.handle(state, "A")   # 变式也错（变式 answer=B）→ 重规划
    assert state.phase == TEACHING
    assert payload["scaffold"]["active"] is False
    # 当前节点回退到原节点的先修（无先修时保持原节点）
    assert state.current_node == cur or state.current_node in kg.prereqs_of(cur)
    # 重规划反思已落库
    row = mem.conn.execute(
        "SELECT COUNT(*) AS n FROM reflections WHERE trigger='stuck_l3'").fetchone()
    assert row["n"] >= 1


# ---------- 状态序列化往返（持久化探针核心断言） ----------
def test_state_serialization_roundtrip(env):
    orch, mem, kg = env
    state = AgentState(student_id="s3")
    _run_diagnosis(orch, state)
    orch.handle(state, "A")
    d = state.to_dict()
    state2 = AgentState.from_dict(d)
    assert state2.profile.name == state.profile.name
    assert state2.profile.mastery == state.profile.mastery
    assert state2.profile.needs_review == state.profile.needs_review
    assert state2.quiz_state.current_node == state.quiz_state.current_node
    assert state2.quiz_state.covered == state.quiz_state.covered
    assert state2.used_qids == state.used_qids
    assert state2.history == state.history
    # 序列化恢复后继续驱动：答一题不崩，状态一致
    reply, payload = orch.handle(state2, "B")
    assert reply and payload["phase"] == state2.phase


# ---------- 工具函数 ----------
def test_choice_extraction():
    assert Orchestrator._choice("B", {}) == "B"
    assert Orchestrator._choice("我想选 C", {}) == "C"
    assert Orchestrator._choice("没有想法", {"intent": "confusion"}) is None
    assert Orchestrator._choice("嗯", {"intent": "answer", "choice": "D"}) == "D"


def test_parse_name():
    assert Orchestrator._parse_name("小明") == "小明"
    assert Orchestrator._parse_name("我是小明") == "小明"
    assert Orchestrator._parse_name("我叫张三，你好") == "张三"
    assert Orchestrator._parse_name("我的名字是李四") == "李四"
    assert Orchestrator._parse_name("  叫我小王  ") == "小王"
    assert Orchestrator._parse_name("") == "同学"


def test_parse_prior():
    assert Orchestrator._parse_prior("学过线性代数和概率统计") == {
        "m01": 1.0, "m02": 1.0, "m04": 1.0, "m05": 1.0}
    assert Orchestrator._parse_prior("没学过，零基础") == {}
    assert Orchestrator._parse_prior("高等数学学过一点") == {"m03": 0.5}


# ---------- 清空会话重新诊断（回归：曾因 profile=None 崩溃） ----------
def test_restart_diagnosis_resets_to_fresh(env):
    orch, mem, kg = env
    state = AgentState(student_id="redo")
    _run_diagnosis(orch, state)
    assert state.profile is not None and state.session_id > 0

    # 重新诊断：不恢复旧画像，直接进入诊断并给出开场白
    fresh = AgentState(student_id="redo")
    reply = orch.restart_diagnosis(fresh)
    assert fresh.phase == DIAGNOSING
    assert fresh.profile is not None
    assert fresh.diagnosis_step == 0
    assert "怎么称呼" in reply

    # 输入名字不再报错，正确记录
    orch.handle(fresh, "小明")
    assert fresh.profile.name == "小明"


def test_bare_idle_name_input_does_not_crash(env):
    orch, mem, kg = env
    state = AgentState(student_id="bare")   # profile=None、phase=IDLE（历史“清空”产生）
    orch.handle(state, "小明")               # 触发 _idle_turn：初始化画像进入诊断
    assert state.phase == DIAGNOSING
    assert state.profile is not None
    orch.handle(state, "小明")               # 第二次输入记名字
    assert state.profile.name == "小明"


# ---------- 记忆开场白：初次使用不显示「欢迎回来」，不引用未学知识点 ----------
def test_first_time_no_welcome_back(env):
    orch, mem, kg = env
    state = AgentState(student_id="first_timer")
    _run_diagnosis(orch, state)          # 完成 4 问诊断，尚未进入教学（无 teach 交互）
    orch.handle(state, "结束")           # 结束会话，产生 session_end 反思
    state2 = AgentState(student_id="first_timer")
    reply, _ = orch.start_session(state2)
    assert "欢迎回来" not in reply
    assert "欢迎使用知途伴学" in reply


def test_has_study_history_gate(env):
    orch, mem, kg = env
    sid = mem.start_session("ghost")
    assert not mem.has_study_history("ghost")
    mem.log_interaction(sid, "ghost", "message", "", "对话诊断")
    mem.log_interaction(sid, "ghost", "quiz", "b01", "测验")
    assert not mem.has_study_history("ghost")   # 诊断/测验不算真正学习
    mem.log_interaction(sid, "ghost", "teach", "b01", "开始学习")
    assert mem.has_study_history("ghost")


def test_returning_student_preview_grounded(env):
    orch, mem, kg = env
    state = AgentState(student_id="veteran")
    _run_diagnosis(orch, state)
    _run_quiz_until_plan(orch, state)
    cur = state.current_node
    kg.nodes[cur].lecture = LECTURE
    orch.handle(state, "嗯嗯")
    state.used_qids = []
    orch.handle(state, "好的")
    assert state.current_question is not None
    orch.handle(state, "A")             # 答对 → 完成当前节点
    assert state.done_nodes
    last_done = kg.nodes[state.done_nodes[-1]].name
    orch.handle(state, "结束")
    state2 = AgentState(student_id="veteran")
    reply, _ = orch.start_session(state2)
    assert "欢迎回来" in reply
    assert last_done in reply           # 回顾的是真正学过的知识点，而非任意薄弱点


# ---------- 诊断测验：答题后给答案+解析 ----------
def test_quiz_answer_shows_explanation(env):
    orch, mem, kg = env
    state = AgentState(student_id="quizexpl")
    _run_diagnosis(orch, state)
    assert state.phase == QUIZZING
    q = state.current_question
    reply, _ = orch.handle(state, q["answer"])     # 答对
    assert "正确答案" in reply and "解析" in reply
    # 答错同样给解析（下一题）
    q2 = state.current_question
    reply, _ = orch.handle(state, "D" if q2["answer"] != "D" else "C")
    assert "正确答案" in reply and "解析" in reply


# ---------- 主动选题练习 ----------
def test_practice_flow(env):
    orch, mem, kg = env
    state = AgentState(student_id="practice1")
    _run_diagnosis(orch, state)
    _run_quiz_until_plan(orch, state)
    assert state.phase == TEACHING
    state.used_qids = []                 # 隔离：确保练习节点有可用题
    reply, _ = orch.handle(state, "练习 线性回归")
    assert state.phase == PRACTICING
    assert state.practice_node and state.resume_phase == TEACHING
    assert state.current_question is not None and "来练" in reply
    q = state.current_question
    reply, _ = orch.handle(state, q["answer"])
    assert "正确答案" in reply and "解析" in reply
    guard = 0
    while state.phase == PRACTICING and guard < 10:
        q = state.current_question
        reply, _ = orch.handle(state, q["answer"])
        guard += 1
    assert state.phase == TEACHING       # 题做完自动恢复
    assert state.practice_node == ""


def test_practice_blocked_during_quiz(env):
    orch, mem, kg = env
    state = AgentState(student_id="practice2")
    _run_diagnosis(orch, state)
    assert state.phase == QUIZZING
    reply, _ = orch.handle(state, "练习 线性回归")
    assert state.phase == QUIZZING       # 诊断/测验中拒绝切练习
    assert "完成后再来" in reply


def test_practice_unknown_topic(env):
    orch, mem, kg = env
    state = AgentState(student_id="practice3")
    _run_diagnosis(orch, state)
    _run_quiz_until_plan(orch, state)
    reply, _ = orch.handle(state, "练习 火箭发动机")
    assert state.phase == TEACHING       # 未命中知识点，不进入练习
    assert "没找到" in reply
