"""Agent 编排器：感知→规划→行动→记忆 主循环

单进程同步状态机 IDLE→DIAGNOSING→QUIZZING→TEACHING⇄INTERVENING→REFLECTING。
handle_message 五步：感知(意图分类+记忆) → 规划(FSM 分派) → 行动(结构动作) →
记忆(落库+快照) → 返回 (reply, ui_payload)。

双通道设计贯穿始终：发给 LLM 的消息同时携带标记（Mock 路由键）与原始数据
（真实 LLM 素材），Mock 与真实模式接口契约完全一致。
"""
from __future__ import annotations

import json
import re
import time

from src.agent.state import (AgentState, IDLE, DIAGNOSING, QUIZZING, TEACHING,
                             INTERVENING, REFLECTING, PRACTICING, PHASE_LABELS)
from src.memory.reflection import maybe_reflect
from src.memory.retrieve import build_context, retrieve_node, stats_json
from src.path.pacing import pace_params
from src.student.diagnosis import AdaptiveQuiz, build_report
from src.student.profile import StudentProfile, init_mastery
from src.student.update import apply_forgetting, mastery_update
from src.tutor.scaffold import LEVELS, Scaffolder, detect_stuck
from src.tutor.teach import segment_count, split_segments, teach_segment

# ---------- 对话诊断 ----------
DIAG_QUESTIONS = [
    "先认识一下！怎么称呼你？（说个昵称就可以）",
    "你是哪个学校、什么专业的？这样我能配合你的学习节奏。",
    "之前学过哪些数学或机器学习基础？比如高等数学、线性代数、概率统计……"
    "没学过也没关系，直说就行。",
    "这次想重点攻克什么方向？比如深度学习、经典算法、面试求职、期末备考……",
]

# 先验映射：关键词 → 节点先验（0.5 表示"学过一点"，1.0 表示"学过"）
PRIOR_RULES = [
    (["高等数学", "高数", "微积分"], {"m03": 1.0}),
    (["线性代数", "线代"], {"m01": 1.0, "m02": 1.0}),
    (["概率", "统计"], {"m04": 1.0, "m05": 1.0}),
    (["机器学习", "ml", "深度学习入门"], {"b01": 0.5}),
]
VAGUE_WORDS = ("学过一点", "了解一点", "有点基础", "接触过", "知道一点")

# 目标关键词映射（关键词取自 KG 节点 keywords，保证 goal_sim 有效命中）
GOAL_RULES = [
    (["深度学习", "神经网络"], ["多层感知机", "反向传播", "激活函数", "卷积", "池化",
                          "RNN", "LSTM", "Transformer", "自注意力", "GAN", "词嵌入",
                          "预训练", "微调", "大模型"]),
    (["面试", "求职", "找工作", "秋招"], ["集成学习", "特征工程", "过拟合", "超参数",
                                    "部署", "交叉验证", "精确率", "召回率",
                                    "决策树", "逻辑回归"]),
    (["考试", "期末", "测验"], ["线性回归", "决策树", "支持向量机", "朴素贝叶斯",
                          "逻辑回归", "K近邻", "聚类"]),
    (["比赛", "竞赛", "项目", "kaggle"], ["集成学习", "特征工程", "模型融合",
                                    "数据增强", "交叉验证", "超参数"]),
]


class Orchestrator:
    """会话编排器。构造参数：kg、llm、mem、planner、questions（题库列表）。"""

    def __init__(self, kg, llm, mem, planner, questions):
        self.kg = kg
        self.llm = llm
        self.mem = mem
        self.planner = planner
        self.quiz = AdaptiveQuiz(kg, questions)
        self.scaffolder = Scaffolder(llm, questions, mem)
        self.qs_by_node = {}
        for q in questions:
            self.qs_by_node.setdefault(q["node_id"], []).append(q)

    # ==================== 会话生命周期 ====================
    def start_session(self, state: AgentState) -> tuple:
        """登录/开新会话：老学生恢复画像+遗忘衰减+记忆开场白+直接出路径；
        新学生进入 IDLE 等待对话诊断。返回 (reply, payload)。

        记忆开场白只在「真正学过内容」时给出；仅完成诊断、尚未学习任何知识点
        的学生视为初次使用，不给「欢迎回来」/回顾，避免引用从未学过的知识点。
        """
        profile = self.mem.restore_profile(state.student_id)
        if profile is None:
            state.profile = StudentProfile(student_id=state.student_id)
            state.phase = DIAGNOSING
            state.diagnosis_step = 0
            reply = self._greeting(None) + "\n\n" + DIAG_QUESTIONS[0]
            return reply, self._payload(state)
        state.profile = profile
        now = time.time()
        for nid, ts in list(profile.last_seen.items()):
            days = (now - ts) / 86400.0
            if days >= 1.0:
                apply_forgetting(profile, nid, days)
        state.session_id = self.mem.start_session(state.student_id)
        if not self.mem.has_study_history(state.student_id):
            reply = self._first_learn_greeting(profile.name)
        else:
            preview = self.mem.last_reflection(state.student_id) or {}
            ctx = build_context(self.mem, state.student_id,
                                preview.get("next_session_preview", ""), preview)
            reply = self._greeting(ctx or preview.get("next_session_preview", ""))
        self._new_batch(state)
        if not state.plan.get("items"):
            return (reply + "\n\n你的知识点掌握得都很扎实，可以自由选择想学的内容。",
                    self._payload(state))
        begin = self._begin_node(state, state.plan["items"][0])
        return reply + "\n\n" + begin, self._payload(state)

    def restart_diagnosis(self, state: AgentState) -> str:
        """清空会话重新诊断：新建空白画像并进入诊断，返回开场白（不恢复旧画像）"""
        state.profile = StudentProfile(student_id=state.student_id)
        state.phase = DIAGNOSING
        state.diagnosis_step = 0
        return self._greeting(None) + "\n\n" + DIAG_QUESTIONS[0]

    # ==================== 主入口 ====================
    def handle(self, state: AgentState, text: str) -> tuple:
        text = (text or "").strip()
        if not text:
            return "我在的，想说什么都可以，比如聊聊学习进度或你卡住的地方。", self._payload(state)
        state.interaction_count += 1
        intent = self._classify(text)
        try:
            state.memory_ctx = build_context(self.mem, state.student_id, text,
                                             self.mem.last_reflection(state.student_id))
        except Exception:  # noqa: BLE001 —— 记忆检索失败不阻断主流程
            state.memory_ctx = ""
        kind = intent.get("intent", "answer")
        dispatch = {IDLE: self._idle_turn, DIAGNOSING: self._diagnose_turn,
                    QUIZZING: self._quiz_turn, TEACHING: self._teach_turn,
                    INTERVENING: self._intervene_turn, PRACTICING: self._practice_turn}
        if kind == "end_session" and state.phase not in (IDLE, REFLECTING, PRACTICING):
            reply, payload = self._end_session(state)
        elif state.phase == REFLECTING:
            state.reset_for_new_session()
            reply, payload = self.start_session(state)
        elif kind == "practice" and state.phase != PRACTICING:
            reply, payload = self._start_practice(state, text)
        elif kind == "question":
            ans = self._answer_question(state, text)
            reply, payload = ans if ans is not None else \
                dispatch.get(state.phase, self._teach_turn)(state, text, kind)
        else:
            reply, payload = dispatch.get(state.phase, self._teach_turn)(state, text, kind)
        state.history.append({"role": "user", "content": text})
        state.history.append({"role": "assistant", "content": reply})
        return reply, payload

    # ==================== 感知 ====================
    def _classify(self, text: str) -> dict:
        """意图分类：LLM（Mock 规则/真实模型），失败离线降级"""
        messages = [
            {"role": "system",
             "content": "[TPL:intent]\n你是伴学智能体的意图识别模块。根据学生输入输出 JSON："
                        "{\"intent\": \"answer|confusion|goal_change|question|practice|end_session|other\","
                        " \"choice\": \"A/B/C/D（若为答题输入，否则省略）\", \"confidence\": 0~1}。"},
            {"role": "user", "content": text},
        ]
        try:
            result = self.llm.chat_json(messages)
            if isinstance(result, dict) and result.get("intent"):
                return result
        except Exception:  # noqa: BLE001 —— 真实 LLM 故障时离线降级
            pass
        from src.llm.mock import MockLLM
        return MockLLM._classify_intent(text)

    @staticmethod
    def _choice(text: str, intent: dict) -> str | None:
        m = re.search(r"[ABCD]", text, re.I)
        if m:
            return m.group(0).upper()
        c = intent.get("choice") if isinstance(intent, dict) else None
        return str(c).upper()[:1] if c else None

    def _greeting(self, preview: str | None) -> str:
        # 记忆上下文含 [kind/node] 路由标记，直接塞进 [preview=] 会让 Mock 的正则
        # 提取在嵌套的 ] 处截断（出现「欢迎回来！[quiz/m01」）。剥掉标记只留纯文本。
        preview = re.sub(r"\[[^\]]*\]", "", preview or "").strip()
        messages = [
            {"role": "system",
             "content": "[TPL:greeting]\n你是伴学智能体知途，用亲切的语气和学生打招呼。"},
            {"role": "user", "content": f"[preview={preview}]"},
        ]
        # 开场白走本地快速通道：确定性问候，不等真实推理模型长考，登录才能秒进
        return self.llm.chat_local(messages)

    def _first_learn_greeting(self, name: str) -> str:
        """已完成诊断但尚未开始学习的学生的开场白（不引用任何未学知识点）"""
        messages = [
            {"role": "system",
             "content": "[TPL:first_learn]\n你是伴学智能体知途，用亲切的语气向已完成诊断"
                        "的学生打招呼，鼓励他开始个性化学习。"},
            {"role": "user", "content": f"[name={name or '同学'}]"},
        ]
        return self.llm.chat_local(messages)

    # ==================== 知识问答（RAG） ====================
    def _match_node(self, text: str) -> str | None:
        """检索与问题最相关的知识点节点；无命中返回 None"""
        hits = retrieve_node(self.kg, text, top_k=1)
        return hits[0] if hits else None

    @staticmethod
    def _lecture_excerpt(node, max_chars: int = 400) -> str:
        """取讲义正文节选（跳过 [ASK:] 提问位，累计 ≤max_chars）"""
        parts = []
        total = 0
        if node.lecture:
            for block in node.lecture.split("\n\n"):
                block = block.strip()
                if not block or block.startswith("[ASK:]"):
                    continue
                parts.append(block)
                total += len(block)
                if total >= max_chars:
                    break
        return "\n\n".join(parts)

    @staticmethod
    def _profile_ctx(state) -> str:
        """拼学生画像上下文（真实 LLM 个性化用；Mock 只读 [node=]，忽略此段）"""
        p = getattr(state, "profile", None)
        if p is None:
            return ""
        bits = []
        if getattr(p, "name", ""):
            bits.append(f"称呼：{p.name}")
        if getattr(p, "major", ""):
            bits.append(f"专业：{p.major}")
        goals = getattr(p, "goals", None) or []
        if goals:
            bits.append(f"学习目标：{'、'.join(str(g) for g in goals[:2])}")
        if getattr(p, "prior", None):
            bits.append(f"已有基础：{len(p.prior)} 个知识点")
        return "【学生画像】" + "；".join(bits) if bits else ""

    def _answer_question(self, state: AgentState, text: str):
        """知识问答：检索相关知识点（支持跨知识点对比）并生成解答；不命中返回 None。

        双通道：真实 LLM 读【学生画像】+ 多节点【知识库】生成自然解答；
        Mock 只读 [node=] 标记，返回名称概述 + 讲义首段（离线兜底不变）。
        """
        hits = retrieve_node(self.kg, text, top_k=3)
        if not hits:
            return None
        nodes = [self.kg.nodes[n] for n in hits]
        per = 300 if len(nodes) > 1 else 500
        kb_blocks = [
            f"【知识点{i + 1}】{n.name}\n概述：{n.summary}\n讲义节选：\n"
            f"{self._lecture_excerpt(n, max_chars=per)}"
            for i, n in enumerate(nodes)
        ]
        kb = "\n\n".join(kb_blocks)
        messages = [
            {"role": "system",
             "content": "[TPL:qa]\n你是知途伴学，一位亲切耐心的 AI 伴学导师，善于用通俗语言"
                        "和生动类比把知识讲明白。回答学生问题时：\n"
                        "1. 先直接回答核心问题，再用一个贴近生活的类比帮助理解；\n"
                        "2. 紧扣给定知识库、不编造，知识库未覆盖的内容如实说明；\n"
                        "3. 结合学生画像调整深浅：基础弱的少用术语、多打比方，基础好的可适当深入；\n"
                        "4. 篇幅 200 字左右，结尾抛一个延伸问题或提示，鼓励继续追问。"},
            {"role": "user",
             "content": f"[node={hits[0]}]\n{self._profile_ctx(state)}\n【知识库】\n{kb}"
                        f"\n\n【学生问题】{text}"},
        ]
        answer = self.llm.chat(messages)
        if state.session_id:
            self.mem.log_interaction(state.session_id, state.student_id, "qa",
                                     hits[0], text[:60])
        label = "、".join(n.name for n in nodes[:2])
        if len(nodes) > 2:
            label += " 等"
        return f"关于「{label}」：\n\n{answer}", self._payload(state)

    # ==================== 自主练习（主动选题） ====================
    def _start_practice(self, state, text, keep_resume=False):
        """学生主动「练习 XX」：检索知识点并出该节点的题，进入 PRACTICING 相位"""
        if state.phase in (DIAGNOSING, QUIZZING, INTERVENING):
            msg = ("先把当前环节完成再练吧～现在正在"
                   f"{PHASE_LABELS.get(state.phase, '进行中')}，完成后再来说「练习 XX」。")
            return msg, self._payload(state)
        nid = self._match_node(text)
        if nid is None:
            return ("我没找到这个知识点，换个说法试试？比如「练习 线性回归」。"
                    "也可以先问「什么是 XX」了解它。"), self._payload(state)
        q = None
        for qq in self.qs_by_node.get(nid, []):
            if qq["id"] not in state.used_qids:
                q = qq
                break
        if q is None:
            return f"「{self.kg.nodes[nid].name}」的练习题都做过了，换个知识点吧。", self._payload(state)
        if not keep_resume:
            state.resume_phase = state.phase
        state.phase = PRACTICING
        state.practice_node = nid
        state.current_question = q
        state.used_qids.append(q["id"])
        return f"好的，来练「{self.kg.nodes[nid].name}」：\n\n" + self._fmt_question(q), self._payload(state)

    def _practice_turn(self, state, text, intent):
        """练习相位：答题 → 判定 + 解析 → 出下一题；题完/退出词 → 恢复原相位"""
        if intent == "end_session" or any(w in text for w in
                                          ("回到学习", "继续学习", "不练了", "退出练习")):
            return self._exit_practice(state, "好的，练习先到这里，回到学习。")
        if intent == "practice":
            return self._start_practice(state, text, keep_resume=True)
        q = state.current_question
        choice = self._choice(text, intent)
        if choice is None:
            return ("回复选项字母 A/B/C/D 即可；想换知识点就说「练习 XX」，"
                    "想结束就说「结束练习」。"), self._payload(state)
        correct = choice == q["answer"]
        theta = mastery_update(state.profile, self.kg, state.practice_node,
                               correct, kind="practice")
        self._log_attempt(state, q, correct, theta, node_id=state.practice_node)
        state.last_results.append(correct)
        if len(state.last_results) > 8:
            state.last_results.pop(0)
        fb = self._answer_explanation(q, correct)
        nq = None
        for qq in self.qs_by_node.get(state.practice_node, []):
            if qq["id"] not in state.used_qids:
                nq = qq
                break
        if nq is None:
            node = self.kg.nodes[state.practice_node]
            done_msg = (f"「{node.name}」的题都练完啦！可以说「练习 XX」换个知识点，"
                        "或「结束练习」回到学习。")
            return self._exit_practice(state, fb + "\n\n" + done_msg)
        state.current_question = nq
        state.used_qids.append(nq["id"])
        return fb + "\n\n" + self._fmt_question(nq), self._payload(state)

    def _exit_practice(self, state, msg):
        """退出练习：恢复进入前的相位，清空练习状态"""
        state.phase = state.resume_phase or IDLE
        state.resume_phase = ""
        state.practice_node = ""
        state.current_question = None
        return msg, self._payload(state)

    # ==================== 各相位 ====================
    def _idle_turn(self, state, text, intent):
        if state.profile is None:
            state.profile = StudentProfile(student_id=state.student_id)
        state.phase = DIAGNOSING
        state.diagnosis_step = 0
        return DIAG_QUESTIONS[0], self._payload(state)

    def _diagnose_turn(self, state, text, intent):
        step = state.diagnosis_step
        profile = state.profile
        if step == 0:
            profile.name = self._parse_name(text)
            reply = f"你好，{profile.name}！" + DIAG_QUESTIONS[1]
        elif step == 1:
            profile.major = text.strip()[:30]
            reply = DIAG_QUESTIONS[2]
        elif step == 2:
            profile.prior.update(self._parse_prior(text))
            if "自学" in text:
                profile.style_tags.append("自学型")
            reply = DIAG_QUESTIONS[3]
        else:
            return self._diagnosis_done(state, text)
        state.diagnosis_step += 1
        return reply, self._payload(state)

    def _diagnosis_done(self, state, text):
        profile = state.profile
        goals = text.strip()[:50]
        profile.goals = [goals] if goals else []
        profile.goal_keywords = self._parse_goals(text)
        init_mastery(profile, self.kg)
        self.mem.save_student(profile)
        state.session_id = self.mem.start_session(state.student_id)
        self.mem.log_interaction(state.session_id, state.student_id, "message", "",
                                 f"对话诊断完成 prior={json.dumps(profile.prior, ensure_ascii=False)} "
                                 f"goals={json.dumps(profile.goal_keywords, ensure_ascii=False)}")
        state.phase = QUIZZING
        state.quiz_state = self.quiz.new_state()
        q = self.quiz.next_question(state.quiz_state)
        state.current_question = q
        state.used_qids.append(q["id"])
        reply = ("好的，你的情况我记下了！接下来做几道题，看看你的真实水平分布——"
                 "答错没关系，题目会自动跟着你的表现调整难度。\n\n"
                 + self._fmt_question(q))
        return reply, self._payload(state)

    def _quiz_turn(self, state, text, intent):
        qs = state.quiz_state
        q = state.current_question
        choice = self._choice(text, intent)
        if choice is None:
            return ("这是水平摸底测验，尽量凭感觉选一个（回复 A/B/C/D 即可），"
                    "实在不确定就选最像的。"), self._payload(state)
        correct = choice == q["answer"]
        theta = mastery_update(state.profile, self.kg, qs.current_node, correct, kind="quiz")
        self._log_attempt(state, q, correct, theta)
        self.quiz.record(qs, q, correct)
        state.last_results.append(correct)
        if len(state.last_results) > 8:
            state.last_results.pop(0)
        fb = self._answer_explanation(q, correct)
        if qs.finished:
            reply, payload = self._quiz_finished(state)
            return fb + "\n\n" + reply, payload
        nq = self.quiz.next_question(qs)
        if nq.get("id") is None:
            reply, payload = self._quiz_finished(state)
            return fb + "\n\n" + reply, payload
        state.current_question = nq
        state.used_qids.append(nq["id"])
        return fb + "\n\n" + self._fmt_question(nq), self._payload(state)

    @staticmethod
    def _answer_explanation(q, correct):
        """答题后的权威反馈：判定 + 正确答案 + 解析（直接取题库，不调 LLM）"""
        verdict = "✅ 回答正确" if correct else "❌ 回答错误"
        expl = (q.get("explanation") or "").strip()
        return (f"{verdict}！正确答案：{q.get('answer', '')}\n\n"
                f"解析：{expl or '（暂无解析）'}")

    def _quiz_finished(self, state):
        profile = state.profile
        report = build_report(profile, self.kg, self.planner, state.quiz_state)
        stuck = sum(1 for c in state.last_results if not c)
        params = pace_params(report["accuracy"], stuck)
        state.plan = self.planner.plan(profile, batch=params["batch"])
        state.plan_idx = 0
        state.report = report
        self.mem.save_plan(state.session_id, state.student_id, params["pace"],
                           state.plan["band"], state.plan)
        self.mem.log_interaction(state.session_id, state.student_id, "report", "",
                                 "学情诊断完成", report)
        stats = stats_json(profile, self.kg, report=report, done_nodes=state.done_nodes)
        messages = [
            {"role": "system",
             "content": "[TPL:diag_report]\n你是学情诊断报告助手，基于学情统计生成一段"
                        "诊断报告（掌握情况/ZPD 带/建议起点）。"},
            {"role": "user", "content": f"[stats_json={json.dumps(stats, ensure_ascii=False)}]"},
        ]
        diag = self.llm.chat(messages)
        if not state.plan["items"]:
            state.phase = TEACHING
            state.current_node = ""
            return diag + "\n\n你的知识点掌握得都很好，可以自由选择想学的内容。", self._payload(state)
        begin = self._begin_node(state, state.plan["items"][0])
        return diag + "\n\n" + begin, self._payload(state)

    def _teach_turn(self, state, text, intent):
        profile = state.profile
        if intent == "goal_change":
            profile.goals = [text.strip()[:50]]
            profile.goal_keywords = self._parse_goals(text)
            return self._new_batch(state, "已按新目标重新规划学习路径：\n\n")
        if state.plan_idx >= len(state.plan.get("items", [])):
            return self._new_batch(state)
        if state.current_question is not None:
            return self._grade_attempt(state, text, intent, in_scaffold=False)
        # 讲义讲解中：卡住 → 脚手架
        if intent == "confusion" or detect_stuck(state.scaffold, intent, text, state.last_results):
            return self._engage_scaffold(state, "没关系，我们放慢一点，我来带你一步步想。")
        # 学生回应 [ASK:] 提问 → 软证据 + 推进分段
        if intent in ("answer", "question"):
            theta = mastery_update(profile, self.kg, state.current_node, 0.5, kind="dialog")
            self.mem.log_interaction(state.session_id, state.student_id, "message",
                                     state.current_node, f"回应讲义提问：{text[:60]}",
                                     {"theta": round(theta, 3)})
            self.mem.snapshot_mastery(state.student_id, state.current_node, theta,
                                      profile.evidence_count[state.current_node])
        node = self.kg.nodes[state.current_node]
        segs = split_segments(node.lecture or "")
        state.lecture_para += 1
        if state.lecture_para < len(segs):
            seg = teach_segment(self.llm, state.current_node, state.lecture_para, segs[state.lecture_para])
            self.mem.log_interaction(state.session_id, state.student_id, "teach",
                                     state.current_node, f"讲义第{state.lecture_para + 1}段")
            return "好的，我们继续往下看：\n\n" + seg, self._payload(state)
        return self._present_quiz_question(state)

    def _intervene_turn(self, state, text, intent):
        return self._grade_attempt(state, text, intent, in_scaffold=True)

    # ==================== 作答判定与脚手架 ====================
    def _grade_attempt(self, state, text, intent, in_scaffold):
        q = state.current_question
        choice = self._choice(text, intent)
        if choice is None:
            if in_scaffold:
                r = self.scaffolder.on_help(state.scaffold)
                if r.get("replan"):
                    return self._replan(state)
                self._log_hint(state, r["level"])
                return r["text"] or "再想想，从题干给了哪些条件入手？", self._payload(state)
            if intent == "confusion":
                return self._engage_scaffold(state, "先不急着看答案，我们一起想想。")
            return ("回复选项字母 A/B/C/D 就可以啦；"
                    "哪里不清楚也可以直接告诉我。"), self._payload(state)
        correct = choice == q["answer"]
        theta = mastery_update(state.profile, self.kg, state.current_node, correct, kind="quiz")
        self._log_attempt(state, q, correct, theta)
        state.last_results.append(correct)
        if len(state.last_results) > 8:
            state.last_results.pop(0)
        if correct:
            if in_scaffold:
                self.scaffolder.on_correct(state.scaffold, state.profile)
            return self._finish_node(state, "回答正确！思路很清晰。")
        if in_scaffold:
            r = self.scaffolder.on_wrong(state.scaffold)
            if r.get("replan"):
                if q.get("variant") and not state.scaffold.variant_tried:
                    state.scaffold.variant_tried = True
                    state.current_question = q["variant"]
                    return ("这道题确实有难度。换个形式检验一下是否真正理解了"
                            "（回复选项字母）：\n\n" + self._fmt_question(q["variant"]),
                            self._payload(state))
                return self._replan(state)
            self._log_hint(state, r["level"])
            return r["text"] or "换个角度：题干给出了哪些已知条件？", self._payload(state)
        return self._engage_scaffold(state, "答错了也没关系，先不公布答案——我们一起来找思路：")

    def _engage_scaffold(self, state, preamble):
        q = self._next_question_for(state)
        if q is None:
            return ("我们回到讲义：回看刚才的 [ASK:] 提问，用自己的话说说你现在的想法，"
                    "我再帮你往下理。"), self._payload(state)
        state.current_question = q
        state.used_qids.append(q["id"])
        r = self.scaffolder.engage(state.scaffold, q["id"], state.current_node)
        state.phase = INTERVENING
        self._log_hint(state, r["level"])
        return preamble + "\n\n" + (r["text"] or "先想一想，这题在考哪个知识点？"), self._payload(state)

    def _finish_node(self, state, praise):
        state.done_nodes.append(state.current_node)
        self.mem.log_interaction(state.session_id, state.student_id, "teach",
                                 state.current_node, "知识点完成")
        maybe_reflect(self.mem, self.llm, self.kg, state.profile, state.session_id,
                      "node_done", state.interaction_count, state.report, state.done_nodes)
        state.current_question = None
        state.lecture_para = 0
        state.plan_idx += 1
        items = state.plan.get("items", [])
        if state.plan_idx < len(items):
            begin = self._begin_node(state, items[state.plan_idx])
            return praise + " 🎉\n\n" + begin, self._payload(state)
        state.current_node = ""
        state.phase = TEACHING
        reply = (praise + " 🎉\n\n这一批学习计划全部完成！"
                 "你可以继续说「继续」，我给你规划下一批；"
                 "或者今天先到这里，说「结束」即可，我会把学习记录保存好。")
        return reply, self._payload(state)

    def _begin_node(self, state, item) -> str:
        state.current_node = item["node_id"]
        state.lecture_para = 0
        state.current_question = None
        state.phase = TEACHING
        node = self.kg.nodes[item["node_id"]]
        segs = split_segments(node.lecture or "")
        seg0 = segs[0] if segs else ""
        seg = teach_segment(self.llm, item["node_id"], 0, seg0)
        self.mem.log_interaction(state.session_id, state.student_id, "teach",
                                 item["node_id"], "开始学习「" + node.name + "」")
        tier = "复习巩固" if item.get("tier") == "复习" else "正好落在你的最近发展区内"
        return f"我们从「{node.name}」开始（难度 {node.difficulty:.2f}，{tier}）。\n\n" + seg

    def _present_quiz_question(self, state):
        q = self._next_question_for(state)
        if q is None:
            return self._finish_node(state, "这个知识点你已经练完啦")[0], self._payload(state)
        state.current_question = q
        state.used_qids.append(q["id"])
        reply = f"讲义部分到这里，来做一道巩固题（回复选项字母即可）：\n\n" + self._fmt_question(q)
        return reply, self._payload(state)

    def _next_question_for(self, state):
        for q in self.qs_by_node.get(state.current_node, []):
            if q["id"] not in state.used_qids:
                return q
        return None

    # ==================== 重规划与批次 ====================
    def _replan(self, state, trigger="stuck_l3"):
        stats = stats_json(state.profile, self.kg, report=state.report, done_nodes=state.done_nodes)
        messages = [
            {"role": "system",
             "content": "[TPL:replan]\n你是学习路径规划助手。基于学情统计输出 JSON："
                        "{\"action\": \"review_prereq|reorder\", \"node_id\": \"...\","
                        " \"reason\": \"...\", \"new_order\": [\"...\"]}。"},
            {"role": "user",
             "content": f"[trigger={trigger}][node={state.current_node}]"
                        f"[memory={state.memory_ctx}]"
                        f"[stats_json={json.dumps(stats, ensure_ascii=False)}]"},
        ]
        try:
            action = self.llm.chat_json(messages)
        except Exception:  # noqa: BLE001 —— 离线降级
            action = self.planner.replan_rules(state.profile, trigger, state.current_node)
        action = action or {}
        new_node = action.get("node_id") or state.current_node
        if new_node not in self.kg.nodes:
            new_node = state.current_node
        items = state.plan.get("items", [])
        if action.get("action") == "review_prereq" and new_node != state.current_node:
            if not any(i["node_id"] == new_node for i in items[:state.plan_idx + 1]):
                items.insert(state.plan_idx, self._make_item(state, new_node, "复习"))
        self.mem.save_plan(state.session_id, state.student_id, 0.5,
                           state.plan.get("band", {}), state.plan)
        maybe_reflect(self.mem, self.llm, self.kg, state.profile, state.session_id,
                      "stuck_l3", state.interaction_count, state.report, state.done_nodes)
        state.scaffold.reset()
        state.current_question = None
        state.lecture_para = 0
        begin = self._begin_node(state, self._make_item(state, new_node, "复习"))
        return (action.get("reason", "为你重新调整了学习路径") + "\n\n" + begin), self._payload(state)

    def _new_batch(self, state, prefix=""):
        stuck = sum(1 for c in state.last_results if not c)
        params = pace_params((state.report or {}).get("accuracy"), stuck)
        state.plan = self.planner.plan(state.profile, batch=params["batch"])
        state.plan_idx = 0
        state.current_node = ""
        state.current_question = None
        state.lecture_para = 0
        self.mem.save_plan(state.session_id, state.student_id, params["pace"],
                           state.plan["band"], state.plan)
        if not state.plan["items"]:
            return "你的知识点掌握得都很扎实，可以自由选择想学的内容。", self._payload(state)
        begin = self._begin_node(state, state.plan["items"][0])
        return prefix + begin, self._payload(state)

    def _make_item(self, state, node_id, tier):
        node = self.kg.nodes[node_id]
        return {"node_id": node_id, "name": node.name, "score": 0.0, "tier": tier,
                "difficulty": node.difficulty,
                "mastery": round(state.profile.mastery.get(node_id, 0.0), 3),
                "reason": "重规划：回补先修知识点"}

    # ==================== 会话结束 ====================
    def _end_session(self, state):
        state.phase = REFLECTING
        reflection = maybe_reflect(self.mem, self.llm, self.kg, state.profile,
                                   state.session_id, "session_end",
                                   state.interaction_count, state.report, state.done_nodes)
        summary = reflection.get("progress_summary", "") if reflection else ""
        self.mem.end_session(state.session_id, summary)
        reply = ("今天的学习到这里！" + (f"\n\n{summary}" if summary else "") +
                 "\n\n你的学习记录我都保存好了，下次回来我会记得你。👋"
                 "（随时说「继续」开始新的学习）")
        return reply, self._payload(state)

    # ==================== 落库 ====================
    def _log_attempt(self, state, q, correct, theta, node_id=None):
        node_id = node_id or state.current_node or \
            (state.quiz_state.current_node if state.quiz_state else "")
        self.mem.log_interaction(state.session_id, state.student_id, "quiz", node_id,
                                 f"{'✓' if correct else '✗'} {q.get('stem', '')[:50]}",
                                 {"correct": correct, "theta": round(theta, 3)})
        self.mem.snapshot_mastery(state.student_id, node_id, theta,
                                  state.profile.evidence_count[node_id])

    def _log_hint(self, state, level):
        sc = state.scaffold
        self.mem.log_hint(state.session_id, state.student_id,
                          sc.node_id or state.current_node, sc.question_id, level)

    # ==================== 工具 ====================
    @staticmethod
    def _fmt_question(q) -> str:
        return f"题目：{q.get('stem', '')}\n" + "\n".join(q.get("options", []))

    @staticmethod
    def _parse_name(text: str) -> str:
        """从自述里提取称呼：剥掉「我是 / 我叫 / 叫我」前缀，并截到首个标点

        「我叫张三，你好」→「张三」；空输入回退「同学」。
        """
        name = text.strip()
        for prefix in ("我的名字是", "我叫", "我是", "叫我", "叫"):
            if name.startswith(prefix):
                name = name[len(prefix):].strip()
                break
        for sep in ("，", "。", "、", ",", ".", "!", "！", "?", "？", "\n", "；", ";"):
            name = name.split(sep)[0].strip()
        name = name[:20].strip(" ")
        return name or "同学"

    @staticmethod
    def _parse_prior(text: str) -> dict:
        if any(w in text for w in ("没学过", "零基础", "都没学过", "没接触过")):
            return {}
        vague = any(w in text for w in VAGUE_WORDS)
        prior = {}
        for words, mapping in PRIOR_RULES:
            if any(w in text for w in words):
                for nid, v in mapping.items():
                    prior[nid] = 0.5 if vague else v
        return prior

    @staticmethod
    def _parse_goals(text: str) -> list:
        out = []
        for words, kws in GOAL_RULES:
            if any(w in text for w in words):
                out.extend(kws)
        return list(dict.fromkeys(out))

    def _payload(self, state) -> dict:
        profile = state.profile
        practicing = state.phase == PRACTICING
        node_id = state.practice_node if practicing else state.current_node
        node = self.kg.nodes.get(node_id)
        theta = profile.mastery.get(node_id) if profile and node_id else None
        return {
            "phase": state.phase,
            "phase_label": PHASE_LABELS.get(state.phase, state.phase),
            "node_id": node_id,
            "node_name": node.name if node else "",
            "node_difficulty": node.difficulty if node else None,
            "theta": round(theta, 3) if theta is not None else None,
            "lecture_para": 0 if practicing else state.lecture_para,
            "lecture_total": 0 if practicing else (segment_count(node.lecture) if node else 0),
            "scaffold": {"active": state.scaffold.active,
                         "level": LEVELS[state.scaffold.level] if state.scaffold.active else None,
                         "question_id": state.scaffold.question_id},
            "question": state.current_question,
            "plan": state.plan,
            "plan_idx": state.plan_idx,
            "report": state.report,
            "done_nodes": state.done_nodes,
            "session_id": state.session_id,
        }
