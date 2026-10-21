"""错题本页：自动收集所有答错的题 + 错因归类 + 一键组卷重练

按题聚合：完整题干 / 选项 / 正确答案 / 解析 / 知识点 / 答错次数 / 最近时间。
数据来源是每次测验落库的作答记录（含正确性标记），无需学生手动添加。
"""
import time
from collections import Counter

import streamlit as st

from src.student.error_cause import error_cause
from src.ui.components import flash

MAX_RETRY = 5          # 重练卷最多题数
RETRY_KEYS = ("retry_paper", "retry_idx", "retry_answers", "retry_feedback")


def wrongbook_page():
    st.header("📕 错题本")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None:
        st.info("请先登录。")
        return
    mem, kg = env["mem"], env["kg"]
    attempts = mem.wrong_attempts(state.student_id)
    if not attempts:
        st.success("🎉 还没有答错过的题，继续保持！答错的题会自动收集到这里。")
        return

    # ===== 聚合同题 =====
    grouped = {}
    for a in attempts:
        q = _match_question(env, a["content"])
        if q is None:
            continue
        key = q.get("id") or q.get("stem")
        g = grouped.setdefault(key, {"q": q, "count": 0, "last": 0.0})
        g["count"] += 1
        g["last"] = max(g["last"], a["ts"])
    rows = sorted(grouped.values(), key=lambda g: g["last"], reverse=True)
    for g in rows:
        node = kg.nodes.get(g["q"].get("node_id"))
        g["cause"], g["cause_hint"] = _error_cause(
            g["q"], profile=state.profile, count=g["count"],
            node_name=(node.name if node else ""))

    # ===== 重练模式：优先渲染，聚焦答题 =====
    if st.session_state.get("retry_paper"):
        _retry_mode(env, state)
        return

    # ===== 顶部统计概览（含错因分布） =====
    _stats_overview(rows, kg)

    # ===== 一键组卷重练 =====
    _retry_bar(env, rows)

    # ===== 筛选栏 =====
    _filter_bar(rows, kg)

    # ===== 错题卡片列表 =====
    st.markdown("#### 📋 错题列表")
    filtered = _apply_filter(rows, kg)

    if not filtered:
        st.info("没有符合条件的错题。")
        return

    for g in filtered:
        q = g["q"]
        node = kg.nodes.get(q.get("node_id"))
        node_name = node.name if node else q.get("node_id", "—")
        category = node.category if node else "其他"
        last = time.strftime("%m-%d %H:%M", time.localtime(g["last"]))
        stem = (q.get("stem") or "").strip()

        with st.expander(
                f"❌ {stem[:40]}{'…' if len(stem) > 40 else ''}　"
                f"[{category}] 错 {g['count']} 次 · {last} · {g['cause']}"):
            _question_card(q, node_name, g["count"], g["cause"], g["cause_hint"])


def _stats_overview(rows, kg):
    """顶部统计概览"""
    c1, c2, c3, c4 = st.columns(4)

    total = len(rows)
    total_errors = sum(g["count"] for g in rows)
    frequent = sum(1 for g in rows if g["count"] >= 2)

    # 知识点分布
    cat_counts = Counter()
    for g in rows:
        node = kg.nodes.get(g["q"].get("node_id"))
        if node:
            cat_counts[node.category] += 1
    top_cat = cat_counts.most_common(1)[0] if cat_counts else ("—", 0)

    with c1:
        st.metric("错题总数", f"{total} 道")
    with c2:
        st.metric("累计答错", f"{total_errors} 次")
    with c3:
        st.metric("高频错题", f"{frequent} 道",
                  help="错了2次及以上的题")
    with c4:
        st.metric("薄弱知识点", top_cat[0],
                  delta=f"{top_cat[1]} 道错题")

    # 知识点分布图
    if cat_counts:
        st.markdown("**知识点错题分布**")
        for cat, cnt in cat_counts.most_common():
            pct = cnt / total * 100
            st.progress(cnt / total, text=f"{cat}: {cnt} 道 ({pct:.0f}%)")

    # 错因分布图
    cause_counts = Counter(g["cause"] for g in rows)
    if cause_counts:
        st.markdown("**错因分布**")
        for cause, cnt in cause_counts.most_common():
            pct = cnt / total * 100
            st.progress(cnt / total, text=f"{cause}: {cnt} 道 ({pct:.0f}%)")


def _filter_bar(rows, kg):
    """筛选栏：按知识点/错误次数筛选"""
    # 获取所有涉及的知识点
    cats = set()
    for g in rows:
        node = kg.nodes.get(g["q"].get("node_id"))
        if node:
            cats.add(node.category)
    cats = sorted(cats)

    c1, c2 = st.columns(2)
    with c1:
        selected_cat = st.selectbox(
            "按知识点筛选",
            ["全部"] + cats,
            key="wrongbook_cat_filter"
        )
    with c2:
        sort_by = st.selectbox(
            "排序方式",
            ["最近答错", "错误次数最多", "知识点"],
            key="wrongbook_sort"
        )
    st.session_state["wrongbook_filter_cat"] = selected_cat
    st.session_state["wrongbook_sort_by"] = sort_by


def _apply_filter(rows, kg):
    """应用筛选和排序"""
    cat = st.session_state.get("wrongbook_filter_cat", "全部")
    sort_by = st.session_state.get("wrongbook_sort_by", "最近答错")

    # 筛选
    filtered = []
    for g in rows:
        node = kg.nodes.get(g["q"].get("node_id"))
        node_cat = node.category if node else "其他"
        if cat == "全部" or node_cat == cat:
            filtered.append(g)

    # 排序
    if sort_by == "最近答错":
        filtered.sort(key=lambda g: g["last"], reverse=True)
    elif sort_by == "错误次数最多":
        filtered.sort(key=lambda g: g["count"], reverse=True)
    elif sort_by == "知识点":
        filtered.sort(key=lambda g: (kg.nodes.get(g["q"].get("node_id")).category
                                      if g["q"].get("node_id") in kg.nodes else ""))
    return filtered


def _question_card(q, node_name, count, cause, hint):
    """单个错题卡片：题干 / 选项（标出正确项）/ 答案 / 解析 / 错因建议"""
    stem = (q.get("stem") or "").strip()
    st.markdown(f"**📝 题目**：{stem}")

    # options 是形如 ["A. 1", "B. 2", ...] 的列表
    opts = q.get("options") or []
    answer = str(q.get("answer") or "").strip().upper()
    for opt in opts:
        letter = str(opt).strip()[:1].upper()
        st.markdown(f"- {opt}{' ✅' if letter == answer else ''}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**✅ 正确答案**：{q.get('answer', '—')}")
    with c2:
        st.markdown(f"**📚 知识点**：{node_name}")

    if q.get("explanation"):
        st.markdown(f"**💡 解析**：{q['explanation']}")

    st.warning(f"⚠️ 错因：{cause}（累计答错 {count} 次）　建议：{hint}")


def _match_question(env, content):
    """用作答记录里的题干前缀匹配题库完整题目（含变式）

    作答记录只存了题干前 50 字，故匹配需双向前缀：长题干用
    stem.startswith(prefix)（记录是它的前缀），短题干用 prefix.startswith(stem)。
    命中多个时取题干最长者，避免短题干误配。
    """
    prefix = content[2:].strip() if content.startswith("✗ ") else content.strip()
    best = None
    for q in env["questions"]:
        for src in (q, q.get("variant") or {}):
            stem = (src.get("stem") or "").strip()
            if len(stem) >= 8 and (stem.startswith(prefix) or prefix.startswith(stem)):
                if best is None or len(stem) > len(best[2]):
                    display = dict(q)
                    for k, v in src.items():
                        if v:
                            display[k] = v
                    best = (display, src.get("stem", ""), len(stem))
    return best[0] if best else None


def _error_cause(q, profile, count, node_name=""):
    """错因归类：走共享错因模块（与脚手架靶向干预同一口径）"""
    return error_cause(q, profile, count, node_name)


def _retry_bar(env, rows):
    """一键组卷：把当前错题组成最多 MAX_RETRY 道的重练卷（优先变式题）"""
    paper = _build_paper(env, rows)
    c1, c2 = st.columns([0.62, 0.38], vertical_alignment="center")
    with c1:
        st.markdown(f"**🎯 一键组卷重练**：按错题自动生成 {len(paper)} 道练习"
                    "（优先换一个问法，避免死记答案）")
    with c2:
        if st.button(f"✍️ 生成错题重练卷（最多 {MAX_RETRY} 题）", type="primary",
                     use_container_width=True, key="retry_build"):
            if not paper:
                st.warning("暂无可用于重练的题目。")
                return
            _clear_retry()
            st.session_state["retry_paper"] = paper
            st.session_state["retry_idx"] = 0
            st.session_state["retry_answers"] = []
            flash(f"已生成 {len(paper)} 道错题重练卷，开始吧", icon="✍️")
            st.rerun()


def _build_paper(env, rows):
    """生成重练卷：高频错题优先 + 优先变式题 + 题干去重 + 最多 MAX_RETRY 道

    变式题与原题 id 相同但问法/选项不同，用它避免学生背答案。
    """
    by_id = {q.get("id"): q for q in env["questions"]}
    paper, seen = [], set()
    for g in sorted(rows, key=lambda g: (-g["count"], -g["last"])):
        if len(paper) >= MAX_RETRY:
            break
        base = by_id.get(g["q"].get("id")) or g["q"]
        item = dict(base)
        for k, v in (base.get("variant") or {}).items():
            if v:
                item[k] = v
        stem = item.get("stem")
        if stem in seen:
            continue
        seen.add(stem)
        paper.append(item)
    return paper


def _clear_retry():
    """清理重练模式的所有会话状态"""
    for k in RETRY_KEYS:
        st.session_state.pop(k, None)


def _retry_mode(env, state):
    """重练模式：一次一题，答完即时判分 + 解析并逐题落库；末尾汇总得分"""
    paper = st.session_state.get("retry_paper") or []
    idx = st.session_state.get("retry_idx", 0)
    answers = st.session_state.get("retry_answers") or []
    fb = st.session_state.get("retry_feedback")

    top1, top2 = st.columns([0.72, 0.28], vertical_alignment="center")
    with top1:
        st.markdown(f"#### ✍️ 错题重练　`{min(idx + 1, len(paper))} / {len(paper)}`")
    with top2:
        if st.button("← 退出重练", use_container_width=True, key="retry_exit"):
            _clear_retry()
            st.rerun()

    if not paper:
        st.info("重练卷为空，请回错题列表重新生成。")
        _clear_retry()
        return

    if idx >= len(paper):
        _retry_summary(paper, answers)
        return

    q = paper[idx]
    st.progress(idx / len(paper), text=f"进度 {idx} / {len(paper)} 题")
    st.markdown(f"**📝 {(q.get('stem') or '').strip()}**")
    opts = q.get("options") or []
    answer_letter = str(q.get("answer") or "").strip().upper()

    if fb is None:
        for opt in opts:
            letter = str(opt).strip()[:1].upper()
            if st.button(opt, use_container_width=True, key=f"retry_opt_{idx}_{letter}"):
                correct = letter == answer_letter
                env["orch"].log_practice(state, q, correct, letter)
                answers.append({"letter": letter, "correct": correct})
                st.session_state["retry_answers"] = answers
                st.session_state["retry_feedback"] = {"choice": letter, "correct": correct}
                st.rerun()
    else:
        choice = fb["choice"]
        for opt in opts:
            letter = str(opt).strip()[:1].upper()
            mark = " ✅" if letter == answer_letter else (" ❌" if letter == choice else "")
            st.markdown(f"- {opt}{mark}")
        if fb["correct"]:
            st.success(f"答对了！正确答案：{q.get('answer')}")
        else:
            st.error(f"答错了。你的选择 {choice}，正确答案 {q.get('answer')}")
        if q.get("explanation"):
            st.info(f"💡 解析：{q['explanation']}")
        last = idx + 1 >= len(paper)
        if st.button("查看结果 →" if last else "下一题 →", type="primary",
                     use_container_width=True, key="retry_next"):
            st.session_state["retry_idx"] = idx + 1
            st.session_state.pop("retry_feedback", None)
            st.rerun()


def _retry_summary(paper, answers):
    """重练结束：统计答对/答错数量，提供再练一次或返回列表"""
    total = len(paper)
    correct = sum(1 for a in answers if a.get("correct"))
    wrong = total - correct
    st.markdown("#### 🎯 重练结果")
    c1, c2, c3 = st.columns(3)
    c1.metric("共练题数", f"{total} 题")
    c2.metric("答对", f"{correct} 道")
    c3.metric("答错", f"{wrong} 道")
    if total:
        st.progress(correct / total, text=f"正确率 {correct / total * 100:.0f}%")
    if wrong == 0:
        st.success("🎉 全部答对，这套错题已经拿下！")
    else:
        st.info(f"还有 {wrong} 道没拿下，可以再练一次，或回错题列表看解析。")

    b1, b2 = st.columns(2)
    with b1:
        if st.button("🔁 再练一次", type="primary", use_container_width=True,
                     key="retry_again"):
            st.session_state["retry_idx"] = 0
            st.session_state["retry_answers"] = []
            st.session_state.pop("retry_feedback", None)
            flash("已重置重练卷，再来一遍", icon="🔁")
            st.rerun()
    with b2:
        if st.button("返回错题列表", use_container_width=True, key="retry_back"):
            _clear_retry()
            st.rerun()
