"""知途伴学 · Streamlit 入口（登录页 → 核心界面五页导航）

未登录只渲染登录页；登录后进入核心界面：对话学习 / 学生画像 / 学习路径 /
知识图谱 / 状态探针。无任何 API Key 时 MockLLM 离线兜底，配置真实 Key 后
自动切换真实大模型。
"""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.agent.state import AgentState  # noqa: E402
from src.ui.env import build_env  # noqa: E402
from src.ui.pages.account_page import account_page  # noqa: E402
from src.ui.pages.chat_page import chat_page  # noqa: E402
from src.ui.pages.home_page import home_page  # noqa: E402
from src.ui.pages.kg_page import kg_page  # noqa: E402
from src.ui.pages.login_page import login_page  # noqa: E402
from src.ui.pages.path_page import path_page  # noqa: E402
from src.ui.pages.profile_page import profile_page  # noqa: E402
from src.ui.probe_page import probe_page  # noqa: E402

st.set_page_config(page_title="知途伴学",
                   page_icon=str(ROOT / "assets" / "logo.png"), layout="wide")

from src.ui.theme import inject_theme, logo_html  # noqa: E402

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


def _top_bar(current):
    """页面顶栏：左侧返回首页（首页不显示），右上角账户入口"""
    left, right = st.columns([5, 1.4], vertical_alignment="center")
    with left:
        if current.title != "首页":
            st.markdown('<div class="back-home-bar">', unsafe_allow_html=True)
            if st.button("← 返回首页", key="back_home"):
                st.switch_page(st.Page(home_page))
            st.markdown('</div>', unsafe_allow_html=True)
    with right:
        with st.container(key="top_account"):
            if st.button(f":material/account_circle: {state.student_id}",
                         key="acct_entry", help="账户管理"):
                st.switch_page(st.Page(account_page))


# ---------- 侧边栏（登录后） ----------
with st.sidebar:
    st.markdown(f'<div style="padding:2px 0 6px 0;">{logo_html(150, "0 0 0 0")}</div>',
                unsafe_allow_html=True)
    st.divider()
    st.markdown(f"**学生**：{state.student_id}")
    if st.button("结束本次会话", use_container_width=True,
                 disabled=state.phase == "reflecting"):
        env["orch"].handle(state, "结束")
        st.rerun()
    if st.button("退出登录", use_container_width=True):
        st.session_state["agent_state"] = None
        st.session_state["login_pwd"] = ""  # 退出后清除密码框，避免残留
        st.rerun()
    st.divider()
    llm_cfg = env["cfg"]["llm"]
    mode = ("真实大模型：" + llm_cfg.get("model", "")) \
        if llm_cfg.get("provider") != "mock" else "离线模式（未配置 Key）"
    st.caption(mode)
    st.caption(f"知识库：{len(env['kg'].nodes)} 节点 / {len(env['questions'])} 题")

# ---------- 核心界面 ----------
pages = [
    st.Page(home_page, title="首页", default=True),
    st.Page(chat_page, title="对话学习"),
    st.Page(profile_page, title="学生画像"),
    st.Page(path_page, title="学习路径"),
    st.Page(kg_page, title="知识图谱"),
    st.Page(account_page, title="账户管理"),
    st.Page(probe_page, title="状态探针"),
]
current = st.navigation(pages)
_top_bar(current)
current.run()
