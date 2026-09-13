"""知识图谱页：50 节点网络图（颜色=掌握度，路径金色描边，当前节点星标）"""
import streamlit as st

from src.ui.components import kg_figure


def kg_page():
    st.header("知识图谱")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    kg = env["kg"]
    profile = state.profile if state else None
    mastery = profile.mastery if profile else {}
    plan = state.plan if state and state.plan else None
    current = state.current_node if state else None

    st.caption("节点颜色 = 当前掌握度 θ（红 <0.4 / 黄 0.4~0.75 / 绿 ≥0.75）；"
               "边 = 先修依赖关系（自左向右按拓扑层展开）；"
               "金色描边 = 本批学习路径；★ = 当前学习知识点。")
    fig = kg_figure(kg, mastery=mastery, plan=plan, current_node=current)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("知识结构")
        for cat, nids in _categories(kg).items():
            st.caption(f"**{cat}**：{len(nids)} 节点")
    with c2:
        st.subheader("掌握度分层统计")
        if mastery:
            low = sum(1 for t in mastery.values() if t < 0.4)
            mid = sum(1 for t in mastery.values() if 0.4 <= t < 0.75)
            high = sum(1 for t in mastery.values() if t >= 0.75)
            st.caption(f"未掌握（<0.4）：{low} 个\n\n"
                       f"学习中（0.4~0.75）：{mid} 个\n\n"
                       f"已掌握（≥0.75）：{high} 个")
        else:
            st.caption("登录后展示统计。")
    with c3:
        st.subheader("图例")
        st.caption("● 红色：需要补基础\n\n● 黄色：正在构建\n\n"
                   "● 绿色：已掌握\n\n★：当前正在学\n\n金框：本批计划")


def _categories(kg):
    cats = {}
    for nid, node in kg.nodes.items():
        cats.setdefault(node.category, []).append(nid)
    return cats
