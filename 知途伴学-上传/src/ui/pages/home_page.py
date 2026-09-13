"""首页：全息主视觉 + 数据指标条 + 功能卡片网格 + 快捷标签

版式参考已有获奖项目的深色科技风首页：居中标语 → 实时指标 → 卡片网格 → 胶囊标签。
"""
import streamlit as st

from src.ui.pages.chat_page import chat_page
from src.ui.pages.kg_page import kg_page
from src.ui.pages.path_page import path_page
from src.ui.pages.profile_page import profile_page
from src.ui.probe_page import probe_page
from src.ui.theme import logo_html

# 功能卡片：Material 图标名 + 标题 + 描述 + 目标页面（点击卡片跳转到对应页面）
_CARDS = [
    ("forum", "对话学习", "与伴学智能体对话完成诊断、测验与讲义学习，卡住时自动进入阶梯式引导", chat_page),
    ("radar", "学生画像", "七类知识掌握度雷达、最近发展区分布与掌握度变化趋势一屏呈现", profile_page),
    ("route", "学习路径", "按知识图谱先修关系与最近发展区生成个性化学习序列，支持动态重规划", path_page),
    ("hub", "知识图谱", "50 节点机器学习知识结构可视化，节点颜色随掌握度实时变化", kg_page),
    ("psychology", "记忆反思", "跨会话记录学情，会话结束自动反思，新会话开场即引用上次进度", chat_page),
    ("monitor_heart", "状态探针", "运行状态自检：状态持久化、序列化往返与完整性清单逐项验证", probe_page),
]


def home_page():
    surface, counts = _surface_stats()
    st.markdown(f"""
    <div class="hero-wrap">
        {logo_html(170, "0 auto 4px auto")}
        <p class="hero-sub">大模型驱动的自适应学习路径决策与伴学智能体</p>
        <p class="hero-desc">从学情诊断到路径规划，从实时干预到记忆反思——让每个学生都有一条自己的学习路线</p>
        <div class="stats-row">
            <span><span class="dot"></span>{counts['nodes']} 知识点</span>
            <span><span class="dot"></span>{counts['questions']} 道题</span>
            <span><span class="dot"></span>{counts['categories']} 类知识</span>
            <span><span class="dot"></span>{counts['levels']} 级脚手架</span>
            <span><span class="dot"></span>{surface}模式</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    _entry_buttons()

    st.markdown('<div class="section-title">核心能力</div>', unsafe_allow_html=True)
    _cards_grid()

    _quick_tags()

    with st.expander("系统架构"):
        _architecture_diagram()

    state = st.session_state.get("agent_state")
    if state is not None and not _diagnosed(state):
        st.markdown('<div class="section-title">开始学习</div>',
                    unsafe_allow_html=True)
        st.markdown("首次使用需要先完成 **4 问背景诊断 + 自适应测验**（约 2 分钟），"
                    "系统将据此生成你的学生画像与个性化学习路径。")
        if st.button("开始学习", type="primary"):
            _goto(chat_page)
    if state is not None and _diagnosed(state):
        st.markdown('<div class="section-title">我的学习概览</div>',
                    unsafe_allow_html=True)
        profile = state.profile
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("已掌握知识点", f"{sum(1 for t in profile.mastery.values() if t >= 0.75)} 个")
        c2.metric("平均掌握度",
                  f"{sum(profile.mastery.values()) / max(len(profile.mastery), 1):.3f}")
        c3.metric("本批计划", f"{len(state.plan.get('items', []))} 个知识点")
        c4.metric("已完成", f"{len(state.done_nodes)} 个知识点")


def _diagnosed(state) -> bool:
    """是否已完成学情诊断（有掌握度数据即可视为诊断完成）"""
    return bool(state is not None and state.profile and state.profile.mastery)


def _surface_stats():
    env = st.session_state.get("env")
    provider = env["cfg"]["llm"].get("provider") if env else "mock"
    surface = "离线" if provider == "mock" else "大模型"
    kg_nodes = len(env["kg"].nodes) if env else 50
    questions = len(env["questions"]) if env else 150
    categories = len({n.category for n in env["kg"].nodes.values()}) if env else 7
    return surface, {"nodes": kg_nodes, "questions": questions,
                     "categories": categories, "levels": 4}


def _entry_buttons():
    """主入口：跳转到对话学习页"""
    _, mid, _ = st.columns([1.1, 1.2, 1.1])
    with mid:
        state = st.session_state.get("agent_state")
        label = "继续学习" if _diagnosed(state) else "开始学习"
        if st.button(label, type="primary", use_container_width=True):
            _goto(chat_page)


def _quick_tags():
    tags = ["学情诊断", "最近发展区路径", "四级脚手架引导", "变式检验",
            "掌握度模型", "跨会话记忆", "离线可运行"]
    st.markdown('<div class="section-title">能力标签</div>', unsafe_allow_html=True)
    st.markdown('<div class="pill-row">' + "".join(
        f'<span class="pill">{t}</span>' for t in tags) + "</div>",
        unsafe_allow_html=True)


def _cards_grid():
    """核心能力卡片网格：每张卡片点击标题即跳转到对应页面"""
    for start in range(0, len(_CARDS), 3):
        cols = st.columns(3, gap="medium")
        for j in range(3):
            idx = start + j
            if idx >= len(_CARDS):
                break
            icon, title, desc, page = _CARDS[idx]
            with cols[j]:
                with st.container(border=True, key=f"card_{idx}"):
                    if st.button(f":material/{icon}: {title}", key=f"card_go_{idx}",
                                 use_container_width=True, help="点击进入"):
                        _goto(page)
                    st.caption(desc)


def _goto(page):
    """跳转到指定页面；切换失败不影响使用，退回左侧导航提示"""
    try:
        st.switch_page(st.Page(page))
    except Exception:  # noqa: BLE001 —— 跳转失败不影响使用
        st.info("请在左侧导航选择对应页面继续。")


_LAYERS = [
    ("用户交互层", "对话学习 · 学生画像 · 学习路径 · 知识图谱（Streamlit 多页面）"),
    ("智能体编排层", "感知 → 规划 → 行动 → 记忆 主循环 · 六状态有限状态机"),
    ("教学决策层", "学情诊断 · 最近发展区路径规划 · 脚手架干预 · 记忆反思"),
    ("领域知识层", "50 节点机器学习知识图谱 · 150 题题库 · 分段讲义（含提问位）"),
    ("数据持久层", "SQLite（WAL）记忆库：画像 / 会话 / 交互 / 快照 / 反思 / 计划 / 提示"),
    ("大模型接入层", "兼容主流大模型接口的抽象层 + 离线规则兜底（无 Key 全功能可用）"),
]


def _architecture_diagram():
    """分层架构图：玻璃盒子 + 层间箭头（HTML 绘制，无需图片资源）"""
    blocks = []
    for i, (title, desc) in enumerate(_LAYERS):
        blocks.append(
            f'<div class="gcard" style="min-height:auto; padding:10px 16px;">'
            f'<b style="color:#7fe6ff; font-size:14.5px;">{title}</b>'
            f'<span style="color:#9fb3ce; font-size:13px;">　{desc}</span></div>')
        if i < len(_LAYERS) - 1:
            blocks.append('<div style="text-align:center; color:#22d3ee;'
                          ' margin:3px 0;">↓</div>')
    st.markdown("".join(blocks), unsafe_allow_html=True)
