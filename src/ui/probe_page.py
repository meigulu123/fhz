"""🧪 状态持久化探针页（P4 门禁）

验证目标：Streamlit 每次交互都会整脚本 rerun，AgentState 必须完整驻留
session_state，且可序列化往返（to_dict → from_dict 一致）。本页通过后才
允许业务页面依赖 session_state 持状态。

操作流程：① 修改状态（counter+1）→ 触发 rerun → 观察修改是否存活；
② 序列化往返断言 → 观察 to_dict/from_dict 是否一致。
"""
import streamlit as st

from src.agent.state import AgentState


def probe_page():
    st.header("状态持久化探针")
    st.caption("门禁：Streamlit 全脚本 rerun 后，AgentState 完整驻留 session_state 且可序列化")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")

    if state is None:
        st.warning("尚未登录。可在本页直接创建探针状态独立验证（不依赖左侧登录）。")
        if st.button("创建探针状态并驱动编排器", use_container_width=True):
            state = AgentState(student_id="probe_user")
            reply, _ = env["orch"].start_session(state)
            state.history.append({"role": "assistant", "content": reply})
            st.session_state["agent_state"] = state
            st.rerun()
        st.caption("提示：也可先在左侧登录，再回到本页对真实会话状态做验证。")
        return

    st.markdown("### ① 状态存活验证（rerun 不丢）")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("修改状态：interaction_count +1", use_container_width=True):
            state.interaction_count += 1
            st.session_state["probe_marker"] = st.session_state.get("probe_marker", 0) + 1
            st.rerun()
    with c2:
        if st.button("重置探针计数", use_container_width=True):
            st.session_state["probe_marker"] = 0
            st.rerun()
    marker = st.session_state.get("probe_marker", 0)
    if marker > 0:
        st.success(f"rerun 后修改存活：按钮已触发 {marker} 次 rerun，"
                   f"当前 interaction_count={state.interaction_count}")
    else:
        st.info("点击左侧按钮后，本行应变为绿色且计数保留——即 rerun 未丢状态。")

    st.markdown("### ② 序列化往返断言")
    if st.button("执行 to_dict → from_dict → to_dict 一致性检查", use_container_width=True):
        d = state.to_dict()
        s2 = AgentState.from_dict(d)
        ok = (s2.to_dict() == d)
        st.session_state["probe_roundtrip"] = ok
        st.rerun()
    if "probe_roundtrip" in st.session_state:
        if st.session_state["probe_roundtrip"]:
            st.success("序列化往返一致（AgentState 可完整持久化）")
        else:
            st.error("序列化往返不一致，需要修复 to_dict/from_dict")

    st.markdown("### ③ 状态完整性清单")
    checks = [
        ("profile 画像对象", state.profile is not None),
        ("掌握度条目数 == 知识图谱节点数", state.profile is not None
         and len(state.profile.mastery) == len(env["kg"].nodes)),
        ("对话 history 保留", len(state.history) > 0),
        ("plan 计划结构合法", isinstance(state.plan, dict)),
        ("scaffold 对象存在", state.scaffold is not None),
    ]
    for name, ok in checks:
        st.write("通过" if ok else "未通过", name)

    st.markdown("### ④ 当前状态摘要")
    st.json({
        "student_id": state.student_id, "phase": state.phase,
        "interaction_count": state.interaction_count,
        "plan_idx": state.plan_idx, "current_node": state.current_node,
        "lecture_para": state.lecture_para,
        "done_nodes": len(state.done_nodes), "history_msgs": len(state.history),
        "used_qids": len(state.used_qids), "session_id": state.session_id,
    })
