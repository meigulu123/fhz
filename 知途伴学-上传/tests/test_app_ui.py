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
    # 登录页：品牌标识 + 账户密码 + 登录/演示账号/注册
    assert _has(at, "大模型驱动的自适应学习路径决策与伴学智能体")
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
    for msg in ["小明", "计算机专业", "学过线性代数", "想学深度学习"]:
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
    from src.ui.pages.kg_page import kg_page
    from src.ui.pages.path_page import path_page
    from src.ui.pages.profile_page import profile_page
    for page, keyword in [(profile_page, "学生画像"), (path_page, "学习路径"),
                          (kg_page, "知识图谱"), (chat_page, "对话学习"),
                          (account_page, "账户管理")]:
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
