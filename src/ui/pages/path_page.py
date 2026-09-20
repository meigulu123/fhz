"""学习路径页：进度概览 + 时间线路径 + 节奏参数 + 重规划 + 历史版本"""
import time

import streamlit as st

from src.ui.components import TIER_BADGES


def path_page():
    st.header("🗺️ 学习路径")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None or state.profile is None:
        st.info("请先登录并完成诊断，路径页将展示个性化学习计划。")
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
            st.caption("排序公式：0.30·ZPD贴近度 + 0.25·(1−掌握度) + "
                       "0.20·中心性 + 0.15·目标相似度 + 0.10·认知契合")

    if state.plan.get("notes"):
        st.markdown(f"**整体安排**：{state.plan['notes']}")

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

    # ===== 操作按钮 =====
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🔄 重新规划本批路径", use_container_width=True):
            orch._new_batch(state, "")
            st.rerun()
    with c2:
        in_progress = bool(items and plan_idx < len(items))
        if st.button("📦 生成下一批", use_container_width=True,
                     disabled=in_progress,
                     help="当前批次尚未学完；学完后可生成下一批"):
            orch._new_batch(state, "")
            st.rerun()
    if items and plan_idx < len(items):
        st.caption("💡 完成本批全部知识点后，才能生成下一批。")
    with c3:
        if st.button("🏁 结束会话", use_container_width=True,
                     disabled=state.phase == "reflecting"):
            orch.handle(state, "结束")
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
            status_color = "#34d399"
            bg_color = "rgba(52, 211, 153, 0.08)"
        elif i == plan_idx:
            status_icon = "▶️"
            status_color = "#22d3ee"
            bg_color = "rgba(34, 211, 238, 0.12)"
        else:
            status_icon = "⏳"
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
                {['已完成','学习中','待学习'][min(i,2) if i!=plan_idx else 1] if i != plan_idx else '学习中'}
            </div>
        </div>
        """, unsafe_allow_html=True)

