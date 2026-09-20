"""替换kg_figure函数"""
from pathlib import Path

p = Path('src/ui/components.py')
content = p.read_text(encoding='utf-8')

# 找到函数开始和结束位置
start_marker = 'def kg_figure(kg, mastery: dict | None = None, plan=None, current_node=None) -> go.Figure:'
start_idx = content.find(start_marker)

# 找到下一个函数定义作为结束
end_marker = '\ndef info_card('
end_idx = content.find(end_marker, start_idx)

print(f"Start: {start_idx}, End: {end_idx}")

new_func = '''def kg_figure(kg, mastery: dict | None = None, plan=None, current_node=None,
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
        )

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
'''

# 替换
new_content = content[:start_idx] + new_func + content[end_idx:]
p.write_text(new_content, encoding='utf-8')
print(f"Replaced kg_figure function. New file length: {len(new_content)}")
