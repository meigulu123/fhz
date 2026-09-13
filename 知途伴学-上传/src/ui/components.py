"""UI 共享组件：掌握度条/雷达图/ZPD 分布图/掌握度趋势/知识图谱网络图"""
from __future__ import annotations

import statistics

import networkx as nx
import plotly.graph_objects as go
import streamlit as st

from src.student.profile import BLOOM_LABELS, cognitive_profile

CATEGORY_ORDER = ["数学基础", "ML概论", "经典监督学习", "集成学习",
                  "神经网络深度学习", "评估调优", "无监督学习"]
TIER_BADGES = {"A": "主修", "复习": "复习巩固", "暂缓": "暂缓"}

# 深色主题配色（与 theme.py 保持一致）
_INK = "#c7d5e8"
_GRID = "rgba(120, 190, 255, 0.13)"
_ACCENT = "#22d3ee"


def dark(fig):
    """统一深色图表风格：透明底 + 青蓝网格 + 浅色文字（与玻璃卡片融合）

    注意：曲线轴/标题只在已有文字时才套样式——plotly.js 遇到没有 text 的
    title 对象会把它渲染成字符串 "undefined"。
    """
    axis_style = dict(gridcolor=_GRID, zerolinecolor=_GRID, linecolor=_GRID,
                      tickfont=dict(color="#8ea3c0", size=11))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=_INK, size=12),
        xaxis=dict(axis_style), yaxis=dict(axis_style),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=_INK, size=11)),
    )
    if fig.layout.title and fig.layout.title.text:
        fig.update_layout(title=dict(font=dict(color="#dbe9fb", size=14)))
    axis_title_font = dict(color="#a9c0dc", size=12)
    for axis_name in ("xaxis", "yaxis"):
        axis = getattr(fig.layout, axis_name, None)
        if axis is not None and axis.title and axis.title.text:
            fig.update_layout(**{axis_name: {"title": {"font": axis_title_font}}})
    # 色条属于 trace 层属性，逐个染色（掌握度色阶的刻度文字）
    for trace in fig.data:
        if getattr(trace, "marker", None) is not None \
                and getattr(trace.marker, "showscale", False):
            trace.marker.colorbar = dict(
                tickfont=dict(color="#8ea3c0"), outlinewidth=0, thickness=12,
                title=dict(font=dict(color="#8ea3c0")))
    if fig.layout.polar is not None:
        fig.update_polars(
            bgcolor="rgba(255,255,255,0.03)",
            radialaxis=dict(gridcolor=_GRID, linecolor=_GRID,
                            tickfont=dict(color="#8ea3c0")),
            angularaxis=dict(gridcolor=_GRID, linecolor=_GRID,
                             tickfont=dict(color=_INK)),
        )
    return fig


def category_averages(kg, profile) -> dict:
    """七个知识类别的平均掌握度"""
    cats = {}
    for nid, node in kg.nodes.items():
        cats.setdefault(node.category, []).append(profile.mastery.get(nid, 0.0))
    return {c: round(statistics.mean(v), 3) for c, v in cats.items()}


def mastery_bar(theta):
    if theta is None:
        st.caption("暂无掌握度数据")
        return
    st.progress(min(1.0, max(0.0, theta)), text=f"掌握度 θ = {theta:.3f}")


def phase_badge(phase: str, label: str):
    st.markdown(f"**当前阶段**：`{phase}` · {label}")


def radar_figure(kg, profile) -> go.Figure:
    avgs = category_averages(kg, profile)
    vals = [avgs.get(c, 0.0) for c in CATEGORY_ORDER]
    fig = go.Figure(go.Scatterpolar(
        r=vals + [vals[0]], theta=CATEGORY_ORDER + [CATEGORY_ORDER[0]],
        fill="toself", name="类别平均掌握度",
        line=dict(color=_ACCENT, width=2), fillcolor="rgba(34,211,238,0.22)"))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 1], tickvals=[0.25, 0.5, 0.75, 1])),
        height=380, margin=dict(l=60, r=60, t=50, b=40),
        title="七类知识掌握度雷达")
    return dark(fig)


def zpd_figure(kg, profile, band=None) -> go.Figure:
    """知识点（难度, 掌握度）散点 + ZPD/复习/暂缓三带叠加"""
    band = band or {"z_low": 0.3, "z_high": 0.45}
    nids = list(kg.nodes)
    xs = [kg.nodes[n].difficulty for n in nids]
    ys = [profile.mastery.get(n, 0.0) for n in nids]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers", name="知识点",
        text=[f"{kg.nodes[n].name}<br>θ={ys[i]:.3f}" for i, n in enumerate(nids)],
        hoverinfo="text",
        marker=dict(size=9, color=ys, colorscale="RdYlGn", cmin=0, cmax=1,
                    showscale=True, colorbar=dict(title="θ", thickness=12))))
    fig.add_vrect(x0=0, x1=band["z_low"], fillcolor="#f59e0b", opacity=0.10,
                  annotation_text="复习带", annotation_position="top left",
                  annotation_font=dict(color="#c79a4a", size=11))
    fig.add_vrect(x0=band["z_low"], x1=band["z_high"], fillcolor=_ACCENT,
                  opacity=0.13, annotation_text="ZPD 带",
                  annotation_position="top",
                  annotation_font=dict(color="#7fe6ff", size=11))
    fig.add_vrect(x0=band["z_high"], x1=1.0, fillcolor="#94a3b8", opacity=0.07,
                  annotation_text="暂缓带", annotation_position="top right",
                  annotation_font=dict(color="#8ea3c0", size=11))
    fig.update_layout(height=420, xaxis_title="知识点难度",
                      yaxis_title="当前掌握度 θ", yaxis_range=[0, 1])
    return dark(fig)


def bloom_figure(kg, profile) -> go.Figure:
    """布鲁姆认知层级分布：x=1~6 层级，y=该层平均掌握度"""
    cog = cognitive_profile(profile, kg)
    dist = cog["distribution"]
    levels = [b for b in range(1, 7) if b in dist]
    fig = go.Figure(go.Bar(
        x=[BLOOM_LABELS[b] for b in levels],
        y=[dist[b] for b in levels],
        marker_color=_ACCENT, marker_opacity=0.75))
    fig.update_layout(
        height=320, margin=dict(l=40, r=20, t=50, b=40),
        xaxis_title="布鲁姆认知层级", yaxis_title="平均掌握度", yaxis_range=[0, 1],
        title=f"认知层级分布（当前 ≈ L{int(round(cog['level']))}·{cog['label']}）")
    return dark(fig)


def trend_figure(kg, history: list) -> go.Figure:
    """掌握度快照趋势：每条折线一个知识点"""
    fig = go.Figure()
    if not history:
        return dark(fig)
    import time as _t
    seen = set()
    for r in history:
        nid = r["node_id"]
        if nid not in kg.nodes or nid in seen:
            continue
        seen.add(nid)
        pts = [x for x in history if x["node_id"] == nid]
        fig.add_trace(go.Scatter(
            x=[_t.strftime("%H:%M:%S", _t.localtime(p["ts"])) for p in pts],
            y=[p["theta"] for p in pts], mode="lines+markers",
            name=kg.nodes[nid].name[:12]))
    fig.update_layout(height=400, xaxis_title="时间", yaxis_title="掌握度 θ",
                      yaxis_range=[0, 1], legend=dict(font=dict(size=9)))
    return dark(fig)


def kg_figure(kg, mastery: dict | None = None, plan=None, current_node=None) -> go.Figure:
    """知识图谱网络图：节点颜色=掌握度，先修边从左到右按拓扑层布局"""
    mastery = mastery or {}
    G = nx.DiGraph()
    G.add_nodes_from(kg.nodes)
    for e in kg.edges:
        G.add_edge(e.source, e.target)
    layers = kg.topological_layers()
    layer_nodes = {}
    for nid, lyr in layers.items():
        layer_nodes.setdefault(lyr, []).append(nid)
    pos = {}
    for lyr in sorted(layer_nodes):
        nids = sorted(layer_nodes[lyr], key=lambda n: kg.nodes[n].difficulty)
        for i, nid in enumerate(nids):
            pos[nid] = (lyr * 1.0, i - len(nids) / 2.0 + 0.5)
    edge_x, edge_y = [], []
    for s, t in G.edges:
        edge_x += [pos[s][0], pos[t][0], None]
        edge_y += [pos[s][1], pos[t][1], None]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                             line=dict(color="rgba(150,200,255,0.28)", width=1),
                             hoverinfo="none", name="先修关系"))
    thetas = [mastery.get(n, 0.0) for n in G.nodes]
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in G.nodes], y=[pos[n][1] for n in G.nodes],
        mode="markers", name="知识点（颜色=掌握度）",
        text=[f"{kg.nodes[n].name}<br>θ={mastery.get(n, 0.0):.3f}"
              for n in G.nodes], hoverinfo="text",
        marker=dict(size=15, color=thetas, colorscale="RdYlGn", cmin=0, cmax=1,
                    line=dict(color="rgba(200,230,255,0.45)", width=0.8),
                    showscale=True,
                    colorbar=dict(title="θ", thickness=12))))
    if plan and plan.get("items"):
        pids = [it["node_id"] for it in plan["items"] if it["node_id"] in pos]
        fig.add_trace(go.Scatter(
            x=[pos[n][0] for n in pids], y=[pos[n][1] for n in pids],
            mode="markers", name="学习路径",
            text=[kg.nodes[n].name for n in pids], hoverinfo="text",
            marker=dict(size=20, color="rgba(0,0,0,0)",
                        line=dict(color="#ffd54a", width=3))))
    if current_node and current_node in pos:
        fig.add_trace(go.Scatter(
            x=[pos[current_node][0]], y=[pos[current_node][1]],
            mode="markers", name="当前学习", text=[kg.nodes[current_node].name],
            hoverinfo="text",
            marker=dict(size=26, symbol="star", color="#22d3ee",
                        line=dict(color="#eaffff", width=1))))
    fig.update_layout(height=600, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(visible=False, showgrid=False),
                      yaxis=dict(visible=False, showgrid=False))
    fig = dark(fig)
    fig.update_xaxes(gridcolor="rgba(0,0,0,0)", zerolinecolor="rgba(0,0,0,0)",
                     linecolor="rgba(0,0,0,0)")
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)", zerolinecolor="rgba(0,0,0,0)",
                     linecolor="rgba(0,0,0,0)")
    return fig


def info_card(env, state):
    """对话页右侧信息卡：相位/当前节点/讲义进度/掌握度/脚手架/计划预览"""
    orch = env["orch"]
    payload = orch._payload(state)
    with st.container(border=True):
        st.markdown(f"**学习状态** · {payload['phase_label']}")
        if payload["node_name"]:
            st.markdown(f"**当前知识点**：{payload['node_name']}"
                        f"（难度 {payload['node_difficulty']:.2f}）")
            mastery_bar(payload["theta"])
            total = payload["lecture_total"]
            if total:
                st.caption(f"讲义进度：第 {min(payload['lecture_para'] + 1, total)} / {total} 段")
        sc = payload["scaffold"]
        if sc["active"]:
            st.markdown(f"**脚手架干预**：{sc['level']} 阶梯")
        else:
            st.caption("脚手架：未激活")
        plan = payload["plan"]
        items = plan.get("items", [])
        if items:
            st.markdown("**本批路径**")
            for i, it in enumerate(items):
                mark = "✓" if i < payload["plan_idx"] else ("▶" if i == payload["plan_idx"] else "·")
                st.caption(f"{mark} {it['name']}（{TIER_BADGES.get(it['tier'], it['tier'])}）")
        if payload["report"]:
            r = payload["report"]
            st.markdown(f"**诊断报告**：覆盖 {r['covered']} 节点，"
                        f"正确率 {r['accuracy']}，建议起点「{r['suggested']}」")
        st.caption(f"已完成知识点 {len(payload['done_nodes'])} 个 · 会话 {payload['session_id']}")
