"""知识图谱页：50 节点网络图（颜色=掌握度，路径金色描边，当前节点星标）

在上图基础上新增「知识点探索」：定位任一知识点 → 图内高亮它的先修链与
直接后继，并在下方展开该节点的基本信息、先修门槛与后继去向。
"""
import streamlit as st

from src.student.profile import BLOOM_LABELS
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
    with col3:
        focus = st.selectbox(
            "🔍 定位知识点（高亮其先修链与后继）",
            [""] + sorted(kg.nodes, key=lambda n: kg.nodes[n].name),
            format_func=lambda n: "（不定位）" if not n else kg.nodes[n].name,
            key="kg_focus")

    # 探索高亮：先修链（含间接先修）+ 直接后继；中心节点单独描边
    chain, succ = set(), []
    if focus and focus in kg.nodes:
        chain = _prereq_chain(kg, focus)
        succ = [n for n in kg.successors_of(focus)]
    highlight = (chain | set(succ)) - {focus}

    st.caption("节点大小 = 掌握度（越大越熟）；节点边框色 = 知识类别；"
               "节点填充色 = 掌握度 θ（红 <0.4 / 黄 0.4~0.75 / 绿 ≥0.75）；"
               "金色描边 = 本批学习路径；★ = 当前学习知识点；"
               "品红描边 = 定位知识点的先修链与后继，紫色外圈 = 定位知识点本身。")

    fig = kg_figure(kg, mastery=mastery, plan=plan, current_node=current,
                    category_filter=selected_cat, highlight=highlight,
                    emphasis=focus or None)
    st.plotly_chart(fig, use_container_width=True)

    if focus and focus in kg.nodes:
        _node_card(kg, mastery, focus, chain, succ)

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
        # 节点填充是连续色阶（Plotly RdYlGn），所以图例用真实渐变条而不是三色圆点，
        # 否则图例颜色会与图谱里的节点颜色对不上。
        st.markdown(
            '<div style="height:10px;border-radius:5px;margin:2px 0 4px 0;'
            'background:linear-gradient(90deg,#a50026,#d73027,#fdae61,#ffffbf,'
            '#a6d96a,#1a9850)"></div>'
            '<div style="display:flex;justify-content:space-between;font-size:11px;'
            'color:#a9c0dc"><span>0</span><span>0.4 学习中</span>'
            '<span>0.75 已掌握</span><span>1.0</span></div>',
            unsafe_allow_html=True)
        st.caption("填充色＝掌握度（0 红 → 1 绿）；节点越大掌握度越高；"
                   "边框色＝知识类别；⭐ 当前在学；🟡 金框＝本批学习路径")


def _prereq_chain(kg, node_id) -> set:
    """全部间接先修（沿 prerequisite 边向上回溯，含直接先修，不含自身）"""
    seen, stack = set(), list(kg.prereqs_of(node_id))
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in kg.nodes:
            continue
        seen.add(nid)
        stack.extend(kg.prereqs_of(nid))
    return seen


def _node_card(kg, mastery, node_id, chain, succ):
    """定位知识点详情：基本信息 + 先修门槛（链上掌握度）+ 后继去向"""
    node = kg.nodes[node_id]
    theta = mastery.get(node_id, 0.0)
    st.divider()
    st.subheader(f"🔍 知识点详情 · {node.name}")
    b1, b2, b3 = st.columns([1, 1, 1])
    with b1:
        st.markdown(f"**类别**：{node.category}")
        st.markdown(f"**难度**：{node.difficulty:.2f}")
        st.markdown(f"**布鲁姆层级**：L{node.bloom} {BLOOM_LABELS.get(node.bloom, '')}")
    with b2:
        st.markdown(f"**当前掌握度**：θ = {theta:.3f}")
        st.markdown(f"**建议学习时长**：{node.minutes} 分钟")
        st.markdown(f"**知识点编号**：{node.id}")
    with b3:
        st.markdown(f"**一句话概述**：{node.summary}")
        if node.objectives:
            st.caption("学习目标：" + "；".join(node.objectives[:2]))

    l1, l2 = st.columns(2)
    with l1:
        st.markdown(f"**先修门槛（{len(chain)} 个，含间接先修）**")
        if chain:
            for nid in sorted(chain, key=lambda n: -mastery.get(n, 0.0)):
                th = mastery.get(nid, 0.0)
                mark = "🟢" if th >= 0.75 else ("🟡" if th >= 0.4 else "🔴")
                st.caption(f"{mark} {kg.nodes[nid].name}（θ={th:.2f}）")
        else:
            st.caption("无先修门槛，可以直接学。")
    with l2:
        st.markdown(f"**直接后继（{len(succ)} 个）**")
        if succ:
            for nid in succ:
                th = mastery.get(nid, 0.0)
                st.caption(f"→ {kg.nodes[nid].name}（θ={th:.2f}）")
        else:
            st.caption("本知识点没有后继，是当前链条的终点。")


def _categories(kg):
    cats = {}
    for nid, node in kg.nodes.items():
        cats.setdefault(node.category, []).append(nid)
    return cats
