"""登录页：全息玻璃卡片（账户登录 / 注册 / 演示账号一键进入）"""
import streamlit as st

from src.agent.state import AgentState
from src.ui.theme import logo_html

DEMO_USER = "demo"
DEMO_PASSWORD = "demo"


def login_page(env):
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        st.markdown(f"""
        <div style="text-align:center; padding: 6vh 0 2px 0;">
            {logo_html(180, "0 auto 6px auto")}
            <p class="hero-desc" style="margin-bottom:0;">
                大模型驱动的自适应学习路径决策与伴学智能体
            </p>
        </div>
        """, unsafe_allow_html=True)
        with st.container(border=True):
            if st.session_state.get("auth_view") == "register":
                _register_view(env)
            else:
                _login_view(env)


def _make_state(env, student_id):
    """创建会话状态并完成开场（登录/演示共用）"""
    state = AgentState(student_id=student_id)
    reply, _ = env["orch"].start_session(state)
    state.history.append({"role": "assistant", "content": reply})
    return state


def _login_view(env):
    mem = env["mem"]
    flash = st.session_state.pop("auth_flash", None)
    if flash:
        st.success(flash)
    acc = st.text_input("账户", key="login_acc", placeholder="请输入账户")
    pwd = st.text_input("密码", key="login_pwd", type="password",
                        placeholder="请输入密码")
    # 按钮始终可点：空值在提交时校验。
    # 若用 disabled 绑定输入框内容，输入框失焦前脚本拿不到新值，
    # 用户打完字第一次点按钮会是禁用态、点了没反应。
    if st.button("登 录", type="primary", use_container_width=True):
        if not acc.strip() or not pwd:
            st.error("请输入账户和密码")
        elif mem.check_account(acc.strip(), pwd):
            st.session_state["agent_state"] = _make_state(env, acc.strip())
            st.rerun()
        else:
            st.error("账户或密码错误")
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("演示账号", use_container_width=True):
            # 演示账号也建一条账户记录，账户管理页的注册时间/改密码才可用
            if not mem.account_exists(DEMO_USER):
                mem.create_account(DEMO_USER, DEMO_PASSWORD)
            st.session_state["agent_state"] = _make_state(env, DEMO_USER)
            st.rerun()
    with c2:
        if st.button("注册新账号", use_container_width=True):
            st.session_state["auth_view"] = "register"
            st.rerun()
    st.caption(f"演示账号：{DEMO_USER} / {DEMO_PASSWORD}（也可直接点上方「演示账号」进入）")


def _register_view(env):
    mem = env["mem"]
    st.markdown("**注册新账号**")
    acc = st.text_input("账户", key="reg_acc", placeholder="设置账户名")
    pwd = st.text_input("密码", key="reg_pwd", type="password",
                        placeholder="设置密码（至少 4 位）")
    pwd2 = st.text_input("确认密码", key="reg_pwd2", type="password",
                         placeholder="再次输入密码")
    if st.button("注 册", type="primary", use_container_width=True):
        if not acc.strip():
            st.error("请填写账户名")
        elif not pwd or not pwd2:
            st.error("请填写密码并确认")
        elif len(pwd) < 4:
            st.error("密码至少 4 位")
        elif pwd != pwd2:
            st.error("两次输入的密码不一致")
        elif mem.account_exists(acc.strip()):
            st.error("账户已存在，请直接登录")
        elif mem.create_account(acc.strip(), pwd):
            # 注册成功：自动返回登录页并预填账户
            st.session_state["login_acc"] = acc.strip()
            st.session_state["auth_view"] = "login"
            st.session_state["auth_flash"] = "注册成功，请登录"
            st.rerun()
        else:
            st.error("注册失败，请稍后重试")
    if st.button("返回登录", use_container_width=True):
        st.session_state["auth_view"] = "login"
        st.rerun()
