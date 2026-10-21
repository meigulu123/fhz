"""首页：全息主视觉 + 数据指标条 + 功能卡片网格 + 快捷标签

版式参考已有获奖项目的深色科技风首页：居中标语 → 实时指标 → 卡片网格 → 胶囊标签。
"""
import streamlit as st

from src.agent.state import AgentState
from src.ui.components import (flash, growth_figure, mastery_share_figure,
                               progress_ring_figure)
from src.ui.pages.chat_page import chat_page
from src.ui.pages.kg_page import kg_page
from src.ui.pages.path_page import path_page
from src.ui.pages.profile_page import profile_page
from src.ui.theme import logo_html

# 功能卡片：Material 图标名 + 标题 + 描述 + 目标页面（点击卡片跳转到对应页面）
_CARDS = [
    ("forum", "对话学习", "与伴学智能体对话完成诊断、测验与讲义学习，卡住时自动进入阶梯式引导", chat_page),
    ("radar", "学生画像", "七类知识掌握度雷达、最近发展区分布与成长曲线一屏呈现", profile_page),
    ("route", "学习路径", "按知识图谱先修关系与最近发展区生成个性化学习序列，支持动态重规划", path_page),
    ("hub", "知识图谱", "50 节点机器学习知识结构可视化，节点颜色随掌握度实时变化", kg_page),
    ("psychology", "记忆反思", "跨会话记录学情，会话结束自动反思，新会话开场即引用上次进度", chat_page),
]


def home_page():
    _, counts = _surface_stats()
    # 首屏只讲一件事：一句对仗主标语 + 一行关键数字。
    # 原来还叠了一行长描述和「离线/大模型模式」（侧栏已标注），首屏密度过高。
    st.markdown(f"""
    <div class="hero-wrap">
        {logo_html(170, "0 auto 10px auto")}
        <h1 class="hero-title">让每一次学习，都有一条清晰的路径</h1>
        <p class="hero-sub">知途伴学 · 大模型驱动的自适应学习路径决策与伴学智能体</p>
        <div class="stats-row">
            <span><span class="dot"></span>{counts['nodes']} 个知识点</span>
            <span><span class="dot"></span>{counts['questions']} 道题</span>
            <span><span class="dot"></span>{counts['categories']} 类知识</span>
            <span><span class="dot"></span>{counts['levels']} 级脚手架</span>
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
    # 首次进入自动弹出「三步上手」引导（可通过按钮关闭，每个会话只弹一次）
    if state is not None and not st.session_state.get("onboarding_seen", False):
        _onboarding_dialog(state)
    if state is not None and not _diagnosed(state):
        st.markdown('<div class="section-title">三步上手</div>',
                    unsafe_allow_html=True)
        st.markdown('<div class="steps-row">' + "".join([
            _step_card(1, "完成学情诊断",
                       "4 问对话 + 自适应测验，约 2 分钟锁定知识起点"),
            _step_card(2, "查看专属学习路径",
                       "按知识图谱先修关系与最近发展区排出学习顺序"),
            _step_card(3, "开始学习与练题",
                       "讲义分段推进；卡住时逐级给提示，不直接给答案"),
        ]) + '</div>', unsafe_allow_html=True)
        if st.button("开始学习", type="primary"):
            _goto(chat_page)
        _role_cards()
    if state is not None and _diagnosed(state):
        st.markdown('<div class="section-title">我的学习概览</div>',
                    unsafe_allow_html=True)
        profile = state.profile
        items = state.plan.get("items", [])
        mastered = sum(1 for t in profile.mastery.values() if t >= 0.75)
        # 关键数字只留 3 个：掌握宽度、掌握深度、当前批次推进度（原为 4 个卡）
        c1, c2, c3 = st.columns(3)
        c1.metric("已掌握知识点", f"{mastered} / {len(profile.mastery)} 个",
                  help="掌握度 θ ≥ 0.75 记为已掌握；分母是已测知识点数")
        c2.metric("平均掌握度",
                  f"{sum(profile.mastery.values()) / max(len(profile.mastery), 1):.3f}",
                  help="已测知识点的掌握度均值")
        if items:
            plan_ids = {it["node_id"] for it in items}
            batch_done = len(plan_ids & set(state.done_nodes))
            c3.metric("本批进度", f"{batch_done} / {len(items)}",
                      help=f"本批计划 {len(items)} 个知识点，已完成 {batch_done} 个")
        else:
            c3.metric("本批进度", "—", help="尚无学习批次，先去对话学习页开始")
        st.markdown('<div class="section-title">学习效率</div>',
                    unsafe_allow_html=True)
        _efficiency_metrics(state)
        _mini_dashboard(state)
        if st.button("查看完整画像 →", key="home_to_profile"):
            _goto(profile_page)


def _efficiency_metrics(state):
    """效率指标卡：累计学习时长 / 平均每题耗时 / 平均掌握度提升幅度"""
    env = st.session_state.get("env")
    if env is None:
        return
    mem, profile = env["mem"], state.profile
    total_sec = mem.total_duration(profile.student_id)
    stats = mem.quiz_stats(profile.student_id)
    c1, c2, c3 = st.columns(3)
    c1.metric("累计学习时长", f"{total_sec / 60:.0f} 分钟",
              help="按交互间隔累计的活跃时长，挂机不计")
    if stats["total"]:
        c2.metric("平均每题耗时", f"{total_sec / stats['total']:.0f} 秒",
                  help=f"累计学习时长 ÷ 答题数（共 {stats['total']} 题）")
    else:
        c2.metric("平均每题耗时", "—", help="做完摸底测验后开始统计")
    gain, base, cur = _mastery_gain(mem, profile)
    c3.metric("平均掌握度提升", f"{base:.3f} → {cur:.3f}" if base else "—",
              delta=f"{gain:+.3f}" if base else None,
              help="按同一批知识点比较：最早快照 → 当前掌握度")


def _mastery_gain(mem, profile):
    """掌握度提升幅度：对每个有快照记录的知识点，比较最早快照与当前值。

    返回 (提升幅度, 起点均值, 当前均值)；无快照时 base 为 None。
    """
    first = {}
    for r in mem.snapshot_history(profile.student_id):
        first.setdefault(r["node_id"], r["theta"])
    if not first:
        return 0.0, None, 0.0
    base = sum(first.values()) / len(first)
    cur = sum(profile.mastery.get(nid, t) for nid, t in first.items()) / len(first)
    return cur - base, base, cur


def _mini_dashboard(state):
    """首页迷你看板：路径完成度环形 + 掌握度三档占比 +（有记录时）成长曲线"""
    env = st.session_state.get("env")
    if env is None:
        return
    kg, mem, profile = env["kg"], env["mem"], state.profile
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(progress_ring_figure(len(state.done_nodes), len(kg.nodes)),
                        use_container_width=True)
    with g2:
        st.plotly_chart(mastery_share_figure(kg, profile), use_container_width=True)
    growth = mem.mastery_growth(profile.student_id)
    if growth:
        st.plotly_chart(growth_figure(growth), use_container_width=True)


def _step_card(no: int, title: str, desc: str, done: bool = False) -> str:
    """三步上手单张步骤卡（HTML）：done 时显示对勾与「已完成」"""
    cls = "step-card done" if done else "step-card"
    mark = "✓" if done else str(no)
    tag = '<span class="step-tag">已完成</span>' if done else ""
    return (f'<div class="{cls}"><span class="step-no">{mark}</span>'
            f'<div class="step-title">{title}{tag}</div>'
            f'<div class="step-desc">{desc}</div></div>')


@st.dialog("🧭 三步上手", width="large")
def _onboarding_dialog(state):
    """首次进入引导：把主流程（诊断 → 路径 → 学习）显性化，可跳过"""
    done = _diagnosed(state)
    st.markdown('<p class="onboard-tip">跟着三步，两分钟就能上手知途伴学。</p>',
                unsafe_allow_html=True)
    st.markdown('<div class="steps-row">' + "".join([
        _step_card(1, "完成学情诊断",
                   "4 问对话 + 自适应测验，约 2 分钟锁定知识起点", done),
        _step_card(2, "查看专属学习路径",
                   "按知识图谱先修关系与最近发展区排出学习顺序"),
        _step_card(3, "开始学习与练题",
                   "讲义分段推进；卡住时逐级给提示，不直接给答案"),
    ]) + '</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([1.5, 1])
    with c1:
        label = "查看我的学习路径" if done else "开始学情诊断"
        if st.button(label, type="primary", use_container_width=True):
            st.session_state["onboarding_seen"] = True
            _goto(path_page if done else chat_page)
    with c2:
        if st.button("跳过引导", use_container_width=True):
            st.session_state["onboarding_seen"] = True
            st.rerun()


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


# 演示角色：只预置背景（称呼/专业/目标），不预置掌握度——
# 基础由学生答完摸底测验真实测得，再据此生成路径与教学节奏。
DEMO_ROLES = [
    {"key": "demo_beginner", "label": "零基础转专业", "desc": "文科转计算机，先补先修基础",
     "name": "小林", "major": "汉语言文学（转计算机方向）",
     "goals": ["先补齐数学基础与机器学习先修知识"]},
    {"key": "demo_exam", "label": "考研冲刺提分", "desc": "数学系，专业课考点提分",
     "name": "阿哲", "major": "数学与应用数学",
     "goals": ["考研机器学习专业课提分"]},
    {"key": "demo_adv", "label": "进阶深耕", "desc": "计算机背景，深入深度学习",
     "name": "小周", "major": "计算机科学与技术",
     "goals": ["深入掌握深度学习与神经网络"]},
]
DEMO_PASSWORD = "demo"


def _role_cards():
    """演示角色体验：选一个典型学生身份，带专业/目标直接进入摸底测验"""
    st.markdown('<div class="section-title">演示角色体验</div>',
                unsafe_allow_html=True)
    st.caption("想直接看效果？选一个典型学生身份——专业和学习目标已替你填好，"
               "进去先做几道摸底题，系统按你的实际水平排学习路径。")
    env = st.session_state.get("env")
    cols = st.columns(len(DEMO_ROLES), gap="medium")
    for col, role in zip(cols, DEMO_ROLES):
        with col:
            with st.container(border=True, key=f"role_{role['key']}"):
                st.markdown(f"**{role['label']}**")
                st.caption(f"{role['desc']}　｜　专业：{role['major']}")
                if st.button("以该角色体验", key=f"role_go_{role['key']}",
                             use_container_width=True):
                    _enter_role(env, role)
                    st.rerun()


def _enter_role(env, role):
    """角色体验：建档（专业/目标已填好）→ 直接进入摸底测验（幂等：每次从干净档案开始）"""
    mem = env["mem"]
    sid = role["key"]
    if not mem.account_exists(sid):
        mem.create_account(sid, DEMO_PASSWORD)
    mem.clear_student_data(sid)
    state = AgentState(student_id=sid)
    reply = env["orch"].start_role_diagnosis(state, role["name"], role["major"],
                                             role["goals"])
    state.history.append({"role": "assistant", "content": reply})
    st.session_state["agent_state"] = state
    st.session_state["onboarding_seen"] = True      # 角色已带引导，不再叠弹窗
    flash(f"已切换到「{role['label']}」体验档案，先做几道摸底题", icon="🎭")
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
