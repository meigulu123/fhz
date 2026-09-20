"""账户管理页：账户信息（含头像上传）/ 学习数据 / 修改密码 / 清空学习数据"""
import time

import streamlit as st

from src.ui.theme import AVATAR_DIR, avatar_html, avatar_path


def account_page():
    st.header("账户管理")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None:
        st.info("请先登录。")
        return
    mem, username = env["mem"], state.student_id

    c1, c2 = st.columns([1, 1], gap="large")
    with c1:
        _account_card(mem, username, state)
    with c2:
        _stats_card(mem, username)

    st.divider()
    c3, c4 = st.columns([1, 1], gap="large")
    with c3:
        _avatar_card(username)
    with c4:
        _password_card(mem, username)

    st.divider()
    _danger_card(env, mem, username, state)


def _account_card(mem, username, state):
    with st.container(border=True):
        st.subheader("账户信息")
        info = mem.account_info(username) or {}
        created = info.get("created_at")
        st.markdown(f"**账户名**：{username}")
        st.markdown(f"**注册时间**：" +
                    (time.strftime("%Y-%m-%d %H:%M", time.localtime(created))
                     if created else "—"))
        st.markdown(f"**当前会话**：{'进行中' if state.phase != 'reflecting' else '已结束'}")
        profile = state.profile
        if profile and profile.name:
            st.markdown(f"**学习档案**：{profile.name}"
                        + (f"（{profile.major}）" if profile.major else ""))
        if st.button("退出登录", use_container_width=True, key="acct_logout"):
            st.session_state["agent_state"] = None
            st.session_state["login_pwd"] = ""
            st.rerun()


def _avatar_card(username):
    """头像：本地预览 + 上传 + 删除（文件存 data/avatars/，不进 git）"""
    with st.container(border=True):
        st.subheader("头像")
        if st.session_state.pop("avatar_flash", None):
            st.success("头像已更新，左侧边栏立即生效。")
        cur = avatar_html(username, 72)
        if cur:
            st.markdown(cur, unsafe_allow_html=True)
        else:
            st.caption("还没设置头像，左侧边栏会显示默认人像图标。")
        up = st.file_uploader("上传头像（jpg/png，2MB 以内）",
                              type=["jpg", "jpeg", "png"], key="avatar_up")
        if up is not None and st.button("保存头像", key="avatar_save"):
            data = up.read()
            if len(data) > 2 * 1024 * 1024:
                st.error("图片超过 2MB，请换一张小一点的。")
            else:
                ext = up.name.rsplit(".", 1)[-1].lower() if "." in up.name else "png"
                AVATAR_DIR.mkdir(parents=True, exist_ok=True)
                # 先清掉旧后缀的头像文件，避免残留多张
                old = avatar_path(username)
                if old is not None:
                    old.unlink(missing_ok=True)
                (AVATAR_DIR / f"{username}.{ext}").write_bytes(data)
                st.session_state["avatar_flash"] = True
                st.rerun()
        if avatar_path(username) is not None and \
                st.button("删除头像", key="avatar_del"):
            avatar_path(username).unlink(missing_ok=True)
            st.rerun()


def _stats_card(mem, username):
    with st.container(border=True):
        st.subheader("学习数据")
        s = mem.account_stats(username)
        c1, c2 = st.columns(2)
        c1.metric("学习会话", f"{s['sessions']} 次")
        c2.metric("互动记录", f"{s['interactions']} 条")
        c3, c4 = st.columns(2)
        c3.metric("学习反思", f"{s['reflections']} 次")
        c4.metric("掌握度快照", f"{s['snapshots']} 点")
        st.caption(f"历史学习计划 {s['plans']} 版；全部数据存放于本地 SQLite 数据库，"
                   "不上传任何服务器。")


def _password_card(mem, username):
    with st.container(border=True):
        st.subheader("修改密码")
        old = st.text_input("原密码", type="password", key="pwd_old")
        new = st.text_input("新密码", type="password", key="pwd_new",
                            placeholder="至少 4 位")
        new2 = st.text_input("确认新密码", type="password", key="pwd_new2")
        if st.button("确认修改", type="primary", use_container_width=True,
                     key="pwd_submit"):
            if not (old and new and new2):
                st.error("请填写完整的密码信息")
            elif len(new) < 4:
                st.error("新密码至少 4 位")
            elif new != new2:
                st.error("两次输入的新密码不一致")
            elif not mem.change_password(username, old, new):
                st.error("原密码不正确")
            else:
                for k in ("pwd_old", "pwd_new", "pwd_new2"):
                    st.session_state[k] = ""
                st.success("密码已修改，下次登录请使用新密码")


def _danger_card(env, mem, username, state):
    with st.container(border=True):
        st.subheader("清空学习数据")
        st.caption("删除该账户下的画像、会话记录、掌握度快照、反思与学习计划，"
                   "账户本身保留。**此操作不可撤销。**")
        # 清空成功后的复位：必须在复选框实例化之前写 session_state，
        # 否则 Streamlit 报 "cannot be modified after the widget is instantiated"
        if st.session_state.pop("wipe_done", False):
            st.session_state["wipe_confirm"] = False
            st.success("学习数据已清空，学习档案已重置。")
        confirm = st.checkbox("我确认要清空全部学习数据", key="wipe_confirm")
        if st.button("清空学习数据", use_container_width=True, key="wipe_btn",
                     disabled=not confirm):
            mem.clear_student_data(username)
            from src.agent.state import AgentState
            st.session_state["agent_state"] = AgentState(student_id=username)
            st.session_state["wipe_done"] = True
            st.rerun()
            _ = env, state  # 保留引用避免未使用告警
