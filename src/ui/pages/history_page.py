"""历史对话页：过往学习会话列表 + 跨会话长期记忆可见入口 + 学习档案

每个会话：开始时间 / 状态（进行中或已结束）/ 交互条数 / 反思摘要，
展开可见本会话内的交互记录。顶部「知途记得你」汇总长期记忆，底部「学习
档案」跨会话聚合并可导出 Markdown。
"""
import time

import streamlit as st

from src.path.review import due_reviews
from src.ui.pages.chat_page import chat_page


def history_page():
    st.header("历史对话")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None:
        st.info("请先登录。")
        return
    mem = env["mem"]
    if state.profile is not None:
        _memory_card(env, state, mem)
        st.divider()
    sessions = mem.list_sessions(state.student_id)
    if not sessions:
        # 空状态统一为「一句话 + 一个行动按钮」，学生不用自己找入口
        with st.container(border=True):
            st.markdown("**还没有学习会话**")
            st.caption("开始第一段学习后，会话记录、反思摘要和学习档案会出现在这里。")
            if st.button("开始一段学习 →", type="primary", key="hist_go_chat"):
                st.switch_page(st.Page(chat_page))
        return
    for s in sessions:
        active = s["session_id"] == state.session_id
        status = "进行中" if active else "已结束"
        n = mem.interaction_count(s["session_id"])
        started = (time.strftime("%Y-%m-%d %H:%M", time.localtime(s["started_at"]))
                   if s["started_at"] else "—")
        title = f"会话 {s['session_id']} · {started} · {status} · {n} 条交互"
        with st.expander(title, expanded=active):
            if s["summary"]:
                st.markdown(f"**本段小结**：{s['summary']}")
            msgs = mem.session_interactions(s["session_id"], limit=12)
            if msgs:
                for m in msgs:
                    text = (m["content"] or "").strip()[:60]
                    if not text:
                        continue
                    if m["kind"] == "quiz":
                        d = m.get("delta") or {}
                        pick, ans = d.get("choice"), d.get("answer")
                        # 补上「你选 X，正确 Y」：只给题干前缀学生看不出当时错在哪
                        if pick or ans:
                            text = f"{text}（你选 {pick or '—'}，正确 {ans or '—'}）"
                        st.caption(f"📝 {text}")
                    elif m["kind"] == "scaffold":
                        st.caption(f"🪜 {text}")
                    elif m["kind"] == "message":
                        st.caption(f"💬 {text}")
                    else:
                        st.caption(f"· {text}")
            else:
                st.caption("（本会话暂无交互记录）")

    st.divider()
    _study_archive(env, state, mem, sessions)


def _memory_card(env, state, mem):
    """🧠 知途记得你：把跨会话长期记忆（目标/风格/上次反思/观察/复习）显式呈现"""
    profile, kg = state.profile, env["kg"]
    sid = state.student_id
    due = due_reviews(profile, kg, hits=mem.correct_by_node(sid),
                      last_map=mem.last_ts_by_node(sid))
    overdue = sum(1 for r in due if r["overdue"])
    prev = mem.last_reflection(sid, exclude_session_id=state.session_id) or {}
    obs = mem.list_observations(sid, limit=1)
    obs_txt = ""
    if obs:
        c = obs[0]["content"]
        obs_txt = c.get("observation") or ""
    with st.container(border=True):
        st.markdown("### 🧠 知途记得你")
        st.markdown(
            f"- **长期目标**：{'、'.join(profile.goals) if profile.goals else '暂无'}\n"
            f"- **风格标签**：{'、'.join(profile.style_tags) if profile.style_tags else '暂无'}\n"
            f"- **上次会话预告**：{prev.get('next_session_preview') or '暂无'}\n"
            f"- **最近观察**：{obs_txt or '暂无'}\n"
            f"- **复习排程**：{overdue} 个已逾期（共 {len(due)} 个在排程中）\n"
            f"- **学习足迹**：{len(mem.list_sessions(sid))} 个会话 · 累计 "
            f"{_fmt_duration(mem.total_duration(sid))}")


def _study_archive(env, state, mem, sessions):
    """📚 学习档案：跨会话聚合的学习轨迹，可导出 Markdown"""
    profile, kg = state.profile, env["kg"]
    sid = state.student_id
    qs = mem.quiz_stats(sid)
    lines = [
        f"# {profile.name or '同学'} 的学习档案", "",
        f"- 专业：{profile.major or '—'}",
        f"- 学习目标：{'、'.join(profile.goals) if profile.goals else '—'}",
        f"- 学习会话：{len(sessions)} 段",
        f"- 累计学习时长：{_fmt_duration(mem.total_duration(sid))}",
        f"- 做题统计：共 {qs['total']} 题，答对 {qs['correct']}，答错 {qs['wrong']}", "",
        "## 会话轨迹",
    ]
    for s in reversed(sessions):
        started = (time.strftime("%Y-%m-%d %H:%M", time.localtime(s["started_at"]))
                   if s["started_at"] else "—")
        lines.append(f"- {started}｜{s['summary'] or '（未生成小结）'}")
    done = [kg.nodes[n].name for n in state.done_nodes if n in kg.nodes]
    lines += ["", "## 本会话已完成知识点", "、".join(done) or "—", ""]
    doc = "\n".join(lines)
    with st.expander("📚 学习档案（跨会话）"):
        st.markdown(doc)
        st.download_button(
            "⬇ 导出学习档案", data=doc,
            file_name=f"{profile.name or 'student'}_学习档案.md",
            mime="text/markdown",
            help="跨会话聚合的 Markdown 档案，可用任意编辑器打开或转为 PDF")


def _fmt_duration(sec):
    h, m = divmod(int(sec) // 60, 60)
    return f"{h} 小时 {m} 分" if h else f"{m} 分钟"
