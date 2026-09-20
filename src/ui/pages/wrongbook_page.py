"""错题本页：自动收集所有答错的题

按题聚合：完整题干 / 选项 / 正确答案 / 解析 / 知识点 / 答错次数 / 最近时间。
数据来源是每次测验落库的作答记录（含正确性标记），无需学生手动添加。
"""
import time
from collections import Counter

import streamlit as st


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

    # ===== 顶部统计概览 =====
    _stats_overview(rows, kg)

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
                f"[{category}] 错 {g['count']} 次 · {last}"):
            _question_card(q, node_name, g["count"])


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


def _question_card(q, node_name, count):
    """单个错题卡片"""
    stem = (q.get("stem") or "").strip()

    # 题目内容
    st.markdown(f"**📝 题目**：{stem}")

    # 选项
    opts = q.get("options") or {}
    if opts:
        for letter in "ABCD":
            if letter in opts:
                is_correct = letter == q.get("answer")
                icon = " ✅" if is_correct else " ❌" if count > 0 else ""
                st.markdown(f"{letter}. {opts[letter]}{icon}")

    # 答案和解析
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**✅ 正确答案**：{q.get('answer', '—')}")
    with c2:
        st.markdown(f"**📚 知识点**：{node_name}")

    if q.get("explanation"):
        st.markdown(f"**💡 解析**：{q['explanation']}")

    # 底部标签
    st.caption(f"📊 答错 {count} 次 · 建议：重新练习这道题巩固知识点")


def _match_question(env, content):
    """用作答记录里的题干前缀匹配题库完整题目（含变式）"""
    prefix = content[2:].strip() if content.startswith("✗ ") else content.strip()
    best = None
    for q in env["questions"]:
        for src in (q, q.get("variant") or {}):
            stem = (src.get("stem") or "").strip()
            if len(stem) >= 8 and stem in prefix:
                if best is None or len(stem) > len(best[2]):
                    display = dict(q)
                    for k, v in src.items():
                        if v:
                            display[k] = v
                    best = (display, src.get("stem", ""), len(stem))
    return best[0] if best else None
