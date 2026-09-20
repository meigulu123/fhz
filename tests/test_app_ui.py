"""P4 验证：Streamlit UI 冒烟（AppTest 无头运行）

覆盖：应用加载 → 登录 → 4 问对话诊断 → 自适应测验 → 生成路径 →
探针页状态存活/序列化往返 → 三个业务页面渲染无异常。
GUOCHUANG_DB 环境变量将测试数据库隔离到临时目录。
"""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")


def _ss_get(at, key, default=None):
    """AppTest 的 SafeSessionState 不支持 .get()，只能索引访问"""
    try:
        return at.session_state[key]
    except KeyError:
        return default


def _has(at, text):
    """header/subheader/title/caption 与 markdown 是 AppTest 的不同元素树"""
    for group in (at.markdown, at.header, at.subheader, at.title, at.caption):
        if any(text in (m.value or "") for m in group):
            return True
    return False


# ---------- 主应用（from_file） ----------
@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("ui") / "ui_test.db"
    os.environ["GUOCHUANG_DB"] = str(db)
    yield str(db)
    os.environ.pop("GUOCHUANG_DB", None)


@pytest.fixture(scope="module")
def st_app(tmp_db):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    return at


def test_login_lands_on_home(st_app, tmp_db):
    """登录门禁 → 登录成功落在首页（含开场白已写入会话状态）"""
    at = st_app
    from src.memory.db import MemoryStore
    mem = MemoryStore(tmp_db)
    mem.create_account("xiaoming", "pass123")
    mem.close()
    # 登录页：左栏品牌（定位语 + 四大能力卡）+ 登录/演示账号/注册
    assert _has(at, "会诊断、懂规划、善引导的 AI 学习导师")
    assert _has(at, "核心能力")
    assert any("演示账号" in (b.label or "") for b in at.button)
    at.text_input[0].set_value("xiaoming")
    at.text_input[1].set_value("pass123")
    at.button[0].click()
    at.run()
    assert not at.exception
    # 落在首页：主视觉 + 核心能力卡片 + 开始学习入口
    assert _has(at, "知途伴学")
    assert _has(at, "核心能力")
    assert any("开始学习" in (b.label or "") for b in at.button)
    state = at.session_state["agent_state"]
    assert state is not None and state.phase == "diagnosing"
    assert "怎么称呼" in state.history[-1]["content"]


# ---------- 各页面（from_function + 预置 session_state） ----------
@pytest.fixture(scope="module")
def page_env(tmp_path_factory):
    """独立环境 + 一个完成诊断/测验的会话状态（页面渲染种子）"""
    from src.agent.state import AgentState
    from src.ui.env import build_env
    db = tmp_path_factory.mktemp("ui2") / "pages.db"
    env = build_env({"paths": {"db": str(db)}})
    state = AgentState(student_id="uipage")
    orch = env["orch"]
    orch.start_session(state)
    for msg in ["小明", "计算机专业", "学过线性代数", "想学深度学习", "确认"]:
        orch.handle(state, msg)
    for i in range(20):
        if state.phase != "quizzing":
            break
        orch.handle(state, "A" if i % 2 == 0 else "B")
    assert state.phase == "teaching"
    return env, state


def _page_app(page_fn, env, state, tmp_path):
    """from_function 不携带模块级 import，改为临时 runner 脚本 + from_file"""
    from streamlit.testing.v1 import AppTest
    runner = tmp_path / "page_runner.py"
    runner.write_text(
        "import sys\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        "import streamlit as st\n"
        f"from {page_fn.__module__} import {page_fn.__name__}\n"
        f"{page_fn.__name__}()\n",
        encoding="utf-8")
    at = AppTest.from_file(str(runner), default_timeout=120)
    at.session_state["env"] = env
    at.session_state["agent_state"] = state
    at.run()
    return at


def test_probe_page_buttons(page_env, tmp_path):
    env, state = page_env
    from src.ui.probe_page import probe_page
    at = _page_app(probe_page, env, state, tmp_path)
    assert not at.exception
    assert _has(at, "状态持久化探针")

    # ① 修改状态 → rerun 存活
    at.button[0].click()
    at.run()
    assert not at.exception
    assert _ss_get(at, "probe_marker", 0) > 0
    assert any("rerun 后修改存活" in (s.value or "") for s in at.success)

    # ② 序列化往返断言
    buttons = [b for b in at.button if "一致性检查" in (b.label or "")]
    assert buttons, "找不到序列化检查按钮"
    buttons[0].click()
    at.run()
    assert not at.exception
    assert _ss_get(at, "probe_roundtrip") is True
    assert any("序列化往返一致" in (s.value or "") for s in at.success)


def test_business_pages_render(page_env, tmp_path):
    env, state = page_env
    from src.ui.pages.account_page import account_page
    from src.ui.pages.chat_page import chat_page
    from src.ui.pages.history_page import history_page
    from src.ui.pages.kg_page import kg_page
    from src.ui.pages.path_page import path_page
    from src.ui.pages.profile_page import profile_page
    from src.ui.pages.wrongbook_page import wrongbook_page
    for page, keyword in [(profile_page, "学生画像"), (path_page, "学习路径"),
                          (kg_page, "知识图谱"), (chat_page, "对话学习"),
                          (account_page, "账户管理"), (history_page, "历史对话"),
                          (wrongbook_page, "错题本")]:
        at = _page_app(page, env, state, tmp_path)
        assert not at.exception, f"{page.__name__} 渲染异常: {at.exception}"
        assert _has(at, keyword), f"{page.__name__} 标题缺失"


def test_chat_page_full_flow(tmp_db, tmp_path):
    """对话页完整流程：4 问诊断 → 自适应测验 → 生成路径（chat_page 直渲）"""
    from src.agent.state import AgentState
    from src.ui.env import build_env
    from src.ui.pages.chat_page import chat_page
    env = build_env({"paths": {"db": tmp_db}})
    state = AgentState(student_id="flow_user")
    reply, _ = env["orch"].start_session(state)
    state.history.append({"role": "assistant", "content": reply})
    at = _page_app(chat_page, env, state, tmp_path)
    assert not at.exception
    assert _has(at, "怎么称呼")

    # 4 问对话诊断
    at.chat_input[0].set_value("小明").run()
    assert not at.exception and _has(at, "专业")
    at.chat_input[0].set_value("广东理工学院 计算机专业").run()
    assert not at.exception
    at.chat_input[0].set_value("学过线性代数和概率统计").run()
    assert not at.exception
    at.chat_input[0].set_value("想重点学深度学习").run()
    assert not at.exception
    # 诊断确认环节
    at.chat_input[0].set_value("确认").run()
    assert not at.exception
    assert state.phase == "quizzing"
    assert _has(at, "题目")

    # 自适应测验（对错交替直到收敛出路径）
    for i in range(20):
        if state.phase != "quizzing":
            break
        at.chat_input[0].set_value("A" if i % 2 == 0 else "B").run()
        assert not at.exception
    assert state.phase == "teaching"
    assert state.plan.get("items") and state.current_node
    assert state.report.get("total_questions", 0) > 0


# ---------- 画像页 AI 学情诊断 ----------
def test_profile_report_generation(page_env):
    """Mock 模式：诊断报告三段结构齐全，指标变化后内容随动"""
    env, state = page_env
    from src.student.diagnosis import gen_profile_report
    band = env["planner"].zpd_band(state.profile)
    text = gen_profile_report(env["llm"], state.profile, env["kg"],
                              env["mem"], band)
    for kw in ("学习优势", "薄弱环节", "学习建议"):
        assert kw in text, f"诊断报告缺少「{kw}」"
    assert len(text) >= 100
    # 画像指标汇总：六维能力与行为数据口径正确
    from src.student.diagnosis import profile_metrics
    m = profile_metrics(state.profile, env["kg"], env["mem"])
    assert set(m["abilities"]) == {"学习进度", "知识掌握", "逻辑理解",
                                   "答题正确率", "记忆巩固", "学习投入"}
    assert all(0 <= v <= 100 for v in m["abilities"].values())


def test_list_students_with_data(tmp_db):
    """学生切换器数据源：有画像的学生（students 表）按注册顺序列出"""
    import time as _t
    from src.memory.db import MemoryStore
    mem = MemoryStore(tmp_db)
    mem.create_account("stu_a", "pass123")  # 只有账户、无画像，不应列出
    for sid in ("stu_b", "stu_c"):
        mem.save_student({"student_id": sid, "name": sid, "major": "",
                          "goals": [], "goal_keywords": [], "style_tags": [],
                          "prior": {}, "created_at": _t.time()})
    students = mem.list_students_with_data()
    assert "stu_a" not in students, "无画像的账户不应出现在学生切换器"
    assert "stu_b" in students and "stu_c" in students
    assert students.index("stu_b") < students.index("stu_c")
    mem.close()


# ---------- 大模型驱动的路径定序 ----------
class _StubOrderLLM:
    """固定输出的 LLM 替身（测 _llm_order 的 LLM 通道，不碰真实模型）"""

    def __init__(self, payload=None):
        self.payload = payload

    def chat_json(self, messages):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_llm_plan_ordering(page_env):
    """LLM 通道：候选内重排生效、公式字段保留、理由与 notes 采纳、非法 id 丢弃"""
    env, state = page_env
    orch = env["orch"]
    base = env["planner"].plan(state.profile, batch=5)
    assert base["items"], "测试画像应有候选知识点"
    want = [it["node_id"] for it in reversed(base["items"])]
    payload = {
        "items": [{"node_id": nid, "reason": f"AI 理由 {nid}"} for nid in want]
        + [{"node_id": "不存在的节点", "reason": "应被丢弃"}],
        "notes": "先回补薄弱先修，再按学习目标推进。",
    }
    plan = orch._llm_order(state, base, llm=_StubOrderLLM(payload))
    assert plan["engine"] == "llm"
    assert plan["notes"] == "先回补薄弱先修，再按学习目标推进。"
    got = [it["node_id"] for it in plan["items"]]
    assert got[:len(want)] == want, "LLM 给出的顺序应被采纳"
    assert "不存在的节点" not in got
    for it in plan["items"]:
        assert it["reason"].startswith("AI 理由 ")
        for key in ("difficulty", "score", "tier", "mastery"):
            assert key in it, f"公式字段 {key} 应保留"


def test_llm_plan_ordering_fallback(page_env):
    """LLM 故障/输出非法 → 整体回退公式结果（engine 不标 llm）"""
    env, state = page_env
    orch = env["orch"]
    base = env["planner"].plan(state.profile, batch=5)
    for bad in (RuntimeError("boom"), {}, {"items": [{"node_id": "瞎编的"}]},
                {"items": [{"reason": "缺 node_id"}]}):
        plan = orch._llm_order(state, base, llm=_StubOrderLLM(bad))
        assert plan["items"] == base["items"], f"非法输出 {bad!r} 应回退公式"
        assert plan.get("engine") != "llm"


def test_llm_plan_ordering_mock_offline(page_env):
    """离线 Mock 模式：LLM 通道静默回退公式，路径与现状完全一致"""
    env, state = page_env
    orch = env["orch"]
    base = env["planner"].plan(state.profile, batch=5)
    plan = orch._llm_order(state, base)  # env 的 llm 是 MockLLM，无 plan_initial 路由
    assert plan["items"] == base["items"]
    assert "engine" not in plan


# ---------- 大模型驱动的画像生成与持续更新 ----------
class _StubObserveLLM:
    """固定输出的 LLM 替身（测诊断提取与画像观察，不碰真实模型）"""

    def __init__(self, payload=None, exc=False):
        self.payload = payload
        self.exc = exc

    def chat_json(self, messages):
        if self.exc:
            raise RuntimeError("boom")
        return self.payload


def test_diag_extract_llm(page_env):
    """诊断提取走大模型：合法节点采纳、非法丢弃；Mock 模式回退规则"""
    env, state = page_env
    orch = env["orch"]
    stub = _StubObserveLLM({"prior": {"m01": 1.0, "m02": 0.5, "不存在": 0.9},
                            "style_tags": ["有竞赛经历", ""]})
    p = orch._extract_prior_llm("学过线性代数", llm=stub)
    assert p["prior"] == {"m01": 1.0, "m02": 0.5}
    assert p["tags"] == ["有竞赛经历"]
    # Mock 模式（JSON 解析失败）→ None → 调用方走规则兜底
    assert orch._extract_prior_llm("学过线性代数") is None
    assert orch._extract_goals_llm("想学深度学习") is None
    assert orch._parse_prior("学过线性代数和概率统计")  # 规则兜底仍可用


def test_profile_observe_llm(page_env):
    """画像观察：LLM 增量合并进画像并落库；无效输出不落库"""
    env, state = page_env
    orch = env["orch"]
    mem = env["mem"]
    stub = _StubObserveLLM({"style_tags_add": ["喜欢追问原理", "重复的"],
                            "goals_update": "想深入学大模型方向",
                            "observation": "对原理类问题追问积极，适合加深度。"})
    ok = orch._update_profile_from_conversation(state, "idle", llm=stub)
    assert ok is True
    assert "喜欢追问原理" in state.profile.style_tags
    assert state.profile.goals == ["想深入学大模型方向"]
    rows = mem.list_observations(state.student_id)
    assert rows and rows[0]["content"]["observation"] == \
        "对原理类问题追问积极，适合加深度。"
    # 全部无效/空输出 → 不落库
    before = len(mem.list_observations(state.student_id))
    ok2 = orch._update_profile_from_conversation(
        state, "idle",
        llm=_StubObserveLLM({"style_tags_add": [""], "goals_update": None,
                             "observation": ""}))
    assert ok2 is False
    assert len(mem.list_observations(state.student_id)) == before


def test_profile_observe_mock_rules(page_env):
    """离线 Mock：观察走规则兜底，确定性落库"""
    env, state = page_env
    orch = env["orch"]
    state.report["accuracy"] = 0.8
    ok = orch._update_profile_from_conversation(state, "session_end")
    assert ok is True
    rows = env["mem"].list_observations(state.student_id)
    assert any("答题节奏稳定" in r["content"].get("style_tags_add", [])
               for r in rows)
    assert any("近期答题正确率" in r["content"].get("observation", "")
               for r in rows)


def test_idle_update_due(page_env):
    """空闲跟进判定：刚交互/观察刚更新不触发；空闲超 5 分钟触发"""
    import time as _t
    env, state = page_env
    orch = env["orch"]
    mem = env["mem"]
    sid = state.student_id
    # 清掉前面用例留下的观察记录，保证本用例从干净状态判定
    mem.conn.execute("DELETE FROM profile_observations WHERE student_id=?",
                     (sid,))
    mem.conn.commit()
    assert orch._idle_update_due(state) is False  # 近期有交互且观察新鲜
    mem.conn.execute(
        "INSERT INTO interactions (session_id, student_id, ts, kind, node_id,"
        " content, mastery_delta_json) VALUES (?,?,?,?,?,?,'{}')",
        (state.session_id, sid, _t.time(), "message", "", "x"))
    mem.conn.commit()
    assert orch._idle_update_due(state) is False  # 刚交互不触发
    mem.conn.execute("UPDATE interactions SET ts=? WHERE student_id=?",
                     (_t.time() - 400, sid))
    mem.conn.commit()
    assert orch._idle_update_due(state) is True   # 空闲 >5min 触发
    mem.save_profile_observation(sid, "idle", {"observation": "x"})
    assert orch._idle_update_due(state) is False  # 观察刚更新，不重复触发


def test_fast_call_timeout(page_env):
    """进场快通道：超过时限返回 None、不阻塞调用方（进场兜底的前提）"""
    import time as _t
    env, state = page_env
    orch = env["orch"]
    t0 = _t.time()
    r = orch._fast_call(lambda: _t.sleep(1), timeout=0.2)
    assert r is None                       # 超时统一返回 None
    assert _t.time() - t0 < 0.8            # 限时等待，不干等慢调用
    assert orch._fast_call(lambda: "ok") == "ok"  # 快调用正常返回


# ---------- 登录页账户体系 ----------
def test_account_page_features(page_env, tmp_path):
    """账户管理页：账户信息 / 学习数据 / 修改密码 / 清空数据四块齐全"""
    env, state = page_env
    from src.ui.pages.account_page import account_page
    at = _page_app(account_page, env, state, tmp_path)
    assert not at.exception
    for keyword in ("账户信息", "学习数据", "修改密码", "清空学习数据"):
        assert _has(at, keyword), f"账户管理页缺少「{keyword}」区块"
    assert any("确认修改" in (b.label or "") for b in at.button)
    # 清空数据按钮默认禁用，需勾选确认框
    wipe = [b for b in at.button if "清空学习数据" in (b.label or "")]
    assert wipe and wipe[0].disabled is True
    at.checkbox[0].set_value(True).run()
    wipe = [b for b in at.button if "清空学习数据" in (b.label or "")]
    assert wipe and wipe[0].disabled is False


def test_demo_button_enters_core_ui(tmp_db):
    """演示账号按钮：无需注册，一键进入核心界面（落在首页）"""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    demo = [b for b in at.button if "演示账号" in (b.label or "")]
    assert demo, "找不到演示账号按钮"
    demo[0].click()
    at.run()
    assert not at.exception
    state = at.session_state["agent_state"]
    assert state is not None and state.phase == "diagnosing"
    assert state.student_id == "demo"
    assert _has(at, "核心能力")


def test_register_flow(tmp_db):
    """注册视图：账号密码完成注册 → 自动返回登录页预填账户 → 登录成功"""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    # 进入注册视图
    link = [b for b in at.button if "注册新账号" in (b.label or "")]
    assert link, "找不到注册入口"
    link[0].click()
    at.run()
    assert not at.exception
    # 注册视图：账户/密码/确认密码 + 注册按钮
    assert len(at.text_input) == 3
    at.text_input[0].set_value("newuser")
    at.text_input[1].set_value("pass123")
    at.text_input[2].set_value("pass123")
    submit = [b for b in at.button if "注 册" in (b.label or "")]
    assert submit, "找不到注册按钮"
    submit[0].click()
    at.run()
    assert not at.exception
    # 自动返回登录页且账户已预填
    assert at.session_state["login_acc"] == "newuser"
    assert any("注册成功" in (s.value or "") for s in at.success)
    at.text_input[1].set_value("pass123")  # 密码框
    login = [b for b in at.button if "登 录" in (b.label or "")]
    assert login, "找不到登录按钮"
    login[0].click()
    at.run()
    assert not at.exception
    state = at.session_state["agent_state"]
    assert state is not None and state.student_id == "newuser"
