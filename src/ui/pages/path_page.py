"""学习路径页：进度概览 + 时间线路径 + 节奏参数 + 重规划 + 历史版本"""
import time

import streamlit as st

from src.ui.components import TIER_BADGES, flash
from src.ui.pages.chat_page import chat_page
from src.path.review import due_reviews


def path_page():
    st.header("🗺️ 学习路径")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None or state.profile is None:
        # 空状态统一为「一句话 + 一个行动按钮」，学生不用自己找入口
        with st.container(border=True):
            st.markdown("**还没有学习计划**")
            st.caption("完成一次学情诊断，这里会自动生成因人而异的个性化学习路径。")
            if st.button("去完成学情诊断 →", type="primary", key="path_go_chat"):
                st.switch_page(st.Page(chat_page))
        return
    kg, orch, profile = env["kg"], env["orch"], state.profile

    items = state.plan.get("items", [])
    plan_idx = state.plan_idx

    # ===== 顶部进度概览 =====
    _progress_overview(items, plan_idx, profile)

    # ===== ZPD 带信息 =====
    band = state.plan.get("band") or env["planner"].zpd_band(profile)
    with st.expander("📐 ZPD 最近发展区说明"):
        st.markdown(f"**ZPD 难度带**：`{band.get('z_low')} ~ {band.get('z_high')}`"
                    f"（中心 {band.get('z_center')}）")
        st.caption("ZPD = 最近发展区，指学生在指导下能掌握的难度范围。"
                   "低于带底 = 太简单（复习档），高于带上界 = 太难（暂缓档）。")
        if state.plan.get("engine") == "llm":
            st.caption("排序引擎：AI 大模型结合学情定序")
        else:
            st.caption("排序公式：0.28·ZPD贴近度 + 0.22·(1−掌握度) + 0.17·中心性 + "
                       "0.13·目标相似度 + 0.10·认知契合 + 0.10·复习紧迫度")

    if state.plan.get("notes"):
        st.markdown(f"**整体安排**：{state.plan['notes']}")

    # ===== 学习节奏与难度适配 =====
    pacing = state.plan.get("pacing") or {}
    if pacing.get("pace") is not None:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("节奏系数", f"{pacing.get('pace')}")
        with c2:
            st.metric("本批知识点", f"{pacing.get('batch')} 个")
        with c3:
            st.metric("难度带", f"{band.get('z_low')} ~ {band.get('z_high')}")
        if pacing.get("focus"):
            st.caption(f"🎯 难度与节奏适配：{pacing['focus']}（节奏由近 10 题正确率与卡壳次数动态计算）")

    # ===== 今日待复习：间隔重复排程（1/3/7/15 天） =====
    _review_section(env, state, profile)

    # ===== 学习日历：近 7 天打卡 + 今日任务 =====
    _study_calendar(state, env["mem"], items, plan_idx)

    # ===== 路径时间线 =====
    if not items:
        st.success("🎉 当前没有排入计划的知识点——你可能已经掌握得不错！")
    else:
        _timeline_view(items, plan_idx)

        # 详细表格
        with st.expander("📊 详细评分表"):
            rows = []
            for i, it in enumerate(items):
                if i < plan_idx:
                    status = "✅ 已完成"
                elif i == plan_idx:
                    status = "▶️ 学习中"
                else:
                    status = "⏳ 待学习"
                rows.append({
                    "序号": i + 1, "知识点": it["name"], "状态": status,
                    "档位": TIER_BADGES.get(it["tier"], it["tier"]),
                    "难度": f"{it['difficulty']:.2f}", "掌握度": f"{it['mastery']:.2f}",
                    "评分": f"{it['score']:.3f}",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

        # 评分理由
        with st.expander("💡 为什么这样排？（前5个）"):
            for it in items[:5]:
                st.caption(f"**「{it['name']}」**：{it['reason']}")

        # 评分构成：六因子分项明细（让人看到排序是算出来的）
        with st.expander("📐 评分构成（前5个）"):
            shown = False
            for it in items[:5]:
                terms = it.get("terms") or {}
                if not terms:
                    continue
                shown = True
                parts = " ＋ ".join(f"{k} {v:.3f}" for k, v in terms.items())
                st.caption(f"**「{it['name']}」**（总分 {it['score']:.3f}）：{parts}")
            if not shown:
                st.caption("本批路径由 AI 定序，暂无公式评分明细。")

    # ===== 操作按钮 =====
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🔄 重新规划本批路径", use_container_width=True):
            orch._new_batch(state, "")
            flash("已按最新学情重新规划本批路径", icon="🔄")
            st.rerun()
    with c2:
        in_progress = bool(items and plan_idx < len(items))
        if st.button("📦 生成下一批", use_container_width=True,
                     disabled=in_progress,
                     help="当前批次尚未学完；学完后可生成下一批"):
            orch._new_batch(state, "")
            flash("已生成本批学习计划", icon="📦")
            st.rerun()
    if items and plan_idx < len(items):
        st.caption("💡 完成本批全部知识点后，才能生成下一批。")
    with c3:
        if st.button("🏁 结束会话", use_container_width=True,
                     disabled=state.phase == "reflecting"):
            orch.handle(state, "结束")
            flash("已结束本次会话，正在生成学习反思", icon="🏁")
            st.rerun()

    st.divider()
    with st.expander("📜 历史路径版本"):
        hist = env["mem"].plan_history(profile.student_id)
        if not hist:
            st.caption("暂无历史计划。")
        for h in hist[:5]:
            names = [it.get("name", it.get("node_id")) for it in h["plan"].get("items", [])]
            st.caption(f"{time.strftime('%m-%d %H:%M', time.localtime(h['ts']))} · "
                       f"pace={h['pace']} · " + " → ".join(names[:6]))


def _progress_overview(items, plan_idx, profile):
    """顶部进度概览：完成数 + 进度条 + 统计"""
    total = len(items)
    done = sum(1 for i in range(total) if i < plan_idx)
    current_idx = min(plan_idx, total - 1) if total > 0 else 0
    pct = done / total if total > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("本批知识点", f"{total} 个")
    with c2:
        st.metric("已完成", f"{done} / {total}",
                  delta=f"{pct*100:.0f}%" if total else "—")
    with c3:
        mastered_count = sum(1 for t in profile.mastery.values() if t >= 0.75)
        st.metric("全局已掌握", f"{mastered_count} 个")
    with c4:
        avg_mastery = sum(profile.mastery.values()) / max(len(profile.mastery), 1)
        st.metric("平均掌握度", f"{avg_mastery:.2f}")

    if total > 0:
        st.progress(pct, text=f"本批学习进度：{done}/{total} ({pct*100:.0f}%)")


def _timeline_view(items, plan_idx):
    """时间线视图：从上到下展示学习顺序"""
    st.markdown("#### 📈 学习路径时间线")

    for i, it in enumerate(items):
        name = it["name"]
        tier = TIER_BADGES.get(it["tier"], it["tier"])
        difficulty = it["difficulty"]
        mastery = it["mastery"]

        if i < plan_idx:
            status_icon = "✅"
            status_text = "已完成"
            status_color = "#34d399"
            bg_color = "rgba(52, 211, 153, 0.08)"
        elif i == plan_idx:
            status_icon = "▶️"
            status_text = "学习中"
            status_color = "#22d3ee"
            bg_color = "rgba(34, 211, 238, 0.12)"
        else:
            status_icon = "⏳"
            status_text = "待学习"
            status_color = "#64748b"
            bg_color = "rgba(100, 116, 139, 0.05)"

        # 时间线卡片
        st.markdown(f"""
        <div style="
            display: flex; align-items: center; gap: 12px;
            padding: 12px 16px; margin: 4px 0;
            background: {bg_color};
            border-left: 3px solid {status_color};
            border-radius: 0 12px 12px 0;
        ">
            <div style="font-size: 20px; min-width: 30px;">{status_icon}</div>
            <div style="flex: 1;">
                <div style="font-weight: 600; color: #e8eef8;">
                    {i+1}. {name}
                </div>
                <div style="font-size: 12px; color: #8ea3c0; margin-top: 2px;">
                    档位：{tier} · 难度：{difficulty:.2f} · 当前掌握度：{mastery:.2f}
                </div>
            </div>
            <div style="
                font-size: 11px; color: {status_color};
                background: {bg_color};
                padding: 4px 10px; border-radius: 999px;
                border: 1px solid {status_color};
            ">
                {status_text}
            </div>
        </div>
        """, unsafe_allow_html=True)


def _review_section(env, state, profile):
    """今日待复习：间隔重复排程中到期的知识点（跨会话，逾期排在最前）"""
    mem, kg = env["mem"], env["kg"]
    sid = profile.student_id
    due = due_reviews(profile, kg, hits=mem.correct_by_node(sid),
                      last_map=mem.last_ts_by_node(sid))
    st.markdown("#### 🔁 今日待复习")
    if not due:
        st.caption("暂无到期复习项。学过的知识点会按 1 / 3 / 7 / 15 天的间隔自动排复习。")
        return
    overdue = [r for r in due if r["overdue"]]
    st.markdown(f"**已逾期 {len(overdue)} 个 / 共 {len(due)} 个在复习排程中**")
    for r in due[:8]:
        tag = "⚠️ 已逾期" if r["overdue"] else f"还有 {r['days_left']} 天到期"
        st.progress(min(1.0, r["urgency"]),
                    text=f"{r['name']}（掌握度 {r['mastery']}）· "
                         f"间隔 {r['interval_days']} 天 · {tag}")


def _study_calendar(state, mem, items, plan_idx):
    """学习日历：近 7 天（含今天）学习打卡 + 今日任务，把路径落到「每天做什么」"""
    st.markdown("#### 🗓️ 学习日历")
    sid = state.profile.student_id
    # duration_by_day 的 day_offset：0 = 最早一天 … 6 = 今天
    daily = {d["day_offset"]: d["seconds"] for d in mem.duration_by_day(sid, 7)}
    nodes_by_day = _nodes_by_day(mem, sid, 7)
    now = time.time()
    cols = st.columns(7, gap="small")
    for d_ago in range(6, -1, -1):        # 左→右：6 天前 → 今天
        label = ("今天" if d_ago == 0 else
                 "昨天" if d_ago == 1 else
                 time.strftime("%m-%d", time.localtime(now - d_ago * 86400)))
        mins = round(daily.get(6 - d_ago, 0.0) / 60)
        done = len(nodes_by_day.get(d_ago, ()))
        with cols[6 - d_ago]:
            with st.container(border=True):
                st.markdown(f"**{label}**")
                st.caption(f"学习 {mins} 分钟")
                st.caption(f"完成 {done} 个知识点" if done else "—")

    today_tasks = items[plan_idx:] if plan_idx < len(items) else []
    if today_tasks:
        st.markdown("**📌 今日任务**：" + "、".join(
            f"{i + 1}. {it['name']}"
            for i, it in enumerate(today_tasks, start=plan_idx)))
        if st.button("▶ 开始今日学习", type="primary", key="cal_start"):
            st.switch_page(st.Page(chat_page))
    else:
        st.caption("🎉 本批知识点已全部学完，可以去生成下一批。")


def _nodes_by_day(mem, sid, days=7):
    """近 N 天每天「真正学完」的知识点集合（0 = 今天），用于日历打卡展示

    只认教学完成记录：摸底/练习答题只是作答证据，不该计成「完成知识点」，
    否则一次摸底会被日历显示成「学会了好几个知识点」，误导学生对进度的认知。
    """
    now = time.time()
    out = {}
    for r in mem.recent_interactions(sid, limit=800):
        nid = r.get("node_id")
        if not nid or r.get("kind") != "teach":
            continue
        if "完成" not in (r.get("content") or ""):
            continue
        off = int((now - (r.get("ts") or now)) // 86400)
        if 0 <= off < days:
            out.setdefault(off, set()).add(nid)
    return out

