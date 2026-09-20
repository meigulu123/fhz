"""历史对话页：过往学习会话列表

每个会话：开始时间 / 状态（进行中或已结束）/ 交互条数 / 反思摘要，
展开可见本会话内的交互记录。
"""
import time

import streamlit as st


def history_page():
    st.header("历史对话")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None:
        st.info("请先登录。")
        return
    mem = env["mem"]
    sessions = mem.list_sessions(state.student_id)
    if not sessions:
        st.info("还没有学习会话。开始一段学习后，会话记录会出现在这里。")
        return
    for s in sessions:
        active = s["session_id"] == state.session_id
        status = "进行中" if active else "已结束"
        n = mem.interaction_count(s["session_id"])
        started = (time.strftime("%Y-%m-%d %H:%M", time.localtime(s["started_at"]))
                   if s["started_at"] else "—")
        title = f"会话 {s['session_id']} · {started} · {status} · {n} 条交互"
        with st.expander(title, expanded=active):
            if s["summary"]:
                st.markdown(f"**本段小结**：{s['summary']}")
            msgs = mem.session_interactions(s["session_id"], limit=12)
            if msgs:
                for m in msgs:
                    text = (m["content"] or "").strip()[:60]
                    if not text:
                        continue
                    if m["kind"] == "quiz":
                        st.caption(f"📝 {text}")
                    elif m["kind"] == "scaffold":
                        st.caption(f"🪜 {text}")
                    elif m["kind"] == "message":
                        st.caption(f"💬 {text}")
                    else:
                        st.caption(f"· {text}")
            else:
                st.caption("（本会话暂无交互记录）")
