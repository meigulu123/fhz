"""知途伴学 · Streamlit 入口（登录页 → 核心界面九页导航）

未登录只渲染登录页；登录后进入核心界面。左侧边栏：logo + 项目名 → 用户信息卡
（点击进账户管理）→ 核心功能框 → 系统框 → 结束/退出。无任何 API Key 时
MockLLM 离线兜底，配置真实 Key 后自动切换真实大模型。
"""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 初始化日志系统
from src.utils.logger import setup_logging  # noqa: E402
setup_logging(level=20)  # INFO 级别

from src.agent.state import AgentState  # noqa: E402
from src.ui.env import build_env  # noqa: E402
from src.ui.pages.account_page import account_page  # noqa: E402
from src.ui.pages.chat_page import chat_page  # noqa: E402
from src.ui.pages.history_page import history_page  # noqa: E402
from src.ui.pages.home_page import home_page  # noqa: E402
from src.ui.pages.kg_page import kg_page  # noqa: E402
from src.ui.pages.login_page import login_page  # noqa: E402
from src.ui.pages.path_page import path_page  # noqa: E402
from src.ui.pages.profile_page import profile_page  # noqa: E402
from src.ui.pages.wrongbook_page import wrongbook_page  # noqa: E402
from src.ui.probe_page import probe_page  # noqa: E402

st.set_page_config(page_title="知途伴学",
                   page_icon=str(ROOT / "assets" / "logo.png"), layout="wide",
                   initial_sidebar_state="expanded")

from src.ui.theme import avatar_html, inject_theme, logo_html  # noqa: E402

inject_theme()


@st.cache_resource
def get_env():
    return build_env()


env = get_env()
st.session_state["env"] = env
if "agent_state" not in st.session_state:
    st.session_state["agent_state"] = None

# ---------- 登录门禁：未登录只显示登录页 ----------
if st.session_state["agent_state"] is None:
    login_page(env)
    st.stop()

state = st.session_state["agent_state"]

# ---------- 页面注册（原生导航隐藏，侧边栏用自绘按钮） ----------
NAV = [
    ("首页", "home", home_page),
    ("新对话", "chat_bubble", chat_page),
    ("历史对话", "history", history_page),
    ("学习路径", "route", path_page),
    ("知识图谱", "hub", kg_page),
    ("个人画像", "person_search", profile_page),
    ("错题本", "edit_note", wrongbook_page),
]
SYS = [
    ("账户管理", "manage_accounts", account_page),
    ("状态探针", "monitor_heart", probe_page),
]
pages = [st.Page(home_page, title="首页", default=True)] + [
    st.Page(fn, title=title) for title, _, fn in NAV[1:] + SYS
]
current = st.navigation(pages, position="hidden")


def _nav_button(title, icon, fn, active, key):
    """侧边栏导航按钮：当前页主色高亮，点击跳转"""
    if st.button(f":material/{icon}: {title}", key=key, use_container_width=True,
                 type="primary" if active else "secondary"):
        st.switch_page(st.Page(fn))


# ---------- 侧边栏（登录后，可开关） ----------
st.session_state.setdefault("sidebar_open", True)
_sb_open = st.session_state["sidebar_open"]

with st.sidebar:
    st.markdown(f'<div style="padding:4px 0 0 0;">{logo_html(150, "0 0 0 0")}</div>',
                unsafe_allow_html=True)
    st.markdown('<p class="side-appname">知途伴学</p>', unsafe_allow_html=True)

    # 用户信息卡：头像（用户上传，未上传显示占位图标）+ 学生名 + 状态
    with st.container(border=True, key="side_user"):
        u1, u2 = st.columns([0.3, 0.7], vertical_alignment="center")
        with u1:
            avatar = avatar_html(state.student_id, 48)
            if avatar:
                st.markdown(avatar, unsafe_allow_html=True)
            else:
                st.markdown(":material/account_circle:")
        with u2:
            st.markdown(f"**{state.student_id}**")
            phase_label = env["orch"]._payload(state).get("phase_label", "")
            st.caption(phase_label or " ")
        if st.button("账户管理 ›", use_container_width=True, key="side_acct"):
            st.switch_page(st.Page(account_page))

    # 核心功能框
    st.markdown('<div class="section-title" style="margin:14px 0 6px 0;">'
                '核心功能</div>', unsafe_allow_html=True)
    for i, (title, icon, fn) in enumerate(NAV):
        _nav_button(title, icon, fn, current.title == title, key=f"nav_{i}")

    # 系统框
    st.markdown('<div class="section-title" style="margin:14px 0 6px 0;">'
                '系统</div>', unsafe_allow_html=True)
    for i, (title, icon, fn) in enumerate(SYS):
        _nav_button(title, icon, fn, current.title == title, key=f"sys_{i}")

    st.divider()
    if st.button("结束本次会话", use_container_width=True,
                 disabled=state.phase == "reflecting"):
        env["orch"].handle(state, "结束")
        st.rerun()
    if st.button("退出登录", use_container_width=True):
        st.session_state["agent_state"] = None
        st.session_state["login_pwd"] = ""  # 退出后清除密码框，避免残留
        # 清页面级残留：学生切换器等有 key 的组件会记住上一个账户的选择，
        # 不清理会导致新账户登录后画像页仍显示上一个学生的数据
        for k in ("profile_student", "profile_report_cache"):
            st.session_state.pop(k, None)
        st.rerun()
    llm_cfg = env["cfg"]["llm"]
    mode = ("真实大模型：" + llm_cfg.get("model", "")) \
        if llm_cfg.get("provider") != "mock" else "离线模式（未配置 Key）"
    st.caption(mode)
    st.caption(f"知识库：{len(env['kg'].nodes)} 节点 / {len(env['questions'])} 题")

# ---------- 侧边栏开关：每页顶部右对齐，登录后所有页面可用 ----------
import time as _time

_c1, _c2 = st.columns([5.8, 1], vertical_alignment="center")
with _c2:
    if st.button("✕ 收起侧边栏" if _sb_open else "☰ 打开侧边栏",
                 key="sb_toggle", help="显示 / 隐藏左侧导航栏"):
        st.session_state["sidebar_open"] = not _sb_open
        st.rerun()
with _c1:
    # 诊断小字：渲染时间戳（点按钮后应变化）+ 浏览器窗口宽度，供排查用
    st.markdown(
        f'<span id="sbdiag" style="color:#64748b;font-size:.78rem;">'
        f'侧边栏：{"显示" if _sb_open else "已收起"} · 渲染 {_time.strftime("%H:%M:%S")}'
        f'</span><script>setTimeout(()=>{{const e=document.getElementById("sbdiag");'
        f'if(e) e.textContent += " · 窗口 "+window.innerWidth+"px";}},60)</script>',
        unsafe_allow_html=True)
if _sb_open:
    # 强制显示：在主区注入（晚于主题 CSS 与 Streamlit 默认折叠规则），
    # 显式清掉 transform/position，任何宽度下左栏都钉住
    st.markdown(
        '<style>section[data-testid="stSidebar"]{display:flex !important;'
        'transform:none !important;width:320px !important;min-width:320px !important;'
        'position:relative !important;left:0 !important}'
        '[data-testid="stMain"]{position:static !important;min-width:0 !important}</style>',
        unsafe_allow_html=True)
else:
    # 收起：display:none 在主区注入，晚于主题 CSS，同优先级时后者生效
    st.markdown(
        '<style>section[data-testid="stSidebar"]{display:none !important}</style>',
        unsafe_allow_html=True)

current.run()
