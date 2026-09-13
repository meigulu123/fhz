"""对话学习页：聊天 + 快捷指令 + 右侧信息卡（阶段/当前节点/掌握度/脚手架/路径）"""
import html

import streamlit as st

from src.ui.components import info_card
from src.ui.theme import MASCOT

# 快捷指令：把「求助（实时干预入口）」「推进」「结束反思」三个核心动作显性化
QUICK_ACTIONS = [
    ("help", "我不会，给点提示", "触发脚手架：系统不给答案，先反问引导"),
    ("arrow_forward", "继续", "推进讲义下一段或进入下一环节"),
    ("flag", "结束本次会话", "结束并生成学习反思，供下次开场引用"),
]


def chat_page():
    st.header("对话学习")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None:
        st.info("请先登录。")
        return

    left, right = st.columns([3, 1.1], gap="large")
    with right:
        info_card(env, state)
        if st.button("清空会话，重新诊断", use_container_width=True):
            from src.agent.state import AgentState
            new_state = AgentState(student_id=state.student_id)
            reply = env["orch"].restart_diagnosis(new_state)
            new_state.history.append({"role": "assistant", "content": reply})
            st.session_state["agent_state"] = new_state
            st.rerun()

    with left:
        _banner(env, state)
        for msg in state.history:
            # 助手用品牌吉祥物头像，学生用默认头像
            avatar = str(MASCOT) if msg["role"] == "assistant" else None
            with st.chat_message(msg["role"], avatar=avatar):
                st.markdown(msg["content"])

        _quick_actions(env, state)

        prompt = st.chat_input("输入你的回答或提问")
        if prompt:
            _submit(env, state, prompt)


def _submit(env, state, text):
    """向编排器提交输入；未预期异常不崩页面，保留状态并友好提示（演示安全网）"""
    try:
        env["orch"].handle(state, text)
    except Exception as exc:  # noqa: BLE001 —— 兜底：任何未预期错误都让应用存活
        st.error(f"系统遇到一点问题，已为你保留当前进度，请重试。\n\n`{exc}`")
        return
    st.rerun()


def _quick_actions(env, state):
    """快捷指令行：点击即向智能体发送对应文本（等价于手动输入）"""
    cols = st.columns(len(QUICK_ACTIONS))
    for i, (icon, label, help_text) in enumerate(QUICK_ACTIONS):
        with cols[i]:
            if st.button(f":material/{icon}: {label}", use_container_width=True,
                         help=help_text, key=f"quick_{i}",
                         disabled=state.phase == "reflecting"):
                _submit(env, state, label)


def _banner(env, state):
    """对话区顶部横幅：学生名 + 当前相位 + 当前知识点"""
    payload = env["orch"]._payload(state)
    name = html.escape((state.profile.name if state.profile else "") or "同学")
    node = html.escape(payload.get("node_name") or "尚未开始")
    phase = html.escape(payload.get("phase_label") or "")
    st.markdown(
        f'<div class="chat-banner">'
        f'<div class="cb-left"><span class="cb-name">{name}</span>'
        f'<span class="cb-phase">{phase}</span></div>'
        f'<div class="cb-right">当前知识点：{node}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
