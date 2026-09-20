"""知识图谱页：50 节点网络图（颜色=掌握度，路径金色描边，当前节点星标）"""
import streamlit as st

from src.ui.components import kg_figure


def kg_page():
    st.header("🕸️ 知识图谱")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    kg = env["kg"]
    profile = state.profile if state else None
    mastery = profile.mastery if profile else {}
    plan = state.plan if state and state.plan else None
    current = state.current_node if state else None

    # 获取所有类别
    all_categories = sorted(set(n.category for n in kg.nodes.values()))

    # 筛选栏
    col1, col2, col3 = st.columns([2, 2, 3])
    with col1:
        selected_cat = st.selectbox(
            "按类别筛选",
            ["全部"] + all_categories,
            index=0
        )
    with col2:
        show_labels = st.checkbox("显示节点标签", value=True)

    st.caption("节点大小 = 掌握度（越大越熟）；节点边框色 = 知识类别；"
               "节点填充色 = 掌握度 θ（红 <0.4 / 黄 0.4~0.75 / 绿 ≥0.75）；"
               "金色描边 = 本批学习路径；★ = 当前学习知识点。")

    fig = kg_figure(kg, mastery=mastery, plan=plan, current_node=current,
                    category_filter=selected_cat)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("📚 知识结构")
        cats = _categories(kg)
        for cat, nids in cats.items():
            # 计算该类别平均掌握度
            cat_mastery = [mastery.get(n, 0) for n in nids]
            avg = sum(cat_mastery) / len(cat_mastery) if cat_mastery else 0
            st.caption(f"**{cat}**：{len(nids)} 节点 · 平均掌握度 {avg:.0%}")
    with c2:
        st.subheader("📊 掌握度分层")
        if mastery:
            low = sum(1 for t in mastery.values() if t < 0.4)
            mid = sum(1 for t in mastery.values() if 0.4 <= t < 0.75)
            high = sum(1 for t in mastery.values() if t >= 0.75)
            total = low + mid + high
            st.caption(f"🔴 未掌握（<0.4）：{low} 个 ({low/total*100:.0f}%)\n\n"
                       f"🟡 学习中（0.4~0.75）：{mid} 个 ({mid/total*100:.0f}%)\n\n"
                       f"🟢 已掌握（≥0.75）：{high} 个 ({high/total*100:.0f}%)")
            # 进度条
            st.progress(high / total if total else 0,
                        text=f"总掌握率：{high/total*100:.1f}%" if total else "")
        else:
            st.caption("登录后展示统计。")
    with c3:
        st.subheader("🎨 图例")
        st.caption("● 节点大小：掌握度越高越大\n\n"
                   "● 边框颜色：知识类别（见上方图例）\n\n"
                   "● 填充颜色：掌握度（红→黄→绿）\n\n"
                   "⭐ 星标：当前正在学\n\n"
                   "🟡 金框：本批学习路径")


def _categories(kg):
    cats = {}
    for nid, node in kg.nodes.items():
        cats.setdefault(node.category, []).append(nid)
    return cats
