"""MockLLM：规则路由的离线兜底大模型。

同一套 OpenAI 风格接口，无网无 Key 时由规则从真实知识库（讲义/题库 hints/
模板报告）取内容拼回答——知识是真的，生成环节由规则替代。所有输出确定性、
可离线、可 pytest 回归。真实 LLM 模式与 Mock 模式的接口契约完全一致。
"""
import json
import re

from .base import BaseLLM
from src.student.error_cause import cause_probe
from src.student.question_gen import rule_question

CONFUSION_WORDS = [
    "不会", "不懂", "卡住", "卡了", "太难", "怎么办", "怎么做", "帮帮我",
    "求助", "想不出来", "想不通", "蒙了", "help", "不会做", "看不懂",
]
GOAL_WORDS = ["想学", "目标", "换一个", "换目标", "重点学", "我要学", "改学", "想先学"]
PRACTICE_WORDS = ["练习", "做题", "刷题", "做几道", "出几道", "来几道", "练一练",
                  "练一下", "测一测", "出题", "做做题", "巩固题", "再练", "几道题",
                  "练几道", "再来几道"]
# 「换个讲法 / 举个例子」等快捷动作归入提问类，由问答链路重新讲解当前知识点
QUESTION_WORDS = ["为什么", "什么是", "是什么", "什么意思", "区别", "怎么理解", "？", "?",
                  "换个讲法", "换一种讲法", "换种讲法", "举个例子", "举例子", "生活例子"]
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
            "profile_report": lambda: self._profile_report(ctx),
            "quiz_feedback": lambda: self._quiz_feedback(ctx),
            "replan": lambda: json.dumps(self._replan(ctx), ensure_ascii=False),
            "reflection": lambda: json.dumps(self._reflection(ctx), ensure_ascii=False),
            "greeting": lambda: self._greeting(ctx),
            "first_learn": lambda: self._first_learn(ctx),
            "qa": lambda: self._qa(ctx),
            "plan_initial": lambda: json.dumps(self._plan_initial(ctx), ensure_ascii=False),
            "profile_observe": lambda: json.dumps(self._profile_observe(ctx), ensure_ascii=False),
            "gen_question": lambda: json.dumps(self._gen_question(ctx), ensure_ascii=False),
        }
        fn = router.get(tpl)
        if fn:
            return fn()
        return self._fallback(ctx)

    def chat_json(self, messages) -> dict:
        tpl = self._tpl(messages)
        if tpl in ("intent", "replan", "reflection", "plan_initial",
                   "profile_observe", "gen_question"):
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
                    "user_answer", "answer", "preview", "name", "cause", "variant"):
            m = re.search(rf"\[{key}=([^\]]*)\]", blob)
            if m:
                ctx[key] = m.group(1)
        # JSON 标记用 raw_decode 解析，嵌套对象不会被正则截断
        for key, default in (("stats_json", {}), ("candidates_json", []),
                             ("band_json", {})):
            m = re.search(rf"\[{key}=\s*(.*)", blob, re.S)
            if not m:
                continue
            try:
                ctx[key[:-5]], _ = json.JSONDecoder().raw_decode(m.group(1).lstrip())
            except json.JSONDecodeError:
                ctx[key[:-5]] = default
        ctx["blob"] = blob
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
        """按 [question_id=][level=] 从题库 hints 取脚手架内容；
        带 [cause=] 时按错因追加靶向反问（不同错因问不同的问题）"""
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
        cause = ctx.get("cause", "")
        if cause and level == "L0":
            return (f"你的卡点偏「{cause}」，先回答我一个问题：{cause_probe(cause)}\n\n"
                    f"{prefix}{text}")
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
        """按 [node=] 取节点，结合学生画像与提问给出解答（名称概述 + 讲义正文首段）

        离线模式下「动态」体现为：命中节点不同→内容不同；学生画像中的目标/基础
        不同→开场与延伸建议不同。
        """
        node = self.kg.nodes.get(ctx.get("node", ""))
        if node is None:
            return self._fallback(ctx)
        blob = ctx.get("blob", "")
        goal_m = re.search(r"学习目标：([^；\n]+)", blob)
        goal = goal_m.group(1).strip() if goal_m else ""
        topics = re.findall(r"【知识点\d+】([^\n]+)", blob)
        names = "、".join(dict.fromkeys(topics)) or node.name
        lines = [f"关于「{names}」——{node.name}：{node.summary}" if names != node.name
                 else f"「{node.name}」{node.summary}"]
        if node.lecture:
            body = [b.strip() for b in node.lecture.split("\n\n")
                    if b.strip() and not b.startswith("[ASK:]")]
            if body:
                lines.append(body[0])
        if goal:
            lines.append(f"结合你「{goal}」的学习目标，这块内容是绕不开的基础，"
                         "建议先弄清它解决的问题，再去看它在模型里的具体用法。")
        lines.append("想深入哪一块，或者要我换个说法，直接说就行。")
        return "\n\n".join(lines)

    def _fallback(self, ctx) -> str:
        """未命中路由时的兜底回复：结合当前知识点，避免千篇一律的机械回应"""
        node = self.kg.nodes.get(ctx.get("node", ""))
        if node is not None:
            return (f"我们在「{node.name}」这里，我建议顺着当前路径继续；"
                    f"如果这一步没讲透，你可以直接问「什么是{node.name}」，我换个说法讲。")
        return ("我记下了。我们可以顺着你的学习路径继续推进——"
                "想换个方向就说「我想学 XX」，卡住了就说「我不会」，我来带你一步步想。")

    @staticmethod
    def _diag_report(ctx) -> str:
        s = ctx.get("stats", {})
        weak = "、".join(s.get("weak", [])[:5]) or "无"
        strong = "、".join(s.get("strong", [])[:5]) or "待继续观察"
        band = s.get("band", {})
        total = s.get("total_questions", 0)
        correct = s.get("correct", 0)
        wrong = s.get("wrong", max(total - correct, 0))
        acc = round((s.get("accuracy") or 0) * 100)
        if total:
            score_line = (f"本次摸底共 {total} 题：答对 {correct} 道、"
                          f"答错 {wrong} 道（正确率 {acc}%）。")
        else:
            score_line = "本次摸底你没有作答，先跳过计分。"
        lines = [
            f"{s.get('name', '同学')}，你的学情诊断完成啦！",
            score_line,
            f"诊断覆盖 {s.get('covered', 0)} 个知识点。",
            f"掌握较好：{strong}。",
            f"需要加强：{weak}。",
            f"你的最近发展区（ZPD）位于掌握度 {band.get('z_low', '-')} ~ "
            f"{band.get('z_high', '-')} 之间，",
            f"建议从「{s.get('suggested', '')}」开始学习。",
            "已为你生成个性化学习路径，去『学习路径』页看看吧。",
        ]
        return "\n".join(lines)

    @staticmethod
    def _profile_report(ctx) -> str:
        """画像页 AI 学情诊断规则兜底：三段文字全部取自真实指标"""
        s = ctx.get("stats", {})
        ab = s.get("abilities", {})
        beh = s.get("behavior", {})
        z = s.get("zpd", {}) or {}
        name = s.get("name", "同学")
        strong = "、".join(s.get("strong_nodes", [])[:3]) or "暂无明确优势节点"
        weak = "、".join(s.get("weak_nodes", [])[:3]) or "暂无"
        review = "、".join(s.get("needs_review", [])[:3]) or "无"
        wrong = "、".join(s.get("wrong_topics", [])[:3]) or "无"
        high_dims = sorted(ab.items(), key=lambda kv: -kv[1])[:2]
        high_txt = "、".join(f"{k}（{v}分）" for k, v in high_dims) if ab else "—"
        best_cat = s.get("best_category", "—")
        zl, zh = z.get("z_low", 0), z.get("z_high", 0)
        mean = s.get("mastery", {}).get("mean", 0)
        bloom = s.get("bloom", {}) or {}
        dur_min = int(beh.get("duration_sec", 0) // 60)
        acc = round((beh.get("accuracy") or 0) * 100)
        start = weak.split("、")[0] if weak != "暂无" else (
            "基础知识薄弱的环节（见知识点掌握度表）")
        lines = [
            f"**学习优势**：{name}，你在 {best_cat} 类知识点上掌握扎实（{strong}），"
            f"六维能力中 {high_txt} 表现突出，答题正确率 {acc}%。",
            f"**薄弱环节**：{weak} 等节点掌握度低于 0.4，且布鲁姆认知层级当前约 "
            f"L{int(round(bloom.get('level', 0))) or '—'}，高阶认知（分析/评价/创造）"
            f"仍需加强；近期错题集中在 {wrong}，待复习 {review}。",
            f"**学习建议**：你的 ZPD 带为 {zl}~{zh}（当前平均掌握度 {round(mean, 2)}），"
            f"建议从「{start}」入手，优先补低层级概念再做高层级变式题；"
            f"累计学习 {dur_min} 分钟，保持每日 30 分钟以上的练习节奏，"
            f"配合错题本每周回顾一次。",
        ]
        return "\n\n".join(lines)

    # ---------- 画像驱动的路径定序（离线也「动态」） ----------
    def _plan_initial(self, ctx) -> dict:
        """离线路径定序：读学情统计与候选清单，输出个性化学习顺序 + 逐条理由。

        与真实大模型的 [TPL:plan_initial] 契约一致（{"items":[{node_id,reason}],
        "notes":...}）：公式已保证先修达标与 ZPD 带内，这里做「学习顺序」适配——
        先回补薄弱先修（复习档），再按难度由易到难主修；理由逐条引用学生自身数据
        （掌握度 / 难度 / ZPD 带 / 学习目标 / 正确率），避免千篇一律的套话。
        """
        stats = ctx.get("stats") or {}
        cands = [c for c in (ctx.get("candidates") or [])
                 if isinstance(c, dict) and c.get("node_id")]
        if not cands:
            return {"items": [], "notes": ""}
        band = ctx.get("band") or stats.get("band") or {}
        zl, zh = band.get("z_low"), band.get("z_high")
        weak = set(stats.get("weak") or [])
        goal_nodes = set(stats.get("goal_nodes") or [])
        goals = stats.get("goals") or []
        goal = goals[0] if goals else ""
        # 学习顺序：复习档（回补薄弱先修）优先，其余按难度由易到难
        ordered = sorted(cands, key=lambda it: (0 if it.get("tier") == "复习" else 1,
                                                float(it.get("difficulty") or 0.0)))
        items = [{"node_id": it["node_id"],
                  "reason": self._plan_reason(it, weak, goal_nodes, goal, zl, zh)}
                 for it in ordered]
        return {"items": items,
                "notes": self._plan_notes(len(items), zl, zh, stats, goal)}

    @staticmethod
    def _plan_reason(it, weak, goal_nodes, goal, zl, zh) -> str:
        name = it.get("name", "")
        m = it.get("mastery")
        d = it.get("difficulty")
        if it.get("tier") == "复习":
            return (f"「{name}」难度 {d} 低于你当前的 ZPD 带（{zl}~{zh}），当前掌握度 {m}，"
                    f"作为复习巩固项排在最前，把这块基础补齐，后面更难的内容才接得上。")
        if name in goal_nodes and goal:
            return (f"「{name}」和你的目标「{goal}」直接相关，难度 {d} 恰好落在你的"
                    f"最近发展区 {zl}~{zh} 内，是这一批的主攻点。")
        if name in weak:
            return (f"「{name}」是你目前偏薄弱的一环（掌握度 {m}），难度 {d} 在你够得着的"
                    f"区间内，趁热打铁补上。")
        return (f"「{name}」难度 {d} 落在你的最近发展区 {zl}~{zh} 内，"
                f"当前掌握度 {m}，由易到难推进到这里最合适。")

    @staticmethod
    def _plan_notes(count, zl, zh, stats, goal) -> str:
        acc = stats.get("accuracy")
        if (stats.get("covered") or 0) and isinstance(acc, (int, float)):
            if acc >= 0.8:
                rhythm = "你的正确率不错，节奏可以稍快一点"
            elif acc < 0.5:
                rhythm = f"摸底正确率只有 {round(acc * 100)}%，节奏放慢、每一步都打牢"
            else:
                rhythm = "节奏保持适中，学练结合"
        else:
            rhythm = "先按中性节奏推进，答对会自动加快"
        goal_txt = f"围绕你的目标「{goal}」" if goal else "围绕你当前的学情"
        return (f"本批 {count} 个知识点按「先回补薄弱先修 → 再由易到难主修」排序，"
                f"{goal_txt}，难度控制在最近发展区 {zl}~{zh} 内；{rhythm}。")

    @staticmethod
    def _profile_observe(ctx) -> dict:
        """画像观察规则兜底（离线 Mock）：由学情统计确定性生成，但逐条引用真实数据"""
        s = ctx.get("stats") or {}
        name = s.get("name") or "同学"
        done = s.get("done", 0)
        acc = s.get("accuracy") or 0
        weak = s.get("weak") or []
        strong = s.get("strong") or []
        last = s.get("last_done") or ""
        tags = []
        if acc >= 0.8:
            tags.append("答题节奏稳定")
        elif acc and acc < 0.5:
            tags.append("基础需巩固")
        if strong:
            tags.append("偏好例题巩固")
        bits = [f"{name}本次已完成 {done} 个知识点"]
        if last:
            bits.append(f"最近拿下的是「{last}」")
        if strong:
            bits.append(f"在「{strong[0]}」上表现扎实")
        if weak:
            bits.append(f"「{weak[0]}」一带还不稳定")
        if acc:
            bits.append(f"近期答题正确率约 {round(acc * 100)}%")
        return {"style_tags_add": tags[:2], "goals_update": None,
                "observation": "，".join(bits) + "。"}

    def _gen_question(self, ctx) -> dict:
        """动态出题规则兜底（离线）：委托 question_gen.rule_question

        用知识点真实内容组题（正确项=节点概述，干扰项=同类节点概述），确定性、
        可回归；[variant=] 让多次生成在答案位置与干扰项上轮转，避免重复。
        """
        try:
            variant = int(ctx.get("variant", 0) or 0)
        except (TypeError, ValueError):
            variant = 0
        q = rule_question(self.kg, ctx.get("node", ""), variant=variant)
        if q is None:
            return {"error": "无法为该知识点生成题目"}
        return q

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
            "adjust": MockLLM._reflection_adjust(s, weak),
        }

    @staticmethod
    def _reflection_adjust(stats, weak) -> dict:
        """结构化调整（离线规则）：让「反思」能真正被下一次会话执行

        review_nodes 取学情统计中掌握度最低的知识点 ID（stats.prereqs 是全体
        知识点的 θ 表），pace_hint 由本次正确率决定。
        """
        prereqs = stats.get("prereqs") or {}
        review_nodes = sorted((nid for nid in prereqs),
                              key=lambda nid: prereqs[nid])[:2]
        acc = stats.get("accuracy")
        if isinstance(acc, (int, float)) and stats.get("total_questions"):
            pace_hint = "slow" if acc < 0.5 else ("fast" if acc >= 0.8 else "keep")
        else:
            pace_hint = "keep"
        bits = ["下次先回补薄弱环节"]
        if weak:
            bits.append("（" + "、".join(weak[:2]) + "）")
        if pace_hint == "slow":
            bits.append("，节奏放缓、先把基础打牢")
        elif pace_hint == "fast":
            bits.append("，节奏可适当加快")
        return {"review_nodes": review_nodes, "pace_hint": pace_hint,
                "note": "".join(bits)}

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
