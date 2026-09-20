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


def _empty_note(fig, text="暂无学习数据，完成诊断与练习后这里会显示分析"):
    """空状态：图中居中提示，不打断页面布局"""
    fig.add_annotation(text=text, showarrow=False, x=0.5, y=0.5,
                       xref="paper", yref="paper",
                       font=dict(color="#8ea3c0", size=13))
    return fig


def _band_name(x, band) -> str:
    """ZPD 带名（散点 hover 用）"""
    if x < band["z_low"]:
        return "复习带"
    if x <= band["z_high"]:
        return "ZPD 带"
    return "暂缓带"


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
        customdata=[_band_name(x, band) for x in xs],
        hovertemplate=("<b>%{text}</b><br>难度 %{x:.2f} · θ=%{y:.3f}"
                        "<br>位于 %{customdata}<extra></extra>"),
        text=[kg.nodes[n].name for n in nids],
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
    if not any(y > 0.05 for y in ys):
        _empty_note(fig)
    return dark(fig)


def bloom_figure(kg, profile) -> go.Figure:
    """布鲁姆认知层级分布：x=1~6 层级，y=该层平均掌握度"""
    cog = cognitive_profile(profile, kg)
    dist = cog["distribution"]
    levels = [b for b in range(1, 7) if b in dist]
    counts = {b: sum(1 for n in kg.nodes.values() if n.bloom == b) for b in levels}
    # L1~L6 青→紫渐变，体现认知层级由低到高的递进
    bloom_colors = ["#22d3ee", "#38bdf8", "#818cf8", "#a78bfa", "#c084fc", "#e879f9"]
    fig = go.Figure(go.Bar(
        x=[f"L{b} {BLOOM_LABELS[b]}" for b in levels],
        y=[dist[b] for b in levels],
        marker_color=[bloom_colors[b - 1] for b in levels], marker_opacity=0.8,
        customdata=[counts[b] for b in levels],
        hovertemplate=("<b>%{x}</b><br>该层平均掌握度 θ=%{y:.3f}"
                        "<br>该层节点数：%{customdata}<extra></extra>")))
    fig.update_layout(
        height=320, margin=dict(l=40, r=20, t=50, b=40),
        xaxis_title="布鲁姆认知层级", yaxis_title="平均掌握度", yaxis_range=[0, 1],
        title=f"认知层级分布（当前 ≈ L{int(round(cog['level']))}·{cog['label']}）")
    if not any(v > 0.05 for v in dist.values()):
        _empty_note(fig)
    return dark(fig)


def ability_figure(env, state) -> go.Figure:
    """六维学习能力雷达（0~100）：学习进度/知识掌握/逻辑理解/答题正确率/记忆巩固/学习投入"""
    profile, kg, mem = state.profile, env["kg"], env["mem"]
    mastery = profile.mastery
    total_nodes = max(len(kg.nodes), 1)
    mastered = sum(1 for v in mastery.values() if v >= 0.75)
    progress = mastered / total_nodes
    knowledge = sum(mastery.values()) / max(len(mastery), 1)
    # 逻辑理解：布鲁姆 4~6 层节点的平均掌握度（体现理解/分析/评价能力）
    high = [v for nid, v in mastery.items()
            if kg.nodes.get(nid) is not None and kg.nodes[nid].bloom >= 4]
    logic = sum(high) / len(high) if high else 0.0
    qs = mem.quiz_stats(profile.student_id)
    accuracy = qs["correct"] / qs["total"] if qs["total"] else 0.0
    # 记忆巩固：已掌握节点的练习证据充分度（8 次练习算满）
    ev = [min(1.0, profile.evidence_count.get(nid, 0) / 8)
          for nid, v in mastery.items() if v >= 0.75]
    retention = sum(ev) / len(ev) if ev else 0.0
    # 学习投入：累计学习时长（10 小时算满）
    effort = min(1.0, mem.total_duration(profile.student_id) / 36000)
    dims = ["学习进度", "知识掌握", "逻辑理解", "答题正确率", "记忆巩固", "学习投入"]
    vals = [progress, knowledge, logic, accuracy, retention, effort]
    defs = [
        "已掌握知识点 / 全部知识点 × 100",
        "全部知识点 BKT 掌握度 θ 的均值 × 100",
        "布鲁姆 4~6 层（分析/评价/创造）节点的掌握度均值 × 100",
        "答对题数 / 总做题数 × 100",
        "已掌握节点的练习证据饱和率（每节点 8 次练习满格）× 100",
        "累计学习时长 / 10 小时（封顶）× 100",
    ]
    fig = go.Figure(go.Scatterpolar(
        r=[v * 100 for v in vals] + [vals[0] * 100],
        theta=dims + [dims[0]], fill="toself", name="能力值",
        customdata=defs + [defs[0]],
        hovertemplate="<b>%{theta}</b>：%{r:.0f} 分<br>%{customdata}<extra></extra>",
        line=dict(color=_ACCENT, width=2), fillcolor="rgba(34,211,238,0.22)"))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100], tickvals=[25, 50, 75, 100])),
        height=360, margin=dict(l=70, r=70, t=46, b=30), title="六维学习能力")
    if not any(vals) and qs["total"] == 0:
        _empty_note(fig)
    return dark(fig)


def mastery_share_figure(kg, profile) -> go.Figure:
    """三档掌握度占比环形图：已掌握 / 学习中 / 未开始"""
    mastered = sum(1 for v in profile.mastery.values() if v >= 0.75)
    learning = sum(1 for v in profile.mastery.values() if 0.05 < v < 0.75)
    fresh = max(len(kg.nodes) - mastered - learning, 0)
    fig = go.Figure(go.Pie(
        labels=["已掌握", "学习中", "未开始"],
        values=[mastered, learning, fresh], hole=0.62, sort=False,
        marker=dict(colors=["#34d399", "#22d3ee", "#475569"]),
        textinfo="value",
        hovertemplate="<b>%{label}</b>：%{value} 个知识点（%{percent}）"
                      "<extra></extra>"))
    fig.update_layout(height=360, margin=dict(l=20, r=20, t=46, b=20),
                      title="掌握度三档占比", showlegend=True,
                      legend=dict(orientation="h", y=-0.05))
    return dark(fig)


def accuracy_pie_figure(correct, wrong) -> go.Figure:
    """做题正确率环形图：绿=正确、红=错误"""
    fig = go.Figure(go.Pie(
        labels=["正确", "错误"], values=[correct, wrong], hole=0.62,
        sort=False, marker=dict(colors=["#34d399", "#f87171"]),
        textinfo="value",
        hovertemplate="<b>%{label}</b>：%{value} 题（%{percent}）<extra></extra>"))
    fig.update_layout(height=360, margin=dict(l=20, r=20, t=46, b=20),
                      title="做题正确率", showlegend=True,
                      legend=dict(orientation="h", y=-0.05))
    if correct + wrong == 0:
        _empty_note(fig, "还没有做过题，完成测验后这里会显示正确率")
    return dark(fig)


def duration_bar_figure(daily: list) -> go.Figure:
    """近 7 天每日学习时长柱状图（分钟）"""
    import time as _time
    labels = [_time.strftime("%m-%d", _time.localtime(
        _time.time() - (len(daily) - 1 - d["day_offset"]) * 86400))
        for d in daily]
    mins = [round(d["seconds"] / 60, 1) for d in daily]
    fig = go.Figure(go.Bar(
        x=labels, y=mins,
        customdata=mins,
        hovertemplate="<b>%{x}</b>：%{y} 分钟<extra></extra>",
        marker_color=_ACCENT, marker_opacity=0.8))
    fig.update_layout(height=360, margin=dict(l=20, r=20, t=46, b=30),
                      xaxis_title="日期", yaxis_title="分钟",
                      title="近 7 天每日学习时长")
    if not any(mins):
        _empty_note(fig, "近 7 天还没有学习记录")
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


def kg_figure(kg, mastery: dict | None = None, plan=None, current_node=None,
              category_filter: str = "全部") -> go.Figure:
    """知识图谱网络图：按类别分组布局，节点颜色=掌握度，分类着色

    优化点：
    1. 按7大类别分组，每组横向排列，更清晰
    2. 节点大小随掌握度变化
    3. 边样式区分主路径和普通依赖
    4. 悬停显示更多信息
    5. 支持按类别筛选
    """
    mastery = mastery or {}
    G = nx.DiGraph()
    G.add_nodes_from(kg.nodes)
    for e in kg.edges:
        G.add_edge(e.source, e.target)

    # 类别颜色映射
    category_colors = {
        "数学基础": "#60a5fa",
        "ML概论": "#a78bfa",
        "经典监督学习": "#34d399",
        "集成学习": "#fbbf24",
        "神经网络深度学习": "#f472b6",
        "评估调优": "#fb923c",
        "无监督学习": "#94a3b8",
    }

    # 按类别分组布局
    categories = {}
    for nid, node in kg.nodes.items():
        if category_filter != "全部" and node.category != category_filter:
            continue
        categories.setdefault(node.category, []).append(nid)

    # 计算位置：每类占一列，类内垂直排列
    pos = {}
    cat_list = sorted(categories.keys())
    for ci, cat in enumerate(cat_list):
        nids = sorted(categories[cat], key=lambda n: kg.nodes[n].difficulty)
        n_count = len(nids)
        for i, nid in enumerate(nids):
            y_pos = (i - n_count / 2.0) * 1.2
            pos[nid] = (ci * 2.5, y_pos)

    # 边
    edge_x, edge_y = [], []
    for s, t in G.edges:
        if s not in pos or t not in pos:
            continue
        edge_x += [pos[s][0], pos[t][0], None]
        edge_y += [pos[s][1], pos[t][1], None]

    fig = go.Figure()

    # 先画边
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(color="rgba(150,180,230,0.25)", width=1.2),
        hoverinfo="none", name="先修关系", showlegend=False
    ))

    # 按类别画节点，这样图例能显示分类
    for cat in cat_list:
        nids = categories[cat]
        thetas = [mastery.get(n, 0.0) for n in nids]
        sizes = [18 + mastery.get(n, 0.0) * 12 for n in nids]
        cat_color = category_colors.get(cat, "#94a3b8")

        fig.add_trace(go.Scatter(
            x=[pos[n][0] for n in nids],
            y=[pos[n][1] for n in nids],
            mode="markers+text",
            name=cat,
            text=[kg.nodes[n].name for n in nids],
            textposition="middle right",
            textfont=dict(size=10, color="rgba(255,255,255,0.8)"),
            hovertext=[
                f"<b>{kg.nodes[n].name}</b><br>"
                f"类别：{kg.nodes[n].category}<br>"
                f"难度：{kg.nodes[n].difficulty:.2f}<br>"
                f"掌握度：θ={mastery.get(n, 0.0):.2f}"
                for n in nids
            ],
            hoverinfo="text",
            marker=dict(
                size=sizes,
                color=thetas,
                colorscale="RdYlGn",
                cmin=0, cmax=1,
                line=dict(color=cat_color, width=2),
                opacity=0.9,
                showscale=False,
            )
        ))

    # 颜色条
    all_nodes = list(pos.keys())
    all_thetas = [mastery.get(n, 0.0) for n in all_nodes]
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers",
        marker=dict(
            size=15, color=all_thetas, colorscale="RdYlGn",
            cmin=0, cmax=1, showscale=True,
            colorbar=dict(title="掌握度θ", thickness=12, x=1.02)
        ),
        showlegend=False, hoverinfo="none"
    ))

    # 学习路径金色描边
    if plan and plan.get("items"):
        pids = [it["node_id"] for it in plan["items"] if it["node_id"] in pos]
        if pids:
            fig.add_trace(go.Scatter(
                x=[pos[n][0] for n in pids], y=[pos[n][1] for n in pids],
                mode="markers", name="本批学习路径",
                text=[kg.nodes[n].name for n in pids], hoverinfo="text",
                marker=dict(size=26, color="rgba(0,0,0,0)",
                            line=dict(color="#ffd54a", width=3))
            ))

    # 当前节点星标
    if current_node and current_node in pos:
        fig.add_trace(go.Scatter(
            x=[pos[current_node][0]], y=[pos[current_node][1]],
            mode="markers", name="当前学习", text=[kg.nodes[current_node].name],
            hoverinfo="text",
            marker=dict(size=30, symbol="star", color="#22d3ee",
                        line=dict(color="#eaffff", width=2))
        ))

    # 类别背景区域
    for ci, cat in enumerate(cat_list):
        nids = categories[cat]
        ys = [pos[n][1] for n in nids]
        if ys:
            y_min, y_max = min(ys) - 0.8, max(ys) + 0.8
            fig.add_hrect(
                y0=y_min, y1=y_max,
                fillcolor=category_colors.get(cat, "#94a3b8"),
                opacity=0.05, line_width=0, layer="below"
            )

    fig.update_layout(
        height=650,
        margin=dict(l=20, r=80, t=30, b=20),
        xaxis=dict(visible=False, showgrid=False),
        yaxis=dict(visible=False, showgrid=False, range=[-12, 12]),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1,
            font=dict(size=11)
        ),
        hoverlabel=dict(bgcolor="rgba(30,40,60,0.95)", font_size=12)
    )
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
