"""MockLLM：规则路由的离线兜底大模型。

同一套 OpenAI 风格接口，无网无 Key 时由规则从真实知识库（讲义/题库 hints/
模板报告）取内容拼回答——知识是真的，生成环节由规则替代。所有输出确定性、
可离线、可 pytest 回归。真实 LLM 模式与 Mock 模式的接口契约完全一致。
"""
import json
import re

from .base import BaseLLM

CONFUSION_WORDS = [
    "不会", "不懂", "卡住", "卡了", "太难", "怎么办", "怎么做", "帮帮我",
    "求助", "想不出来", "想不通", "蒙了", "help", "不会做", "看不懂",
]
GOAL_WORDS = ["想学", "目标", "换一个", "换目标", "重点学", "我要学", "改学", "想先学"]
PRACTICE_WORDS = ["练习", "做题", "刷题", "做几道", "出几道", "来几道", "练一练",
                  "练一下", "测一测", "出题", "做做题"]
QUESTION_WORDS = ["为什么", "什么是", "是什么", "什么意思", "区别", "怎么理解", "？", "?"]
END_WORDS = ["结束", "再见", "退出", "拜拜", "下课", "今天就到这"]


class MockLLM(BaseLLM):
    """规则路由离线 LLM。构造参数：kg（KnowledgeGraph）、questions（题库列表）。"""

    def __init__(self, kg, questions):
        self.kg = kg
        self.qbank = {q["id"]: q for q in questions}

    # ---------- 公开接口 ----------
    def chat(self, messages) -> str:
        tpl = self._tpl(messages)
        ctx = self._ctx(messages)
        last_user = next((m["content"] for m in reversed(messages)
                          if m["role"] == "user"), "")
        router = {
            "intent": lambda: json.dumps(self._classify_intent(last_user), ensure_ascii=False),
            "teach": lambda: self._teach(ctx),
            "scaffold": lambda: self._scaffold(ctx),
            "diag_report": lambda: self._diag_report(ctx),
            "quiz_feedback": lambda: self._quiz_feedback(ctx),
            "replan": lambda: json.dumps(self._replan(ctx), ensure_ascii=False),
            "reflection": lambda: json.dumps(self._reflection(ctx), ensure_ascii=False),
            "greeting": lambda: self._greeting(ctx),
            "first_learn": lambda: self._first_learn(ctx),
            "qa": lambda: self._qa(ctx),
        }
        fn = router.get(tpl)
        if fn:
            return fn()
        return self._fallback(ctx)

    def chat_json(self, messages) -> dict:
        tpl = self._tpl(messages)
        if tpl in ("intent", "replan", "reflection"):
            return json.loads(self.chat(messages))
        return super().chat_json(messages)

    # ---------- 解析辅助 ----------
    @staticmethod
    def _tpl(messages) -> str:
        for m in messages:
            if m["role"] == "system":
                m2 = re.search(r"\[TPL:(\w+)\]", m["content"])
                if m2:
                    return m2.group(1)
        return ""

    @staticmethod
    def _ctx(messages) -> dict:
        """提取全部标记：node/para/question_id/level/stats_json/trigger/preview/..."""
        ctx = {"para": 0}
        blob = "\n".join(m["content"] for m in messages)
        for key in ("node", "para", "question_id", "level", "trigger", "correct",
                    "user_answer", "answer", "preview", "name"):
            m = re.search(rf"\[{key}=([^\]]*)\]", blob)
            if m:
                ctx[key] = m.group(1)
        m = re.search(r"\[stats_json=(\{.*?\})\]", blob, re.S)
        if m:
            try:
                ctx["stats"] = json.loads(m.group(1))
            except json.JSONDecodeError:
                ctx["stats"] = {}
        return ctx

    # ---------- 规则路由实现 ----------
    @staticmethod
    def _classify_intent(text: str) -> dict:
        if any(w in text for w in END_WORDS):
            return {"intent": "end_session", "confidence": 0.9}
        if any(w in text for w in CONFUSION_WORDS):
            return {"intent": "confusion", "confidence": 0.85}
        if any(w in text for w in GOAL_WORDS):
            return {"intent": "goal_change", "confidence": 0.8}
        if re.fullmatch(r"[ABCD]", text.strip(), re.I):
            return {"intent": "answer", "confidence": 0.95}
        if re.search(r"选\s*[ABCD]", text, re.I):
            return {"intent": "answer", "confidence": 0.9}
        if any(w in text for w in PRACTICE_WORDS):
            return {"intent": "practice", "confidence": 0.85}
        if any(w in text for w in QUESTION_WORDS):
            return {"intent": "question", "confidence": 0.7}
        return {"intent": "answer", "confidence": 0.6}

    def _teach(self, ctx) -> str:
        """按 [node=][para=] 返回讲义下一分段（分段边界为 [ASK:] 提问位）"""
        node = self.kg.nodes.get(ctx.get("node", ""))
        if node is None:
            return "（没有指定当前知识点，请先开始学习路径）"
        if not node.lecture:
            return "（讲义生成中，请稍候刷新）"
        blocks = [b.strip() for b in node.lecture.split("\n\n") if b.strip()]
        segs, cur, i = [], [], 0
        for b in blocks:
            if b.startswith("[ASK:]"):
                segs.append(cur + [b])
                cur = []
                i += 1
            else:
                cur.append(b)
        if cur:
            segs.append(cur)
        para = int(ctx.get("para", 0))
        if para >= len(segs):
            return (f"「{node.name}」的讲义已经讲完了。"
                    "接下来做几道巩固题检验一下掌握情况吧。")
        return "\n\n".join(segs[para])

    def _scaffold(self, ctx) -> str:
        """按 [question_id=][level=] 从题库 hints 取脚手架内容"""
        q = self.qbank.get(ctx.get("question_id", ""))
        if q is None:
            return "（未找到对应题目，请重试）"
        level = ctx.get("level", "L0")
        hints = q.get("hints", {})
        text = hints.get(level)
        if not text:
            return "（该题目缺少提示数据）"
        prefix = {"L0": "先别急，想一想：", "L1": "给你一个提示：",
                  "L2": "看一个类似的思路：", "L3": "我们一步步来："}.get(level, "")
        return f"{prefix}{text}"

    def _quiz_feedback(self, ctx) -> str:
        correct = ctx.get("correct", "false") == "true"
        if correct:
            return ("回答正确！思路很清晰。"
                    "继续保持，我们接着学下一个知识点。")
        qid = ctx.get("question_id", "")
        hint0 = self.qbank.get(qid, {}).get("hints", {}).get("L0", "")
        return (f"先不公布答案。你自己再想想：{hint0}")

    def _qa(self, ctx) -> str:
        """按 [node=] 取节点，返回名称概述 + 讲义正文首段（跳过 [ASK:]）"""
        node = self.kg.nodes.get(ctx.get("node", ""))
        if node is None:
            return self._fallback(ctx)
        lines = [f"「{node.name}」{node.summary}"]
        if node.lecture:
            body = [b.strip() for b in node.lecture.split("\n\n")
                    if b.strip() and not b.startswith("[ASK:]")]
            if body:
                lines.append(body[0])
        return "\n\n".join(lines)

    @staticmethod
    def _diag_report(ctx) -> str:
        s = ctx.get("stats", {})
        weak = "、".join(s.get("weak", [])[:5]) or "无"
        strong = "、".join(s.get("strong", [])[:5]) or "待继续观察"
        band = s.get("band", {})
        lines = [
            f"{s.get('name', '同学')}，你的学情诊断完成啦！",
            f"诊断覆盖 {s.get('covered', 0)} 个知识点，答题正确率 {s.get('accuracy', 0)}。",
            f"掌握较好：{strong}。",
            f"需要加强：{weak}。",
            f"你的最近发展区（ZPD）位于掌握度 {band.get('z_low', '-')} ~ "
            f"{band.get('z_high', '-')} 之间，",
            f"建议从「{s.get('suggested', '')}」开始学习。",
            "已为你生成个性化学习路径，去『学习路径』页看看吧。",
        ]
        return "\n".join(lines)

    def _replan(self, ctx) -> dict:
        """重规划规则兜底（LLM 模式由真实模型输出同构 JSON）

        语义：回补当前节点最薄弱的先修知识点（而非全局最弱），与 PathPlanner 一致。
        """
        trigger = ctx.get("trigger", "reorder")
        node_id = ctx.get("node", "")
        mastery = ctx.get("stats", {}).get("prereqs", {})
        if trigger in ("stuck_l3", "prereq_collapse"):
            prereqs = self.kg.prereqs_of(node_id)
            if prereqs:
                weakest = min(prereqs, key=lambda p: mastery.get(p, 0.5))
                return {
                    "action": "review_prereq",
                    "node_id": weakest,
                    "reason": "当前知识点反复卡住，先回补最薄弱的先修知识点",
                    "new_order": [weakest, node_id],
                }
        return {
            "action": "reorder",
            "node_id": node_id,
            "reason": "按最新掌握度重排学习顺序",
            "new_order": [node_id],
        }

    @staticmethod
    def _reflection(ctx) -> dict:
        s = ctx.get("stats", {})
        weak = s.get("weak", [])
        suggested = s.get("suggested", "")
        recent = s.get("recent", [])
        head = f"下次从「{suggested}」继续" if suggested else "下次继续学习"
        review = ("，先花几分钟回顾" + "、".join(recent)) if recent else ""
        return {
            "progress_summary": f"本次会话完成 {s.get('done', 0)} 个知识点，"
                                f"当前平均掌握度 {s.get('mean_theta', 0)}。",
            "effective_strategies": "脚手架提示逐级递进时，学生能在 L1~L2 阶段独立解出问题。",
            "plan_adjustments": "下一会话优先复习薄弱点。" + ("、".join(weak[:3]) if weak else ""),
            "next_session_preview": head + review,
        }

    @staticmethod
    def _greeting(ctx) -> str:
        preview = ctx.get("preview", "")
        if preview:
            return f"欢迎回来！{preview}"
        return ("你好！我是你的伴学智能体知途。"
                "我们先聊几句，了解一下你的基础和目标，"
                "然后做几道题，我就能为你定制一条学习路径。准备好了吗？")

    @staticmethod
    def _first_learn(ctx) -> str:
        name = ctx.get("name", "同学")
        return (f"{name}，欢迎使用知途伴学！你的学情诊断已经完成，"
                "接下来我们就开始个性化学习吧。")

    @staticmethod
    def _fallback(ctx) -> str:
        return "我明白你的意思了。我们继续按学习路径走，遇到困难随时告诉我。"
