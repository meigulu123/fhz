"""学习路径页：有序节点列表（已完成/学习中/待学习）+ 节奏参数 + 重规划 + 历史版本"""
import time

import streamlit as st

from src.ui.components import TIER_BADGES


def path_page():
    st.header("学习路径")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None or state.profile is None:
        st.info("请先登录并完成诊断，路径页将展示个性化学习计划。")
        return
    kg, orch, profile = env["kg"], env["orch"], state.profile

    band = state.plan.get("band") or env["planner"].zpd_band(profile)
    st.markdown(f"**ZPD 带**：`{band.get('z_low')} ~ {band.get('z_high')}`"
                f"（当前平均掌握度 {band.get('z_low')}，上界随波动自适应）")
    st.caption("A 档=难度落在最近发展区内主修；复习档=低于带底，用于回补巩固；"
               "暂缓档=高于带上界，暂不排入。")

    items = state.plan.get("items", [])
    if not items:
        st.success("当前没有排入计划的知识点——你可能已经掌握得不错，"
                   "点击下方按钮生成下一批路径。")
    else:
        rows = []
        for i, it in enumerate(items):
            if i < state.plan_idx:
                status = "已完成"
            elif i == state.plan_idx:
                status = "学习中"
            else:
                status = "待学习"
            rows.append({
                "序号": i + 1, "知识点": it["name"], "状态": status,
                "档位": TIER_BADGES.get(it["tier"], it["tier"]),
                "难度": it["difficulty"], "掌握度": it["mastery"],
                "评分": it["score"],
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
        with st.expander("为什么这样排？（评分构成）"):
            for it in items[:5]:
                st.caption(f"「{it['name']}」：{it['reason']}；"
                           f"综合评分 {it['score']} = 0.30·ZPD 贴近度 + "
                           f"0.25·(1−掌握度) + 0.20·中心性 + 0.15·目标相似度 + 0.10·认知契合")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("重新规划本批路径", use_container_width=True):
            orch._new_batch(state, "")
            st.rerun()
    with c2:
        in_progress = bool(items and state.plan_idx < len(items))
        if st.button("按当前状态生成下一批", use_container_width=True,
                     disabled=in_progress,
                     help="当前批次尚未学完；学完后可生成下一批"):
            orch._new_batch(state, "")
            st.rerun()
    if items and state.plan_idx < len(items):
        st.caption("「按当前状态生成下一批」在完成本批全部知识点后可用。")
    with c3:
        if st.button("结束会话", use_container_width=True,
                     disabled=state.phase == "reflecting"):
            orch.handle(state, "结束")
            st.rerun()

    st.divider()
    with st.expander("历史路径版本"):
        hist = env["mem"].plan_history(profile.student_id)
        if not hist:
            st.caption("暂无历史计划。")
        for h in hist[:5]:
            names = [it.get("name", it.get("node_id")) for it in h["plan"].get("items", [])]
            st.caption(f"{time.strftime('%m-%d %H:%M', time.localtime(h['ts']))} · "
                       f"pace={h['pace']} · " + " → ".join(names[:6]))
