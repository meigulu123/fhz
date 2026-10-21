"""Agent 编排器：感知→规划→行动→记忆 主循环

单进程同步状态机 IDLE→DIAGNOSING→QUIZZING→TEACHING⇄INTERVENING→REFLECTING。
handle_message 五步：感知(意图分类+记忆) → 规划(FSM 分派) → 行动(结构动作) →
记忆(落库+快照) → 返回 (reply, ui_payload)。

双通道设计贯穿始终：发给 LLM 的消息同时携带标记（Mock 路由键）与原始数据
（真实 LLM 素材），Mock 与真实模式接口契约完全一致。
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import time

from src.agent.state import (AgentState, IDLE, DIAGNOSING, QUIZZING, TEACHING,
                             INTERVENING, REFLECTING, PRACTICING, PHASE_LABELS)
from src.memory.reflection import maybe_reflect
from src.memory.retrieve import build_context, retrieve_node, stats_json
from src.path.pacing import pace_params
from src.path.review import urgency_map
from src.student.diagnosis import AdaptiveQuiz, build_report
from src.student.error_cause import error_cause
from src.student.profile import StudentProfile, goal_node_names, init_mastery
from src.student.update import (apply_forgetting, mastery_update, propagate,
                                revise_mastery, undo_propagate)
from src.tutor.scaffold import LEVELS, Scaffolder, detect_stuck
from src.tutor.teach import segment_count, split_segments, teach_segment
from src.agent.milestones import check_milestones, milestone_message
from src.agent.chitchat import (correct_reply, wrong_reply, stuck_reassure,
                                node_done_praise, greeting_new, quiz_start,
                                diagnosis_confirm, path_begin, continue_lecture,
                                welcome_back)
from src.student.question_filter import goals_to_tags, next_question_for_node
from src.student.question_gen import gen_question
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 动态出题：同一知识点在本会话内最多现场补几道题（防止无限出题）
GEN_CAP_PER_NODE = 3

# 「继续」类推进词：讲义段末带 [ASK:] 提问位时，先说这两类词会先被请去回应提问，
# 避免带提问的段落被当成旁白一路跳过。刻意不含「嗯/好的」这类追问回答语。
_CONTINUE_WORDS = ("继续", "下一个", "下一段", "往下", "往下看", "next", "continue", "go on")
# 明确表示「不想回答这个提问」的跳过词：命中时直接推进，不再拦。
_SKIP_ASK_WORDS = ("跳过", "略过", "不想回答", "不知道", "直接往下", "先往下")

# ---------- 对话诊断 ----------
DIAG_QUESTIONS = [
    "先认识一下！怎么称呼你？（说个昵称就可以）",
    "你是哪个学校、什么专业的？这样我能配合你的学习节奏。",
    "之前学过哪些数学或机器学习基础？比如高等数学、线性代数、概率统计……"
    "没学过也没关系，直说就行。",
    "这次想重点攻克什么方向？比如深度学习、经典算法、面试求职、期末备考……",
]

# 专业 → 后续提问：不同专业该问的先修课不同（决定「根据专业提问」）
MAJOR_PRIOR_HINTS = [
    (("计算机", "软件", "人工智能", "智能", "数据", "电子", "自动化", "信息", "网络"),
     "高等数学、线性代数、概率统计、数据结构",
     "你是计算机相关专业，{courses} 这些大概率接触过——具体学过哪些？哪门学得比较吃力？"),
    (("数学", "统计", "物理"),
     "数学分析（高等数学）、高等代数（线性代数）、概率统计、数值分析",
     "你的专业数理要求高，通常学过 {courses}——分别掌握到什么程度？"
     "有哪门是「学过但没学透」的？"),
    (("管理", "经济", "金融", "商", "会计", "市场"),
     "微积分、线性代数、概率统计、统计学",
     "经管类一般开设 {courses}——你学过哪些？概率统计这块感觉如何？"),
    (("文", "法", "教育", "外语", "新闻", "历史", "艺术", "哲学", "设计"),
     "高等数学、线性代数、概率统计",
     "你的专业偏文科，学机器学习要先补一点数学——{courses} 这些接触过吗？"),
]

# 专业 → 目标提问的示例方向（让「想学什么」也更贴合专业）
MAJOR_GOAL_EXAMPLES = [
    (("计算机", "软件", "人工智能", "智能", "数据", "电子", "自动化", "信息", "网络"),
     "深度学习、算法竞赛、课程设计、面试求职"),
    (("数学", "统计", "物理"),
     "深度学习、统计学习、科研方向、读文献做实验"),
    (("管理", "经济", "金融", "商", "会计", "市场"),
     "数据分析、业务建模、用户画像、面试求职"),
    (("文", "法", "教育", "外语", "新闻", "历史", "艺术", "哲学", "设计"),
     "AI 应用入门、数据分析、行业研究、期末备考"),
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
        self.q_by_id = {q["id"]: q for q in questions if q.get("id")}

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
            reply = greeting_new() + "\n\n" + DIAG_QUESTIONS[0]
            return reply, self._payload(state)
        state.profile = profile
        now = time.time()
        # 遗忘衰减：以「知识点最近一次交互」为接触时间。该时间取自 interactions 表
        # （跨会话有效，重启后仍在），回填到 profile.last_seen 后按间隔天数衰减；
        # 间隔 < 1 天不衰减，未被作答过的节点（mastery 缺失）不参与。
        last_map = self.mem.last_ts_by_node(state.student_id)
        profile.last_seen.update(last_map)
        for nid, ts in last_map.items():
            if nid not in profile.mastery:
                continue
            days = (now - ts) / 86400.0
            if days >= 1.0:
                apply_forgetting(profile, nid, days)
        # 提示依赖度与待复习标记同样只在内存里（不落库），从库派生后回填，保证跨会话有效：
        # ①hint_profile ← hint_usage 里每个节点用过的最高提示层级；
        # ②needs_review ← 答错过的知识点所对应的先修集（与 update.py 的标记口径一致）。
        profile.hint_profile.update(self.mem.hint_levels_by_node(state.student_id))
        for nid in self.mem.wrong_node_ids(state.student_id):
            profile.needs_review.update(self.kg.prereqs_of(nid))
        state.session_id = self.mem.start_session(state.student_id)
        if not self.mem.has_study_history(state.student_id):
            reply = self._first_learn_greeting(profile.name)
        else:
            preview = self.mem.last_reflection(state.student_id) or {}
            ctx = build_context(self.mem, state.student_id,
                                preview.get("next_session_preview", ""), preview)
            reply = self._greeting(ctx or preview.get("next_session_preview", ""))
        # 直接用 _new_batch 的返回：其中已含「本次反思调整说明 + 首个知识点导入」
        batch_reply, payload = self._new_batch(state)
        return reply + "\n\n" + batch_reply, payload

    def restart_diagnosis(self, state: AgentState) -> str:
        """清空会话重新诊断：新建空白画像并进入诊断，返回开场白（不恢复旧画像）"""
        state.profile = StudentProfile(student_id=state.student_id)
        state.phase = DIAGNOSING
        state.diagnosis_step = 0
        return greeting_new() + "\n\n" + DIAG_QUESTIONS[0]

    def start_role_diagnosis(self, state: AgentState, name: str, major: str,
                             goals: list) -> str:
        """角色一键体验：用预置背景（称呼/专业/目标）建档后直接进入摸底测验。

        与「演示账号」的区别：这里只填背景，不预置掌握度——学生的真实基础
        全部由摸底测验测得，再据此生成路径与教学节奏。返回开场白。
        """
        profile = StudentProfile(student_id=state.student_id)
        profile.name = name or "同学"
        profile.major = major or ""
        profile.goals = [g for g in (goals or []) if g][:2]
        profile.goal_keywords = self._parse_goals(" ".join(profile.goals))
        init_mastery(profile, self.kg)
        self.mem.save_student(profile)
        state.profile = profile
        state.session_id = self.mem.start_session(state.student_id)
        self.mem.log_interaction(
            state.session_id, state.student_id, "message", "",
            f"角色体验建档：专业={profile.major or '未填'}；"
            f"学习目标={'、'.join(profile.goals) or '未填'}")
        lead = [f"你好，{profile.name}！"]
        analysis = self._analysis_major(profile, profile.major)
        if analysis:
            lead.append(analysis)
        goal_note = self._analysis_goal(profile)
        if goal_note:
            lead.append(goal_note)
        lead.append("先做几道摸底题，我按你的实际水平来安排学习路径和节奏。")
        state.phase = QUIZZING
        state.quiz_state = self.quiz.new_state(profile)
        q = self.quiz.next_question(state.quiz_state)
        if q.get("id") is None:
            # 题库耗尽：直接收敛进入教学，绝不把空题（{"id": None}）丢给弹窗——
            # 否则弹窗会打开却没有题干、没有选项。
            return "\n\n".join(lead) + "\n\n" + self._quiz_finished(state)[0]
        state.current_question = q
        state.used_qids.append(q["id"])
        return ("\n\n".join(lead) + "\n\n" + quiz_start() + "\n\n"
                + self._fmt_question(q))

    # ==================== 主入口 ====================
    def handle(self, state: AgentState, text: str) -> tuple:
        import time as _time
        t0 = _time.time()
        text = (text or "").strip()
        if not text:
            return "我在的，想说什么都可以，比如聊聊学习进度或你卡住的地方。", self._payload(state)
        state.interaction_count += 1
        # 空闲跟进：学习阶段离开 ≥5 分钟后回来，先让大模型更新一次画像再继续
        if state.phase in (TEACHING, INTERVENING) and self._idle_update_due(state):
            self._update_profile_from_conversation(state, "idle")
        intent = self._classify(text)
        t1 = _time.time()
        try:
            state.memory_ctx = build_context(self.mem, state.student_id, text,
                                             self.mem.last_reflection(state.student_id))
        except Exception as e:
            logger.warning("记忆检索失败，跳过记忆上下文: %s", e)
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
        t2 = _time.time()
        logger.debug("handle完成: phase=%s intent=%s 意图耗时=%.1fms 总耗时=%.1fms",
                     state.phase, kind, (t1-t0)*1000, (t2-t0)*1000)
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
        except Exception as e:
            logger.warning("LLM意图分类失败，降级到规则兜底: %s", e)
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
        # 按学习目标筛选题目
        q = self._select_question(state, nid)
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
        # 按学习目标选下一题；题库耗尽时动态生成新题
        nq = self._select_question(state, state.practice_node)
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
        # 确认阶段：学生确认或修正诊断结果
        if step == 99:
            return self._diagnosis_confirm(state, text)
        if step == 0:
            profile.name = self._parse_name(text)
            reply = f"你好，{profile.name}！" + self._analysis_major(profile, "") \
                + "\n\n" + self._adapt_question(1, profile)
            profile.major = ""   # 专业留到下一位回答
        elif step == 1:
            profile.major = text.strip()[:30]
            reply = self._analysis_major(profile, text) + "\n\n" + self._adapt_question(2, profile)
        elif step == 2:
            parsed = self._extract_prior_llm(text)
            if parsed is None:  # 离线/故障：规则解析兜底
                profile.prior.update(self._parse_prior(text))
                if "自学" in text:
                    profile.style_tags.append("自学型")
            else:
                profile.prior.update(parsed["prior"])
                self._merge_style_tags(profile, parsed["tags"])
            reply = self._analysis_prior(profile) + "\n\n" + self._adapt_question(3, profile)
        else:
            return self._diagnosis_done(state, text)
        state.diagnosis_step += 1
        return reply, self._payload(state)

    # ---------- 对话诊断：动态分析（每步读学生实际回答 + 知识图谱） ----------
    def _analysis_major(self, profile, text) -> str:
        """根据专业/学校自述推断学科背景，给出针对性的学习安排说明"""
        major = (text or profile.major or "").strip()
        if not major:
            return ("接下来我会边聊边给你建学习档案，了解清楚后就能给你排一条"
                    "只属于你的学习路径。")
        if any(w in major for w in ("计算机", "软件", "人工智能", "智能", "数据",
                                    "电子", "自动化", "信息", "网络")):
            return (f"你是{major}方向的同学，编程和工程实践上应该不吃亏，"
                    f"机器学习里偏应用的算法你会学得更快；数学基础我一会儿单独确认一下。")
        if any(w in major for w in ("数学", "统计", "物理")):
            return (f"你的{major}背景意味着数理底子通常比较扎实，我会多讲原理和推导，"
                    f"让你从根上理解模型为什么这样设计。")
        if any(w in major for w in ("管理", "经济", "金融", "商", "会计")):
            return (f"你是{major}背景，更看重应用和业务价值，我会多用案例和业务场景来讲，"
                    f"少堆公式，先把「能用起来」放在第一位。")
        if any(w in major for w in ("文", "法", "教育", "外语", "新闻", "历史", "艺术")):
            return (f"你是{major}背景也完全没问题——我会把概念讲成生活里的例子，"
                    f"需要数学时再补最必要的那一点，不会一上来就砸公式。")
        return (f"了解了，你是{major}方向。机器学习的入门门槛其实没那么高，"
                f"我会按你的基础和节奏来安排内容。")

    def _analysis_prior(self, profile) -> str:
        """根据先修自述识别到的知识点，说明后续会如何利用这些基础"""
        names = [self.kg.nodes[n].name for n in profile.prior if n in self.kg.nodes]
        if not names:
            return ("没关系，零基础可以从头学起——我会把基础概念拆得更细，"
                    "每个知识点都配一道小题确认你真的懂了，再往前走。")
        if len(names) >= 3:
            return (f"我注意到你已经接触过 {', '.join(names[:4])} 等 {len(names)} 个相关知识点，"
                    f"这些我会作为你的已有基础：直接跳过基础讲解、用更难的题验证，"
                    f"把时间留给真正薄弱的环节。")
        return (f"你提到学过 {', '.join(names)}，我先按已有基础处理——"
                f"接下来用几道题验证一下，确实扎实就直接往上学。")

    def _analysis_goal(self, profile) -> str:
        """根据学习目标与图谱映射，说明路径与题目会如何贴合这个目标"""
        goals = profile.goals or []
        goal = goals[0] if goals else ""
        nodes = goal_node_names(profile, self.kg)[:4]
        if nodes:
            return (f"你的目标是「{goal}」，我会把 {', '.join(nodes)} 等相关知识点"
                    f"优先排进路径，并让出题更贴近这个方向。")
        if goal:
            return f"你的目标是「{goal}」，我会据此调整路径排序与出题取向。"
        return ""

    def _adapt_question(self, idx, profile) -> str:
        """按已有画像调整下一问的措辞（问题内核不变，保证信息可解析）"""
        base = DIAG_QUESTIONS[idx]
        if idx == 2:
            # 先修提问随专业变化：不同专业该确认的课程不同
            major = profile.major or ""
            for keys, courses, tpl in MAJOR_PRIOR_HINTS:
                if any(w in major for w in keys):
                    return tpl.format(courses=courses) + "没学过也没关系，直说就行。"
            return base
        if idx == 3:
            examples = "深度学习、经典算法、面试求职、期末备考"
            major = profile.major or ""
            for keys, ex in MAJOR_GOAL_EXAMPLES:
                if any(w in major for w in keys):
                    examples = ex
                    break
            if profile.prior:
                names = [self.kg.nodes[n].name for n in profile.prior if n in self.kg.nodes]
                return (f"基础这块我记下了（{', '.join(names[:3])}）。"
                        f"这次想重点攻克什么方向？比如{examples}……")
            return (f"基础这块我记下了。这次想重点攻克什么方向？"
                    f"比如{examples}……")
        return base

    def _diagnosis_done(self, state, text):
        profile = state.profile
        parsed = self._extract_goals_llm(text)
        if parsed is None:  # 离线/故障：规则解析兜底
            goals = text.strip()[:50]
            profile.goals = [goals] if goals else []
            profile.goal_keywords = self._parse_goals(text)
        else:
            profile.goals = parsed["goals"] or [text.strip()[:50]]
            profile.goal_keywords = parsed["goal_keywords"]
            self._merge_style_tags(profile, parsed["tags"])
        init_mastery(profile, self.kg)
        self.mem.save_student(profile)
        state.session_id = self.mem.start_session(state.student_id)
        self.mem.log_interaction(state.session_id, state.student_id, "message", "",
                                 self._diagnosis_log(profile))
        # 诊断确认环节：展示摘要，让学生确认或修正
        state.phase = DIAGNOSING
        state.diagnosis_step = 99  # 标记为确认阶段
        summary = self._diagnosis_summary(profile)
        goal_note = self._analysis_goal(profile)
        reply = (f"{diagnosis_confirm()}\n\n{summary}\n\n"
                 + (goal_note + "\n\n" if goal_note else "")
                 + "如果这些信息准确，请回复「确认」开始做摸底测验；"
                 "如果有需要修正的地方，直接告诉我（比如「我的专业是计算机」）。")
        return reply, self._payload(state)

    def _diagnosis_log(self, profile) -> str:
        """诊断落库文案：写成学生看得懂的自然语言（历史对话页会直接展示）"""
        prior_names = [self.kg.nodes[n].name for n in profile.prior if n in self.kg.nodes]
        return (f"完成学情诊断：专业={profile.major or '未填'}；"
                f"已有基础={'、'.join(prior_names[:5]) or '零基础'}；"
                f"学习目标={'、'.join(profile.goals[:2]) or '未填'}")

    def _diagnosis_summary(self, profile) -> str:
        """生成诊断摘要，供学生确认"""
        lines = []
        if profile.name:
            lines.append(f"- 称呼：{profile.name}")
        if profile.major:
            lines.append(f"- 专业：{profile.major}")
        if profile.prior:
            prior_names = [self.kg.nodes[n].name for n in profile.prior if n in self.kg.nodes]
            if prior_names:
                lines.append(f"- 已有基础：{', '.join(prior_names[:5])}")
        if profile.goals:
            lines.append(f"- 学习目标：{', '.join(profile.goals[:2])}")
        if profile.style_tags:
            lines.append(f"- 学习风格：{', '.join(profile.style_tags[:3])}")
        return "\n".join(lines) if lines else "（暂无详细信息）"

    def _diagnosis_confirm(self, state, text):
        """学生确认诊断结果：进入自适应测验阶段"""
        if any(w in text for w in ("确认", "对", "没错", "是的", "没问题", "开始")):
            profile = state.profile
            state.phase = QUIZZING
            state.quiz_state = self.quiz.new_state(profile)
            q = self.quiz.next_question(state.quiz_state)
            if q.get("id") is None:
                # 题库耗尽：直接收敛，避免弹出「没有题干、没有选项」的空题弹窗
                return self._quiz_finished(state)
            state.current_question = q
            state.used_qids.append(q["id"])
            reply = (quiz_start() + "\n\n"
                     + self._fmt_question(q))
            return reply, self._payload(state)
        else:
            # 学生要求修正：尝试提取修正内容，更新画像
            # 简单规则：如果提到专业/称呼/目标等关键词，更新对应字段
            profile = state.profile
            updated = []
            # 检查是否是专业修正
            if "专业" in text or "学校" in text:
                profile.major = text.strip()[:30]
                updated.append("专业/学校")
            # 检查是否是称呼修正
            if "叫我" in text or "我是" in text or "名字" in text:
                profile.name = self._parse_name(text)
                updated.append("称呼")
            # 检查是否是目标修正
            if any(w in text for w in ("目标", "想学", "重点")):
                profile.goals = [text.strip()[:50]]
                profile.goal_keywords = self._parse_goals(text)
                updated.append("学习目标")
            if not updated:
                # 无法识别修正类型，重新提问
                return ("好的，你想修正哪部分？比如：\n"
                        "- 「我的专业是 XX」\n"
                        "- 「叫我 XX」\n"
                        "- 「我想学 XX」\n\n"
                        "确认没问题就回复「确认」。"), self._payload(state)
            self.mem.save_student(profile)
            summary = self._diagnosis_summary(profile)
            return (f"已更新：{', '.join(updated)}\n\n更新后的信息：\n{summary}\n\n"
                    "还有要改的吗？没问题就回复「确认」。"), self._payload(state)

    # ---------- 摸底测验弹窗动作（跳过 / 提前结束，由 UI 直接调用） ----------
    def quiz_skip(self, state) -> str:
        """跳过当前检测题：不计分、不计覆盖，换一道同节点题目；换不出来则直接收尾"""
        if state.phase != QUIZZING or not state.current_question:
            return ""
        qs = state.quiz_state
        qs.skipped.add(state.current_question["id"])
        nq = self.quiz.next_question(qs)
        if nq.get("id") is not None:
            state.current_question = nq
            state.used_qids.append(nq["id"])
            return ""
        reply, _ = self._quiz_finished(state)
        state.history.append({"role": "user", "content": "跳过本题"})
        state.history.append({"role": "assistant", "content": reply})
        return reply

    def quiz_finish(self, state) -> str:
        """学生主动结束摸底测验：按已答情况生成画像与学习路径，并写入对话记录"""
        if state.phase != QUIZZING:
            return ""
        self.quiz.stop(state.quiz_state, "学生叫停")
        reply, _ = self._quiz_finished(state)
        state.history.append({"role": "user", "content": "提交"})
        state.history.append({"role": "assistant", "content": reply})
        return reply

    def quiz_answer(self, state, text) -> str:
        """摸底弹窗作答（UI 直接调用）：静默记轨迹，不写逐题对错、不贴题进对话

        学生在弹窗里一道道选，全程不给对错反馈；这里只更新掌握度与自适应轨迹。
        全部答完（或主动提交）时才把「诊断报告 + 首个知识点」写进对话。
        """
        if state.phase != QUIZZING or not state.current_question or not state.quiz_state:
            return ""
        qs = state.quiz_state
        q = state.current_question
        choice = self._choice(text, {})
        if choice is None:
            return ""
        correct = choice == q.get("answer")
        node_id = qs.current_node
        theta_before = state.profile.mastery.get(node_id, 0.45)
        evidence_before = state.profile.evidence_count.get(node_id, 0)
        theta = mastery_update(state.profile, self.kg, node_id, correct, kind="quiz")
        self._log_attempt(state, q, correct, theta, node_id=node_id, choice=choice)
        self.quiz.record(qs, q, correct, choice, theta_before, evidence_before)
        state.last_results.append(correct)
        if len(state.last_results) > 8:
            state.last_results.pop(0)
        if qs.finished:
            reply, _ = self._quiz_finished(state)
            state.history.append({"role": "user", "content": "（完成摸底测验）"})
            state.history.append({"role": "assistant", "content": reply})
            return reply
        nq = self.quiz.next_question(qs)
        if nq.get("id") is None:
            reply, _ = self._quiz_finished(state)
            state.history.append({"role": "user", "content": "（完成摸底测验）"})
            state.history.append({"role": "assistant", "content": reply})
            return reply
        state.current_question = nq
        state.used_qids.append(nq["id"])
        return ""

    def quiz_edit_answer(self, state, index: int, text: str) -> str:
        """回看历史检测题并修改作答：重写该题记录，并按新对错重算画像与错题口径

        index 为该题在 quiz_state.answers 中的下标；text 为选项原文（含字母）。
        只在摸底测验进行中有效；已出的题（自适应轨迹）不回退。
        """
        if state.phase != QUIZZING or not state.quiz_state:
            return ""
        qs = state.quiz_state
        if not (0 <= index < len(qs.answers)):
            return ""
        node_id, qid, old_correct, old_choice = qs.answers[index][:4]
        choice = self._choice(text, {})
        if not choice or choice == old_choice:
            return ""
        q = self.q_by_id.get(qid) or {}
        correct = bool(q) and choice == q.get("answer")
        qs.answers[index] = (node_id, qid, correct, choice,
                             qs.answers[index][4], qs.answers[index][5])
        if correct != old_correct:
            self._recompute_quiz_node(state, node_id, old_correct, correct)
        theta = state.profile.mastery.get(node_id, 0.45)
        self.mem.revise_attempt(state.student_id, qid, correct, theta, choice=choice)
        return ""

    def _recompute_quiz_node(self, state, node_id, old_correct, new_correct) -> None:
        """改答后重算该节点画像：撤销旧作答传播 → 按新对错序列重放 → 重施新传播"""
        profile = state.profile
        qs = state.quiz_state
        entries = [a for a in qs.answers if a[0] == node_id]
        base_theta, base_ev = entries[0][4], entries[0][5]
        if base_theta is None or base_ev is None:   # 旧数据无基准：仅改记录，不动画像
            return
        undo_propagate(profile, self.kg, node_id, old_correct)
        revise_mastery(profile, self.kg, node_id,
                       [a[2] for a in entries], base_theta, base_ev)
        propagate(profile, self.kg, node_id, new_correct)
        self.mem.snapshot_mastery(state.student_id, node_id,
                                  profile.mastery.get(node_id, 0.0),
                                  profile.evidence_count.get(node_id, 0))

    def log_practice(self, state, q, correct: bool, choice: str = "") -> float:
        """错题重练作答落库：与测验同口径更新掌握度并写作答记录，返回新掌握度

        供错题本「一键组卷重练」复用，不改变对话状态机相位。
        """
        node_id = q.get("node_id") or state.current_node
        theta = mastery_update(state.profile, self.kg, node_id, correct, kind="quiz")
        self._log_attempt(state, q, correct, theta, node_id=node_id, choice=choice)
        return theta

    def _quiz_turn(self, state, text, intent):
        qs = state.quiz_state
        q = state.current_question
        choice = self._choice(text, intent)
        if choice is None:
            return ("这是水平摸底测验，尽量凭感觉选一个（回复 A/B/C/D 即可），"
                    "实在不确定就选最像的。"), self._payload(state)
        correct = choice == q["answer"]
        node_id = qs.current_node
        theta_before = state.profile.mastery.get(node_id, 0.45)
        evidence_before = state.profile.evidence_count.get(node_id, 0)
        theta = mastery_update(state.profile, self.kg, node_id, correct, kind="quiz")
        self._log_attempt(state, q, correct, theta, node_id=node_id, choice=choice)
        self.quiz.record(qs, q, correct, choice, theta_before, evidence_before)
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
        verdict = correct_reply() if correct else wrong_reply()
        expl = (q.get("explanation") or "").strip()
        return (f"{verdict}\n正确答案：{q.get('answer', '')}\n\n"
                f"解析：{expl or '（暂无解析）'}")

    def _quiz_finished(self, state):
        profile = state.profile
        report = build_report(profile, self.kg, self.planner, state.quiz_state)
        stuck = sum(1 for c in state.last_results if not c)
        params = pace_params(report["accuracy"], stuck)
        state.plan_idx = 0
        state.report = report
        # 首批路径同样走「大模型定序 + 个性化理由」通道（离线由 Mock 规则路由）
        state.plan = self._llm_order(
            state, self.planner.plan(profile, batch=params["batch"], pace=params["pace"],
                                     review=self._review_urgency(state)))
        # 报告建议起点与实际首个教学节点同源：学生点开第一课不会与报告不符
        if state.plan.get("items"):
            report["suggested"] = state.plan["items"][0]["name"]
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
        return diag + "\n\n" + self._pace_note(params, report) + "\n\n" + begin, self._payload(state)

    @staticmethod
    def _pace_note(params: dict, report: dict) -> str:
        """学习节奏与难度适配说明（让人看到「节奏是算出来的」）"""
        acc = report.get("accuracy")
        total = report.get("total_questions", 0)
        acc_txt = (f"摸底正确率 {round(acc * 100)}%" if isinstance(acc, (int, float))
                   and total else "起步阶段")
        pace, batch = params["pace"], params["batch"]
        if pace >= 1.2:
            rhythm = "表现不错，节奏加快"
        elif pace <= 0.6:
            rhythm = "先把每一步打牢，节奏放缓"
        else:
            rhythm = "节奏保持适中"
        return (f"📈 学习节奏：{acc_txt} → 节奏系数 {pace}，本批安排 {batch} 个知识点"
                f"（{rhythm}）；难度带也会随节奏放宽或收紧。")

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
        # 讲义分段末尾是 [ASK:] 提问位时，直接说「继续」先请他回应提问——否则带提问
        # 的段落会被当作旁白一路跳过，提问位就白设了（想说「跳过」则放行）
        if (self._pending_ask(state) and self._is_continue(text)
                and not any(w in text for w in _SKIP_ASK_WORDS)):
            return ("这一段末尾我留了个小问题，想先听你怎么想：用你自己的话说一句就行，"
                    "说得对不对都没关系，我再顺着往下讲。\n\n"
                    "（想先跳过这个提问，就说「跳过」。）"), self._payload(state)
        # 讲义讲解中：卡住 → 先把当前这一段换个说法重讲（而不是马上拉去做题）
        if intent == "confusion" or detect_stuck(state.scaffold, intent, text, state.last_results):
            return self._reteach(state, stuck_reassure())
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

    @staticmethod
    def _is_continue(text: str) -> bool:
        """是否为「继续 / 往下」类推进输入"""
        return any(w in (text or "") for w in _CONTINUE_WORDS)

    def _pending_ask(self, state) -> bool:
        """当前讲义分段末尾是否挂着 [ASK:] 提问位（学生还没回应）"""
        node = self.kg.nodes.get(state.current_node or "")
        if node is None:
            return False
        segs = split_segments(node.lecture or "")
        if not segs:
            return False
        i = min(max(state.lecture_para, 0), len(segs) - 1)
        return "[ASK:]" in segs[i]

    def _reteach(self, state, preamble):
        """重讲当前讲义分段：不换知识点、不跳去做题

        学生在讲义里说「我不会」时，先把这一段换个说法重讲一遍并点一个抓手；
        同一分段重讲过一次还卡住，才进入阶梯式脚手架。
        """
        node = self.kg.nodes.get(state.current_node or "")
        if node is None or not node.lecture:
            return (preamble + "\n\n我们回到刚才的知识点——你说说具体卡在哪一步？"
                    "我再顺着你的卡点讲。"), self._payload(state)
        segs = split_segments(node.lecture or "")
        idx = min(max(state.lecture_para, 0), max(len(segs) - 1, 0))
        if idx == state.reteach_para:            # 这一段已经重讲过 → 升级为阶梯提示
            return self._engage_scaffold(state, preamble)
        state.reteach_para = idx
        seg = segs[idx] if segs else ""
        body = [b.strip() for b in seg.split("\n\n")
                if b.strip() and not b.startswith("[ASK:]")]
        tip = body[0] if body else (node.summary or "")
        retell = self._fast_call(
            lambda: teach_segment(self.llm, state.current_node, idx, seg))
        if retell is None:   # 真实模型超时：离线 Mock 讲义兜底
            retell = teach_segment(getattr(self.llm, "fallback", self.llm),
                                   state.current_node, idx, seg)
        tail = f"先抓住一点就够：{tip}" if tip else "有哪一步没跟上，直接说，我从那里再讲。"
        return (preamble + "\n\n别急，这一段我换个说法再讲一遍：\n\n" + retell
                + "\n\n" + tail), self._payload(state)

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
        self._log_attempt(state, q, correct, theta, choice=choice)
        state.last_results.append(correct)
        if len(state.last_results) > 8:
            state.last_results.pop(0)
        if correct:
            if in_scaffold:
                self.scaffolder.on_correct(state.scaffold, state.profile)
            return self._finish_node(state, node_done_praise())
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
        return self._engage_scaffold(state, wrong_reply())

    def _engage_scaffold(self, state, preamble):
        q = self._next_question_for(state)
        if q is None:
            return ("我们回到讲义：回看刚才的 [ASK:] 提问，用自己的话说说你现在的想法，"
                    "我再帮你往下理。"), self._payload(state)
        state.current_question = q
        state.used_qids.append(q["id"])
        # 错因靶向（C1）：用「连错次数 + 掌握度 + 难度」判错因，L0 提示按错因反问；
        # 起始层级（C2）：该生在该节点历史退出层级越高（提示依赖越强），起步层级越高
        cause, _ = error_cause(q, state.profile,
                               count=1 + state.scaffold.wrong_streak)
        hist = state.profile.hint_profile.get(state.current_node, 0)
        r = self.scaffolder.engage(state.scaffold, q["id"], state.current_node,
                                   cause=cause, start_level=1 if hist >= 2 else 0)
        state.phase = INTERVENING
        self._log_hint(state, r["level"])
        return preamble + "\n\n" + (r["text"] or "先想一想，这题在考哪个知识点？"), self._payload(state)

    def _finish_node(self, state, praise):
        state.done_nodes.append(state.current_node)
        self.mem.log_interaction(state.session_id, state.student_id, "teach",
                                 state.current_node, "知识点完成")
        maybe_reflect(self.mem, self.llm, self.kg, state.profile, state.session_id,
                      "node_done", state.interaction_count, state.report, state.done_nodes)
        # 里程碑检测：完成节点后检查是否达成新里程碑
        new_ms = check_milestones(state, self.kg, self.mem)
        ms_msg = milestone_message(new_ms) if new_ms else ""
        state.current_question = None
        state.lecture_para = 0
        state.reteach_para = -1
        state.plan_idx += 1
        items = state.plan.get("items", [])
        if state.plan_idx < len(items):
            begin = self._begin_node(state, items[state.plan_idx])
            return praise + " 🎉" + ms_msg + "\n\n" + begin, self._payload(state)
        state.current_node = ""
        state.phase = TEACHING
        reply = (praise + " 🎉" + ms_msg + "\n\n这一批学习计划全部完成！"
                 "你可以继续说「继续」，我给你规划下一批；"
                 "或者今天先到这里，说「结束」即可，我会把学习记录保存好。")
        return reply, self._payload(state)

    def _begin_node(self, state, item) -> str:
        state.current_node = item["node_id"]
        state.lecture_para = 0
        state.reteach_para = -1
        state.current_question = None
        state.phase = TEACHING
        node = self.kg.nodes[item["node_id"]]
        segs = split_segments(node.lecture or "")
        seg0 = segs[0] if segs else ""
        seg = self._fast_call(
            lambda: teach_segment(self.llm, item["node_id"], 0, seg0))
        if seg is None:  # 8 秒没等到真实讲义：用离线 Mock 讲义先上课
            seg = teach_segment(getattr(self.llm, "fallback", self.llm),
                                item["node_id"], 0, seg0)
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
        """从当前节点选题：题库优先，题库耗尽时按画像动态生成新题"""
        return self._select_question(state, state.current_node)

    def _select_question(self, state, node_id):
        """选题：静态题库（按学习目标匹配度排序）优先；耗尽后现场生成新题"""
        if not node_id:
            return None
        goal_tags = goals_to_tags(state.profile) if state.profile else {"general"}
        q = next_question_for_node(self.qs_by_node.get(node_id, []), goal_tags,
                                    state.used_qids)
        if q is not None:
            return q
        return self._generate_question(state, node_id)

    def _generate_question(self, state, node_id):
        """题库耗尽时的动态出题：真实大模型生成，离线走规则兜底

        按节点限额（同节点本会话最多补 GEN_CAP_PER_NODE 道），避免无限出题；
        生成题 id 形如 gen_<node_id>_<n>，据此计数。
        """
        prefix = f"gen_{node_id}_"
        made = sum(1 for qid in state.used_qids if str(qid).startswith(prefix))
        if made >= GEN_CAP_PER_NODE:
            return None
        q = gen_question(self.llm, self.kg, node_id, state.profile, variant=made)
        if not q or not q.get("options"):
            return None
        q["id"] = f"{prefix}{made}"
        return q

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
        except Exception as e:
            logger.warning("LLM重规划失败，降级到规则: %s, node=%s", e, state.current_node)
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

    def _review_urgency(self, state) -> dict:
        """知识点 → 复习紧迫度（路径评分第 6 因子；来源于间隔重复排程）"""
        hits = self.mem.correct_by_node(state.student_id)
        last = self.mem.last_ts_by_node(state.student_id)
        return urgency_map(state.profile, self.kg, hits=hits, last_map=last)

    def _pending_adjust(self, state) -> dict:
        """上次会话反思的结构化调整（D1 闭环）：本会话首次规划时消费一次

        取上一次会话反思的 adjust（review_nodes / pace_hint / note）；用
        reflection_used 守卫，保证同一调整不会在后续批次里反复生效。
        """
        if state.reflection_used:
            return {}
        state.reflection_used = True
        prev = self.mem.last_reflection(state.student_id,
                                        exclude_session_id=state.session_id)
        adjust = (prev or {}).get("adjust")
        return adjust if isinstance(adjust, dict) else {}

    def _apply_adjust(self, state, adjust: dict) -> str:
        """把反思调整插到本批路径最前（回补上次会话标记的薄弱点），返回给学生看的说明

        只插入先修已达标（在 planner.frontier 内）的节点：反思挑中的薄弱点若前置
        还没打牢，直接前插会把学生推到还啃不动的题上，此时改为在说明里讲清楚。
        """
        note = (adjust or {}).get("note") or ""
        items = state.plan.get("items") or []
        frontier = set(self.planner.frontier(state.profile))
        picks, blocked = [], []
        for nid in (adjust or {}).get("review_nodes") or []:
            if nid not in self.kg.nodes:
                continue
            if any(i["node_id"] == nid for i in items):
                continue
            if nid not in frontier:
                blocked.append(self.kg.nodes[nid].name)
                continue
            picks.append(self._make_item(state, nid, "复习",
                                         reason="上次会话反思：先回补这个薄弱点"))
        if picks:
            state.plan["items"] = picks + items
        if blocked:
            note += "（" + "、".join(blocked) + " 的前置还没打牢，本批先补齐前置）"
        return note

    def _new_batch(self, state, prefix=""):
        stuck = sum(1 for c in state.last_results if not c)
        params = pace_params((state.report or {}).get("accuracy"), stuck)
        adjust = self._pending_adjust(state)
        # 反思给出的节奏调整落到本批参数上（D1：反思→下一次会话真正生效）
        hint = adjust.get("pace_hint")
        if hint == "slow":
            params["pace"] = round(max(0.4, params["pace"] - 0.2), 2)
            params["batch"] = max(1, params["batch"] - 1)
        elif hint == "fast":
            params["pace"] = round(min(1.6, params["pace"] + 0.2), 2)
        base = self.planner.plan(state.profile, batch=params["batch"],
                                 pace=params["pace"], review=self._review_urgency(state))
        state.plan = self._llm_order(state, base)
        state.plan_idx = 0
        state.current_node = ""
        state.current_question = None
        state.lecture_para = 0
        note = self._apply_adjust(state, adjust)
        self.mem.save_plan(state.session_id, state.student_id, params["pace"],
                           state.plan["band"], state.plan)
        if not state.plan["items"]:
            return "你的知识点掌握得都很扎实，可以自由选择想学的内容。", self._payload(state)
        begin = self._begin_node(state, state.plan["items"][0])
        head = f"🧠 智能体反思：{note}\n\n" if note else ""
        return prefix + head + begin, self._payload(state)

    @staticmethod
    def _fast_call(fn, timeout=8.0):
        """进场路径大模型快通道：限时等待，超时返回 None 由调用方走离线兜底。

        独立线程执行 + 8 秒硬上限：真实推理模型长考不阻塞登录/演示账号进场；
        超时后线程在后台自行结束、结果丢弃（进场后的正常交互照常调用）。
        """
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            return ex.submit(fn).result(timeout=timeout)
        except Exception:  # noqa: BLE001 —— 超时/故障统一返回 None
            return None
        finally:
            ex.shutdown(wait=False)

    def _llm_order(self, state, base: dict, llm=None) -> dict:
        """大模型驱动的路径决策：公式初筛候选 → LLM 定序与逐条理由 → 校验兜底

        公式保证科学底线（先修达标、ZPD 带内、难度适配），大模型读学情统计
        与候选清单输出最终学习顺序、面向学生的理由与整体安排说明。调用失败
        或输出非法（node_id 不在候选集）时整体回退公式结果，plan["engine"]
        标记实际决策引擎（路径页展示）。离线 Mock 模式无此路由，恒走公式。
        """
        candidates = base.get("items") or []
        if not candidates:
            return base
        stats = stats_json(state.profile, self.kg, report=state.report,
                           done_nodes=state.done_nodes)
        messages = [
            {"role": "system",
             "content": "[TPL:plan_initial]\n你是自适应学习路径规划专家。基于学生学情统计"
                        "和候选知识点清单，确定最终学习顺序，输出 JSON：\n"
                        '{"items": [{"node_id": "...", "reason": "..."}], "notes": "..."}\n'
                        "要求：\n"
                        "1. node_id 只能从候选清单中选择，不得新增或编造；\n"
                        "2. 候选已通过先修达标与 ZPD 难度带筛选（公式保证底线），"
                        "排序时优先考虑：薄弱先修回补、学习目标关联、由易到难；\n"
                        "3. 每个 item 的 reason 面向学生写一句具体理由，结合掌握度、"
                        "难度或学习目标，不要空话套话；\n"
                        "4. notes 用 1~2 句说明整体安排思路；\n"
                        "5. items 数量不超过候选数量。"},
            {"role": "user",
             "content": f"[stats_json={json.dumps(stats, ensure_ascii=False)}]\n"
                        f"[candidates_json={json.dumps(candidates, ensure_ascii=False)}]\n"
                        f"[band_json={json.dumps(base.get('band', {}), ensure_ascii=False)}]"},
        ]
        result = self._fast_call(lambda: (llm or self.llm).chat_json(messages))
        if not isinstance(result, dict) or not result:
            # 超时/故障/空输出一律回退公式：进场 8 秒快通道，绝不干等
            logger.info("LLM路径排序无有效输出，回退公式结果")
            return base
        base_by_id = {it["node_id"]: it for it in candidates}
        ordered = []
        for it in (result.get("items") or []) if isinstance(result, dict) else []:
            if not isinstance(it, dict):
                continue
            nid = it.get("node_id")
            if nid not in base_by_id or any(x["node_id"] == nid for x in ordered):
                continue  # 非法/重复 node_id 丢弃
            merged = dict(base_by_id[nid])  # tier/难度/评分等公式字段保留
            if it.get("reason"):
                merged["reason"] = str(it["reason"])
            ordered.append(merged)
        if not ordered:
            return base  # 输出全部非法：回退公式
        for it in candidates:  # LLM 未提及的候选按公式序补尾，保证批次完整
            if all(x["node_id"] != it["node_id"] for x in ordered):
                ordered.append(it)
        plan = dict(base)
        plan["items"] = ordered
        plan["engine"] = "llm"
        if result.get("notes"):
            plan["notes"] = str(result["notes"])
        return plan

    def _make_item(self, state, node_id, tier, reason=None):
        node = self.kg.nodes[node_id]
        return {"node_id": node_id, "name": node.name, "score": 0.0, "tier": tier,
                "difficulty": node.difficulty,
                "mastery": round(state.profile.mastery.get(node_id, 0.0), 3),
                "reason": reason or "重规划：回补先修知识点"}

    # ==================== 会话结束 ====================
    def _end_session(self, state):
        state.phase = REFLECTING
        # 会话结束画像跟进：大模型读本次对话更新画像（风格标签/目标/认知观察）
        self._update_profile_from_conversation(state, "session_end")
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
    def _log_attempt(self, state, q, correct, theta, node_id=None, choice=None):
        """写作答记录：content 仍用「✓/✗ + 题干前缀」（错题本据此匹配题目），
        选项与正确答案另写入 payload，供历史对话页回显「你选 X，正确 Y」。
        """
        node_id = node_id or state.current_node or \
            (state.quiz_state.current_node if state.quiz_state else "")
        self.mem.log_interaction(state.session_id, state.student_id, "quiz", node_id,
                                 f"{'✓' if correct else '✗'} {q.get('stem', '')[:50]}",
                                 {"correct": correct, "theta": round(theta, 3),
                                  "qid": q.get("id", ""),
                                  "choice": (choice or "").upper(),
                                  "answer": str(q.get("answer", "")).upper()})
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

    # ==================== 画像：大模型从对话生成与持续更新 ====================
    @staticmethod
    def _merge_style_tags(profile, tags) -> None:
        for t in tags or []:
            if isinstance(t, str) and t and t not in profile.style_tags:
                profile.style_tags.append(t[:12])

    def _kg_id_index(self) -> str:
        """知识点 ID-名称清单（诊断提取提示词用）"""
        return "；".join(f"{nid} {node.name}"
                         for nid, node in list(self.kg.nodes.items())[:80])

    def _extract_prior_llm(self, text, llm=None):
        """大模型从先修基础自述中提取 prior 与风格标签；失败返回 None（走规则）

        返回 {"prior": {节点ID: 0~1}, "tags": [...]}，ID 经图谱校验。
        """
        messages = [
            {"role": "system",
             "content": "[TPL:diag_extract]\n你是学情诊断信息提取模块。从学生的一句话自述中"
                        "提取先修基础与学习风格，输出 JSON：\n"
                        '{"prior": {"知识点ID": 0~1}, "style_tags": ["标签"]}\n'
                        "可用知识点ID（只输出学生明确提到的，没提及的不输出）：\n"
                        + self._kg_id_index() + "\n"
                        "要求：\n"
                        "1. prior 的值：明确学过=1.0，「学过一点/了解过/选修过」=0.5；\n"
                        "2. 「没学过/零基础」时 prior 输出 {}；\n"
                        "3. style_tags 提取 0~2 个学习风格标签（如：自学型、零基础、"
                        "有竞赛经历）。"},
            {"role": "user", "content": f"[answer={text}]"},
        ]
        result = self._fast_call(lambda: (llm or self.llm).chat_json(messages))
        if not isinstance(result, dict) or "prior" not in result:
            # 超时/故障/非法输出走规则兜底（诊断 8 秒快通道，不干等）
            return None
        prior = {}
        for nid, v in (result.get("prior") or {}).items():
            if nid in self.kg.nodes:
                try:
                    prior[nid] = max(0.0, min(1.0, float(v)))
                except (TypeError, ValueError):
                    continue
        tags = [t for t in result.get("style_tags") or []
                if isinstance(t, str) and t.strip()]
        return {"prior": prior, "tags": tags}

    def _extract_goals_llm(self, text, llm=None):
        """大模型从目标自述中提取目标与关键词；失败返回 None（走规则）"""
        messages = [
            {"role": "system",
             "content": "[TPL:diag_extract]\n你是学情诊断信息提取模块。从学生的一句话自述中"
                        "提取学习目标，输出 JSON：\n"
                        '{"goals": ["目标描述"], "goal_keywords": ["知识点ID"],'
                        ' "style_tags": ["标签"]}\n'
                        "可用知识点ID（只输出与目标直接相关的，没提及的不输出）：\n"
                        + self._kg_id_index() + "\n"
                        "要求：\n"
                        "1. goals 用一句话概括学生学习目标（不超过 50 字）；\n"
                        "2. goal_keywords 列出与目标直接相关的知识点ID；\n"
                        "3. style_tags 提取 0~2 个学习风格标签。"},
            {"role": "user", "content": f"[answer={text}]"},
        ]
        result = self._fast_call(lambda: (llm or self.llm).chat_json(messages))
        if not isinstance(result, dict) or "goals" not in result:
            # 超时/故障/非法输出走规则兜底（诊断 8 秒快通道，不干等）
            return None
        goals = [g[:50] for g in result.get("goals") or []
                 if isinstance(g, str) and g.strip()]
        kws = [k for k in result.get("goal_keywords") or []
               if k in self.kg.nodes]
        tags = [t for t in result.get("style_tags") or []
                if isinstance(t, str) and t.strip()]
        return {"goals": goals, "goal_keywords": kws, "tags": tags}

    def _update_profile_from_conversation(self, state, reason="idle", llm=None) -> bool:
        """画像持续更新：大模型读近期对话与学情，输出画像增量并落库

        触发时机：会话结束 / 空闲超过 5 分钟（命题「多次交互中持续记录进展」）。
        增量合并进画像（风格标签去重追加、目标变化覆盖）并写入
        profile_observations 表；无有效增量不落库。失败走规则兜底。
        """
        profile = state.profile
        stats = stats_json(profile, self.kg, report=state.report,
                           done_nodes=state.done_nodes)
        recent = self.mem.recent_interactions(state.student_id, limit=10)
        recent_txt = "\n".join(
            f"- {r['kind']}: {str(r['content'])[:80]}" for r in recent)
        messages = [
            {"role": "system",
             "content": "[TPL:profile_observe]\n你是学情观察模块。基于学生近期学习对话与"
                        "学情统计，更新学生画像，输出 JSON：\n"
                        '{"style_tags_add": ["新增风格标签"],'
                        ' "goals_update": "新的学习目标描述或 null",'
                        ' "observation": "一句话认知/行为观察"}\n'
                        "要求：\n"
                        "1. style_tags_add 只输出确有依据的新标签 0~2 个（如："
                        "偏好例题巩固、喜欢追问原理、需要正向鼓励、答题节奏稳定），"
                        "与已有标签重复的不输出；\n"
                        "2. goals_update 仅在学生目标明显变化时给出，否则输出 null；\n"
                        "3. observation 用一句话记录学生当前认知或行为特点"
                        "（结合正确率、卡住情况、学习进度），具体不空泛。"},
            {"role": "user",
             "content": f"[stats_json={json.dumps(stats, ensure_ascii=False)}]\n"
                        f"[recent={recent_txt}]"},
        ]
        try:
            result = (llm or self.llm).chat_json(messages) or {}
            if not isinstance(result, dict):
                result = {}
        except Exception:  # noqa: BLE001 —— 离线/故障走规则兜底
            result = self._observe_rules(state)
        content = {"style_tags_add": [], "goals_update": None, "observation": ""}
        for t in result.get("style_tags_add") or []:
            if isinstance(t, str) and t and t not in profile.style_tags:
                profile.style_tags.append(t[:12])
                content["style_tags_add"].append(t[:12])
        gu = result.get("goals_update")
        if isinstance(gu, str) and gu.strip():
            profile.goals = [gu.strip()[:50]]
            content["goals_update"] = gu.strip()[:50]
        obs = result.get("observation")
        if isinstance(obs, str) and obs.strip():
            content["observation"] = obs.strip()[:100]
        if not (content["style_tags_add"] or content["goals_update"]
                or content["observation"]):
            return False
        self.mem.save_profile_observation(state.student_id, reason, content)
        self.mem.save_student(profile)
        return True

    @staticmethod
    def _observe_rules(state) -> dict:
        """画像观察规则兜底（离线 Mock 模式）：由学情统计确定性生成"""
        acc = (state.report or {}).get("accuracy") or 0.0
        tags = []
        if acc >= 0.7:
            tags.append("答题节奏稳定")
        elif acc < 0.4:
            tags.append("基础需巩固")
        return {
            "style_tags_add": tags,
            "goals_update": None,
            "observation": f"已完成 {len(state.done_nodes)} 个知识点，"
                           f"近期答题正确率 {round(acc * 100)}%。",
        }

    def _idle_update_due(self, state) -> bool:
        """空闲跟进触发：距上次交互 ≥5 分钟且上次画像观察也已过期"""
        now = time.time()
        last_int = self.mem.latest_interaction_ts(state.student_id)
        if last_int <= 0 or now - last_int < 300:
            return False
        return now - self.mem.latest_observation_ts(state.student_id) >= 300

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
