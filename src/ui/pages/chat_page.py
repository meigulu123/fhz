"""对话学习页：聊天 + 快捷指令 + 右侧信息卡（阶段/当前节点/掌握度/脚手架/路径）"""
import html
import time

import streamlit as st

from src.agent.state import (INTERVENING, PRACTICING, QUIZZING, REFLECTING,
                             TEACHING)
from src.student.diagnosis import MAX_QUESTIONS
from src.ui.components import ability_live_card, info_card, radar_figure
from src.ui.theme import MASCOT

# 快捷指令：把「求助（实时干预入口）」「推进」「结束反思」三个核心动作显性化
QUICK_ACTIONS = [
    ("help", "我不会，给点提示", "触发脚手架：系统不给答案，先反问引导"),
    ("arrow_forward", "继续", "推进讲义下一段或进入下一环节"),
    ("flag", "结束本次会话", "结束并生成学习反思，供下次开场引用"),
]
# 学习阶段追加的动作：换讲法 / 举生活例子 / 出巩固题（点击即发起对应请求）
STUDY_ACTIONS = [
    ("refresh", "换个讲法", "换一种讲解方式重讲当前知识点"),
    ("lightbulb", "举个生活例子", "用生活中的例子解释当前知识点"),
    ("fitness_center", "出 3 道巩固题", "围绕当前知识点出题练习"),
]


def chat_page():
    st.header("对话学习")
    env = st.session_state["env"]
    state = st.session_state.get("agent_state")
    if state is None:
        st.info("请先登录。")
        return

    left, right = st.columns([3, 1.1], gap="large")
    with right:
        info_card(env, state)
        _diagnosis_card(env, state)
        # 学习画像：六维雷达随作答实时生长，但不标注增减（学生自己看）
        # 摸底测验中不渲染，避免逐题泄漏对错
        if state.phase != QUIZZING and state.profile is not None:
            ability_live_card(env, state)
        if st.button("清空会话，重新诊断", use_container_width=True):
            from src.agent.state import AgentState
            new_state = AgentState(student_id=state.student_id)
            reply = env["orch"].restart_diagnosis(new_state)
            new_state.history.append({"role": "assistant", "content": reply})
            st.session_state["agent_state"] = new_state
            st.rerun()

    with left:
        _banner(env, state)
        chat_container = st.container(height=520)
        with chat_container:
            for msg in state.history:
                # 助手用品牌吉祥物头像，学生用默认头像
                avatar = str(MASCOT) if msg["role"] == "assistant" else None
                with st.chat_message(msg["role"], avatar=avatar):
                    st.markdown(msg["content"])

        _quick_actions(env, state)

        if state.current_question:
            st.caption("💡 答题方式：直接回复选项字母 A/B/C/D 即可；"
                       "也可以问「为什么」，或者卡住了就说「我不会」，我带你一步步想。")
        prompt = st.chat_input("输入你的回答或提问")
        if prompt:
            _submit(env, state, prompt)

    # 画像生成阶段的检测题：弹窗呈现，选完自动判分并弹出下一题
    pending = st.session_state.pop("quiz_answer", None)
    if pending:
        # 摸底作答走静默通道：只记轨迹、不在对话里贴题与判对错，
        # 全部答完（或提交）时才写入诊断报告
        env["orch"].quiz_answer(state, pending)
        st.rerun()
    action = st.session_state.pop("quiz_action", None)
    if action == "skip":
        env["orch"].quiz_skip(state)
        st.rerun()
    elif action == "finish":
        env["orch"].quiz_finish(state)
        st.rerun()
    edit = st.session_state.pop("quiz_edit", None)
    if edit:
        env["orch"].quiz_edit_answer(state, edit[0], edit[1])
        st.rerun()
    if state.phase == QUIZZING and state.current_question:
        _quiz_dialog(env, state)


def _diagnosis_card(env, state):
    """本次学情诊断卡：知识掌握雷达 + 覆盖/正确率/建议起点

    仅在诊断完成后出现（state.report 有值）；把诊断结论从纯文字升级为可视化卡片。
    """
    report = state.report or {}
    if not report or state.profile is None:
        return
    with st.container(border=True):
        st.markdown("**学情诊断**")
        st.plotly_chart(radar_figure(env["kg"], state.profile),
                        use_container_width=True)
        st.caption(f"覆盖 {report.get('covered', 0)} 节点 / "
                   f"{report.get('total_questions', 0)} 题，"
                   f"正确率 {report.get('accuracy', 0)}")
        st.caption(f"建议起点：{report.get('suggested') or '—'}")


def _question_by_id(env, qid):
    for q in env["questions"]:
        if q.get("id") == qid:
            return q
    return {}


# 选项文案里可能出现 _ | < > ^ { } 等 Markdown/公式敏感字符，按钮标签会被 Markdown
# 解释，导致显示异常（看起来像“乱码”）；统一转义，让选项以纯文本原样呈现。
_MD_ESCAPE = set("\\`*_{}[]|<>~$^")


def _plain_label(text: str) -> str:
    """把选项文案转义为纯文本按钮标签，避免被 Markdown/KaTeX 改写"""
    return "".join(("\\" + ch) if ch in _MD_ESCAPE else ch for ch in (text or ""))


@st.dialog("📝 学情摸底 · 检测题", width="large")
def _quiz_dialog(env, state):
    """画像生成阶段的检测题弹窗：进度 + 选项 + 上一题回看 / 跳过 / 提交

    全程不显示对错：学生只管一道道选，最后点「提交」再统一给出对错统计。
    """
    qs = state.quiz_state
    total = MAX_QUESTIONS
    n = min(qs.questions_asked + 1, total)
    st.progress(n / total, text=f"第 {n} / {total} 题")
    st.caption("系统会根据作答自动调整难度，逐题探测你会的边界，最多 12 题；"
               "若已能锁定水平边界会提前收敛。全部选完后点「提交」查看结果。")

    # ---- 提交二次确认：提交是不可逆的收尾动作，先确认一次，避免误点提前结束 ----
    if st.session_state.pop("quiz_confirm", False):
        answered_n = len(qs.answers)
        st.warning("确认提交本次摸底吗？提交后不再继续出题，直接生成画像与学习路径。")
        st.markdown(f"你已作答 **{answered_n}** 题"
                    + (f"，还有 {max(total - answered_n, 0)} 题没作答"
                       if answered_n < total else "")
                    + "。")
        cy, cn = st.columns(2)
        if cy.button("确认提交", type="primary", use_container_width=True,
                     key="quiz_confirm_yes"):
            st.session_state["quiz_action"] = "finish"
            st.rerun()
        if cn.button("继续答题", use_container_width=True, key="quiz_confirm_no"):
            st.rerun()
        return

    # ---- 上一题回看（可修改作答：自适应测验不回退难度；全程不判对错）----
    answered = qs.answers
    rev = st.session_state.get("quiz_review") or 0
    if rev:
        rev = min(rev, len(answered))
        if rev <= 0:
            st.session_state["quiz_review"] = None
            st.rerun()
        index = len(answered) - rev
        entry = answered[index]
        qid = entry[1]
        choice = (entry[3] if len(entry) > 3 else "") or ""
        old = _question_by_id(env, qid)
        st.info("回看说明：这里可以翻看并修改之前每题的选择（不判对错）；"
                "自适应测验的难度不会回退，改完直接继续往后答就行。")
        st.markdown(f"**第 {index + 1} 题（回看 · 可修改答案）**")
        if old.get("options"):
            st.markdown(old.get("stem", ""))
            cur = choice.strip().upper()[:1]
            for i, opt in enumerate(old.get("options", [])):
                picked = bool(cur) and opt.strip().upper().startswith(cur)
                if st.button(("✅ " if picked else "") + _plain_label(opt),
                             key=f"edit_opt_{qid}_{i}", use_container_width=True):
                    st.session_state["quiz_edit"] = (index, opt)
                    st.rerun()
        else:
            # 题面已不在当前题库（如题库更新）：回显当时的选择，不留一个空白的回看页
            st.info(f"这道题的题面已不在当前题库中，你当时的作答是：{choice or '（未作答）'}")
        st.caption("点击另一个选项即可修改本题作答（不判对错）；改完可继续往前/往后翻看。")
        c1, c2, c3 = st.columns(3)
        if c1.button("← 更早一题", key="rev_older", use_container_width=True,
                     disabled=rev >= len(answered)):
            st.session_state["quiz_review"] = rev + 1
            st.rerun()
        if c2.button("下一题 →", key="rev_newer", use_container_width=True):
            # rev 减到 0 表示「回到当前题」，退出回看视图（不能再往前翻）
            nxt = rev - 1
            st.session_state["quiz_review"] = nxt if nxt > 0 else None
            st.rerun()
        if c3.button("返回当前题", key="rev_back", use_container_width=True):
            st.session_state["quiz_review"] = None
            st.rerun()
        return

    # ---- 当前题：选项即作答 ----
    q = state.current_question or {}
    options = q.get("options") or []
    if not options:
        # 兜底：万一拿到空题（题库耗尽/状态异常），不留一个没有任何选项的空弹窗
        st.warning("暂时没有可用的检测题了，请点「提交」结束本次摸底。")
    else:
        st.markdown(f"**{q.get('stem', '')}**")
        for i, opt in enumerate(options):
            if st.button(_plain_label(opt), key=f"quiz_opt_{q.get('id', '')}_{i}",
                         use_container_width=True):
                st.session_state["quiz_answer"] = opt
                st.session_state["quiz_review"] = None
                st.rerun()
    st.divider()
    b1, b2, b3 = st.columns(3)
    if b1.button("← 上一题", key="quiz_prev", use_container_width=True, disabled=not answered,
                 help="回看上一题的作答结果（自适应难度不回退）"):
        st.session_state["quiz_review"] = 1
        st.rerun()
    if b2.button("跳过本题", key="quiz_skip", use_container_width=True,
                 help="不计分、不计入掌握度评估，换一道题继续"):
        st.session_state["quiz_action"] = "skip"
        st.rerun()
    # 提交为不可逆收尾动作：用主色按钮强调、点后弹二次确认，避免误点提前结束
    if b3.button("✅ 提交并生成报告", type="primary", key="quiz_finish",
                 use_container_width=True,
                 help="提交本次摸底作答，生成画像与学习路径，并给出对错统计"):
        st.session_state["quiz_confirm"] = True
        st.rerun()


def _submit(env, state, text):
    """向编排器提交输入；未预期异常不崩页面，保留状态并友好提示（演示安全网）

    智能体调用是同步阻塞的，因此用 st.spinner 在调用期间真实渲染「正在思考」，
    学生不会面对一个点完毫无反馈的界面。
    """
    try:
        with st.spinner("🤔 正在思考..."):
            env["orch"].handle(state, text)
    except Exception as exc:  # noqa: BLE001 —— 兜底：任何未预期错误都让应用存活
        st.error(f"系统遇到一点问题，已为你保留当前进度，请重试。\n\n`{exc}`")
        return
    st.rerun()


def _quick_actions(env, state):
    """上下文动作条：按当前相位动态给动作，点击即向智能体发送对应文本

    学习阶段（教学/干预/练习）在「继续」前后插入学习类动作，形成
    「换讲法·举例子 → 出巩固题 → 继续 → 求助」的顺畅动线；每行最多 3 个。
    """
    if state.phase in (TEACHING, INTERVENING, PRACTICING):
        actions = [QUICK_ACTIONS[0], *STUDY_ACTIONS, QUICK_ACTIONS[1], QUICK_ACTIONS[2]]
    else:
        actions = list(QUICK_ACTIONS)
    disabled = state.phase == REFLECTING
    for i in range(0, len(actions), 3):
        row = actions[i:i + 3]
        cols = st.columns(len(row))
        for col, (icon, label, help_text) in zip(cols, row):
            with col:
                if st.button(f":material/{icon}: {label}", use_container_width=True,
                             help=help_text, key=f"quick_{label}",
                             disabled=disabled):
                    _submit(env, state, label)


def _banner(env, state):
    """对话区顶部横幅：学生名 + 当前相位 + 当前知识点"""
    payload = env["orch"]._payload(state)
    name = html.escape((state.profile.name if state.profile else "") or "同学")
    node = html.escape(payload.get("node_name") or "尚未开始")
    phase = html.escape(payload.get("phase_label") or "")
    st.markdown(
        f'<div class="chat-banner">'
        f'<div class="cb-left"><span class="cb-name">{name}</span>'
        f'<span class="cb-phase">{phase}</span></div>'
        f'<div class="cb-right">当前知识点：{node}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
