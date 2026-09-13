"""学生画像页：雷达图 + ZPD 分布 + 掌握度趋势 + 诊断报告"""
import streamlit as st

from src.ui.components import bloom_figure, radar_figure, trend_figure, zpd_figure


def profile_page():
    st.header("学生画像")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None or state.profile is None:
        st.info("请先登录并开始学习，画像页将展示学情数据。")
        return
    kg, mem, profile = env["kg"], env["mem"], state.profile

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(radar_figure(kg, profile), use_container_width=True)
    with c2:
        band = state.report.get("band") or env["planner"].zpd_band(profile)
        st.plotly_chart(zpd_figure(kg, profile, band), use_container_width=True)

    st.plotly_chart(bloom_figure(kg, profile), use_container_width=True)

    st.divider()
    st.subheader("基本信息与诊断报告")
    b1, b2 = st.columns(2)
    with b1:
        st.markdown(f"**姓名**：{profile.name}　**专业**：{profile.major or '—'}")
        st.markdown(f"**学习目标**：{'、'.join(profile.goals) if profile.goals else '—'}")
        if profile.style_tags:
            st.markdown(f"**风格标签**：{'、'.join(profile.style_tags)}")
        if profile.needs_review:
            st.markdown("**待复习**：" + "、".join(
                kg.nodes[n].name for n in list(profile.needs_review)[:6]))
    with b2:
        r = state.report
        if r:
            st.markdown(f"**诊断覆盖**：{r['covered']} 节点 / {r['total_questions']} 题，"
                        f"正确率 {r['accuracy']}（{r['stop_reason']}）")
            st.markdown(f"**掌握较好**：{'、'.join(r['strong'][:4]) or '待观察'}")
            st.markdown(f"**需要加强**：{'、'.join(r['weak'][:4]) or '无'}")
            st.markdown(f"**建议起点**：{r['suggested']}")
            cog = r.get("cognitive") or {}
            if cog.get("level"):
                st.markdown(f"**认知水平**：布鲁姆 L{int(round(cog['level']))}（{cog.get('label', '')}）")

    st.divider()
    st.subheader("掌握度变化趋势（掌握度快照）")
    history = mem.snapshot_history(profile.student_id)
    if history:
        st.plotly_chart(trend_figure(kg, history), use_container_width=True)
    else:
        st.caption("完成几次作答后，这里会展示各知识点掌握度随时间的演变曲线。")
