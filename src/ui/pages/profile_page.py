"""学生画像页：学习数据看板（学情诊断可视化出口）

排版（面向竞赛演示，深色科技风）：页头（标题+长期目标+学生切换）→
能力概览（六维雷达+三档占比+核心能力分）→ 4 指标卡（hover 动效）→
学习分析 2×2（时长柱状/正确率环形/ZPD 分布/布鲁姆层级）→
知识点掌握度（七类雷达+排序表格+状态标签色）→
基本信息与 AI 学情诊断（LLM 生成，优势/薄弱/建议）→ 掌握度趋势。

指标公式与教育理论依据见 docs/学生画像页需求与设计文档.md。
"""
import json
import time

import streamlit as st

from src.student.diagnosis import gen_profile_report, profile_metrics
from src.ui.components import (ability_figure, accuracy_pie_figure,
                               bloom_figure, duration_bar_figure,
                               mastery_share_figure, radar_figure,
                               trend_figure, zpd_figure)

# 诊断报告缓存键：student_id -> {"fp": 指标指纹, "text": 报告}
_REPORT_CACHE = "profile_report_cache"


def profile_page():
    st.header("学生画像")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None or state.profile is None:
        st.info("请先登录并开始学习，画像页将展示学情数据。")
        return
    kg, mem = env["kg"], env["mem"]

    # ---- 学生切换：切换后整页按新学生数据重渲染（数据联动） ----
    students = mem.list_students_with_data()
    view_profile = state.profile
    if len(students) > 1:
        cur = students.index(state.student_id) if state.student_id in students else 0
        sel = st.selectbox("查看学生", students, index=cur,
                           key="profile_student",
                           help="切换后全部图表、表格与诊断报告同步刷新")
        if sel != state.student_id:
            restored = mem.restore_profile(sel)
            if restored is not None:
                view_profile = restored
    profile = view_profile
    qs = mem.quiz_stats(profile.student_id)

    # ---- 画像跟进：看自己的画像且空闲超 5 分钟，先让大模型更新一次再展示 ----
    orch = env["orch"]
    if (profile.student_id == state.student_id
            and state.phase in ("teaching", "intervening")
            and orch._idle_update_due(state)):
        with st.spinner("学习数据已同步，正在生成最新画像观察…"):
            orch._update_profile_from_conversation(state, "idle")

    # ---- 页头：长期目标标签 ----
    goals = "、".join(profile.goals) if profile.goals else "暂无"
    st.markdown(
        f'<div class="chat-banner"><div class="cb-left">'
        f'<span class="cb-phase">长期目标</span>'
        f'<span class="cb-name">{goals}</span></div>'
        f'<div class="cb-right">知途伴学 · 学习数据看板</div></div>',
        unsafe_allow_html=True)

    # ---- 能力概览：六维雷达 + 三档占比 + 核心能力分 ----
    st.markdown('<div class="section-title">能力概览</div>',
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.35, 1, 0.9])
    with c1:
        st.plotly_chart(ability_figure(env, state), use_container_width=True)
    with c2:
        st.plotly_chart(mastery_share_figure(kg, profile),
                        use_container_width=True)
    with c3:
        _ability_scores(kg, profile, qs)

    # ---- 学习数据概览：4 指标卡（hover 动效） ----
    st.markdown('<div class="section-title">学习数据概览</div>',
                unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    acc = qs["correct"] / qs["total"] if qs["total"] else 0.0
    for col, label, value, hint in (
        (m1, "总做题数", f"{qs['total']} 题", "全部测验作答"),
        (m2, "错题数", f"{qs['wrong']} 题", "自动汇入错题本"),
        (m3, "正确率", f"{acc * 100:.0f}%", "答对题数 / 总做题数"),
        (m4, "总学习时长", _fmt_duration(mem.total_duration(profile.student_id)),
         "全部会话累计"),
    ):
        with col:
            with st.container(border=True, key=f"profile_metric_{label}"):
                st.metric(label, value, help=hint)

    # ---- 学习分析 2×2：时长 / 正确率 / ZPD / 布鲁姆 ----
    st.markdown('<div class="section-title">学习分析</div>',
                unsafe_allow_html=True)
    a1, a2 = st.columns(2)
    with a1:
        st.plotly_chart(
            duration_bar_figure(mem.duration_by_day(profile.student_id)),
            use_container_width=True)
    with a2:
        st.plotly_chart(accuracy_pie_figure(qs["correct"], qs["wrong"]),
                        use_container_width=True)
    a3, a4 = st.columns(2)
    with a3:
        band = state.report.get("band") or env["planner"].zpd_band(profile)
        st.plotly_chart(zpd_figure(kg, profile, band), use_container_width=True)
    with a4:
        st.plotly_chart(bloom_figure(kg, profile), use_container_width=True)

    # ---- 知识点掌握度：七类雷达 + 详情表（排序/状态色） ----
    st.markdown('<div class="section-title">知识点掌握度</div>',
                unsafe_allow_html=True)
    k1, k2 = st.columns([1, 1.35])
    with k1:
        st.plotly_chart(radar_figure(kg, profile), use_container_width=True)
    with k2:
        _mastery_table(kg, profile)

    # ---- 基本信息与 AI 学情诊断 ----
    st.divider()
    st.subheader("基本信息与诊断报告")
    b1, b2 = st.columns([0.9, 1.6])
    with b1:
        st.markdown(f"**姓名**：{profile.name}　**专业**：{profile.major or '—'}")
        st.markdown(f"**学习目标**：{'、'.join(profile.goals) if profile.goals else '—'}")
        if profile.style_tags:
            st.markdown(f"**风格标签**：{'、'.join(profile.style_tags)}")
        if profile.needs_review:
            st.markdown("**待复习**：" + "、".join(
                kg.nodes[n].name for n in list(profile.needs_review)[:6]))
        r = state.report
        if r:
            st.markdown(f"**诊断覆盖**：{r['covered']} 节点 / "
                        f"{r['total_questions']} 题，正确率 {r['accuracy']}（{r['stop_reason']}）")
    with b2:
        _ai_diagnosis(env, kg, profile, band)

    # ---- 大模型观察记录：画像随对话持续生长的证据 ----
    st.divider()
    st.subheader("大模型观察记录")
    obs = mem.list_observations(profile.student_id)
    if obs:
        for o in obs:
            c = o["content"]
            parts = []
            if c.get("style_tags_add"):
                parts.append("新增标签：" + "、".join(c["style_tags_add"]))
            if c.get("goals_update"):
                parts.append("目标更新为：" + c["goals_update"])
            if c.get("observation"):
                parts.append(c["observation"])
            when = time.strftime("%m-%d %H:%M", time.localtime(o["ts"]))
            why = "会话结束" if o["reason"] == "session_end" else "空闲跟进"
            st.caption(f"{when} · {why}：{'；'.join(parts)}")
    else:
        st.caption("暂无观察记录。结束一次会话、或离开超过 5 分钟后再回来，"
                   "大模型会根据对话内容在这里持续更新你的画像。")

    # ---- 掌握度变化趋势 ----
    st.divider()
    st.subheader("掌握度变化趋势（掌握度快照）")
    history = mem.snapshot_history(profile.student_id)
    if history:
        st.plotly_chart(trend_figure(kg, history), use_container_width=True)
    else:
        st.caption("完成几次作答后，这里会展示各知识点掌握度随时间的演变曲线。")


def _ai_diagnosis(env, kg, profile, band):
    """AI 学情诊断：指标指纹缓存 + LLM 生成（Mock 模式规则兜底）"""
    has_data = any(v > 0.05 for v in profile.mastery.values()) or \
        env["mem"].quiz_stats(profile.student_id)["total"] > 0
    if not has_data:
        st.info("暂无学习数据。完成学情诊断测验后，这里会自动生成"
                "你的优势、薄弱点与学习建议。")
        return
    m = profile_metrics(profile, kg, env["mem"])
    m["zpd"] = {"z_low": round(band.get("z_low", 0), 3),
                "z_high": round(band.get("z_high", 0), 3)}
    fp = json.dumps(m, ensure_ascii=False, sort_keys=True)
    cache = st.session_state.setdefault(_REPORT_CACHE, {})
    entry = cache.get(profile.student_id)
    if entry and entry["fp"] == fp:
        st.markdown(entry["text"])
        return
    with st.spinner("正在生成学情诊断…"):
        text = gen_profile_report(env["llm"], profile, kg, env["mem"], band)
    cache[profile.student_id] = {"fp": fp, "text": text}
    st.markdown(text)


def _ability_scores(kg, profile, qs):
    """核心能力分卡片：平均掌握度 / 已掌握数 / 最强类别"""
    import statistics
    mastery = profile.mastery
    mean = sum(mastery.values()) / max(len(mastery), 1)
    mastered = sum(1 for v in mastery.values() if v >= 0.75)
    cats = {}
    for nid, node in kg.nodes.items():
        cats.setdefault(node.category, []).append(mastery.get(nid, 0.0))
    best_cat = max(cats, key=lambda c: statistics.mean(cats[c])) if cats else "—"
    with st.container(border=True):
        st.markdown("**核心能力分**")
        st.metric("平均掌握度", f"{mean * 100:.0f} 分")
        st.metric("已掌握", f"{mastered} / {len(kg.nodes)} 个知识点")
        st.caption(f"最强类别：{best_cat}")
        st.caption(f"答题正确率：{qs['correct']}/{qs['total']}")


def _mastery_table(kg, profile):
    """知识点掌握度详情表：默认按掌握度降序，进度条+状态标签着色"""
    rows = []
    for nid, node in kg.nodes.items():
        th = profile.mastery.get(nid, 0.0)
        status = "已掌握" if th >= 0.75 else ("学习中" if th > 0.05 else "未开始")
        icon = {"已掌握": "🟢", "学习中": "🔵", "未开始": "⚪"}[status]
        rows.append({"知识点": node.name, "类别": node.category,
                     "掌握度": round(th, 3), "状态": f"{icon} {status}"})
    rows.sort(key=lambda row: -row["掌握度"])
    st.dataframe(
        rows, use_container_width=True, hide_index=True,
        column_config={
            "掌握度": st.column_config.ProgressColumn(
                "掌握度", min_value=0.0, max_value=1.0, format="%.3f"),
        },
        height=430)


def _fmt_duration(sec):
    h, m = divmod(int(sec) // 60, 60)
    return f"{h} 小时 {m} 分" if h else f"{m} 分钟"
