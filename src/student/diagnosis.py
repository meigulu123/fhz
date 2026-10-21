"""学情诊断：自适应测验（主链锚点双向搜索）+ 诊断报告

主链：机器学习课程的核心进阶链。答对沿主链上跳（变难），答错下钻先修（变易），
用最少的题锁定学生水平边界；主链走完后转向前沿节点继续探测，直到题量上限。
终止条件：已做≥12 题 / 近 4 题对错交替（水平边界震荡）/ 题库耗尽 / 学生叫停。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.student.profile import cognitive_profile, is_untested
from src.student.question_filter import goals_to_tags, next_question_for_node

MAIN_CHAIN = ["b01", "s02", "s03", "e01", "e04", "d01", "d02", "d08"]
MAX_QUESTIONS = 12


@dataclass
class QuizState:
    current_node: str = MAIN_CHAIN[0]
    chain_idx: int = 0
    covered: set = field(default_factory=set)
    questions_asked: int = 0
    last_results: list = field(default_factory=list)  # 最近 4 题对错
    answers: list = field(default_factory=list)       # [(node_id, qid, correct, choice)]
    skipped: set = field(default_factory=set)         # 学生跳过的题 id（不计分、不计覆盖）
    finished: bool = False
    stop_reason: str = ""
    goal_tags: set = field(default_factory=set)      # 学生目标标签（出题筛选用）


class AdaptiveQuiz:
    """自适应测验引擎。构造参数：kg、题库列表（含 node_id 字段）。"""

    def __init__(self, kg, questions, main_chain=MAIN_CHAIN):
        self.kg = kg
        self.main_chain = main_chain
        self.qs_by_node = {}
        for q in questions:
            self.qs_by_node.setdefault(q["node_id"], []).append(q)

    def new_state(self, profile=None) -> QuizState:
        """创建新测验状态，可传入学生画像以启用目标筛选"""
        state = QuizState()
        if profile:
            state.goal_tags = goals_to_tags(profile)
        return state

    # ---------- 出题 ----------
    def next_question(self, state: QuizState) -> dict:
        """返回当前节点的一道未做过的题（按目标匹配度优先）；该节点无题/题用完则移动后递归"""
        used = {a[1] for a in state.answers} | state.skipped
        questions = self.qs_by_node.get(state.current_node, [])
        q = next_question_for_node(questions, state.goal_tags or {"general"}, used)
        if q:
            return q
        if self._move(state):
            return self.next_question(state)
        state.finished = True
        state.stop_reason = "题库耗尽"
        return {"id": None}

    # ---------- 作答记录 ----------
    def record(self, state: QuizState, question: dict, correct: bool,
               choice: str = "", theta_before: float | None = None,
               evidence_before: int | None = None):
        """记录一次作答：correct 供自适应判分，choice 为学生所选字母（回看用）。

        theta_before/evidence_before 为该节点作答前的画像值，供「回看改答」后重算。
        """
        state.answers.append((state.current_node, question["id"], correct, choice,
                              theta_before, evidence_before))
        state.questions_asked += 1
        state.covered.add(state.current_node)
        state.last_results.append(correct)
        if len(state.last_results) > 4:
            state.last_results.pop(0)
        self._move(state)
        self._check_stop(state)

    def stop(self, state: QuizState, reason: str = "学生叫停"):
        state.finished = True
        state.stop_reason = reason

    # ---------- 移动与终止 ----------
    def _move(self, state: QuizState) -> bool:
        """答对沿主链上跳、答错下钻先修；主链走完 / 无未覆盖先修时转向前沿节点"""
        if not state.last_results:
            return False
        correct = state.last_results[-1]
        if correct:
            if state.chain_idx + 1 < len(self.main_chain):
                state.chain_idx += 1
                state.current_node = self.main_chain[state.chain_idx]
                return True
        else:
            prereqs = self.kg.prereqs_of(state.current_node)
            uncovered = [p for p in prereqs if p not in state.covered]
            if uncovered:
                state.current_node = uncovered[0]
                return True
        return self._advance_frontier(state)

    def _advance_frontier(self, state: QuizState) -> bool:
        """兜底推进：选一个「未覆盖、先修已达标、且尚有余题」的前沿节点继续探测

        只在前两条规则都不适用时启用（主链走完 or 先修已全部覆盖），
        保证摸底能问到题量上限，覆盖到更多的知识点。
        """
        used = {a[1] for a in state.answers} | state.skipped
        best, best_diff = None, None
        for nid in self.kg.nodes:
            if nid in state.covered:
                continue
            qs = self.qs_by_node.get(nid, [])
            if not qs or all(q["id"] in used for q in qs):
                continue
            prereqs = self.kg.prereqs_of(nid)
            if prereqs and not set(prereqs) <= state.covered:
                continue
            diff = self.kg.nodes[nid].difficulty
            if best is None or diff < best_diff:
                best, best_diff = nid, diff
        if best is None:
            return False
        state.current_node = best
        return True

    def _check_stop(self, state: QuizState):
        if state.questions_asked >= MAX_QUESTIONS:
            state.finished, state.stop_reason = True, "达到题量上限"
        elif len(state.last_results) == 4:
            pat = state.last_results
            if pat[0] == pat[2] and pat[1] == pat[3] and pat[0] != pat[1]:
                state.finished, state.stop_reason = True, "水平边界震荡，诊断收敛"


# ---------- 诊断报告 ----------
def build_report(profile, kg, planner, quiz_state) -> dict:
    """诊断报告结构化数据（画像页/报告卡片/Mock 模板共用）"""
    band = planner.zpd_band(profile)
    # weak 优先取「本次摸底真正答错」的节点（按当前掌握度升序），无答错再回退低掌握度节点
    wrong_nodes = [a[0] for a in (quiz_state.answers if quiz_state else []) if not a[2]]
    uniq = list(dict.fromkeys(wrong_nodes))
    if uniq:
        weak = sorted(uniq, key=lambda nid: profile.mastery.get(nid, 0.5))[:5]
    else:
        weak = sorted((nid for nid, t in profile.mastery.items() if t < 0.4),
                      key=lambda nid: profile.mastery[nid])[:5]
    strong = sorted((nid for nid, t in profile.mastery.items() if t >= 0.75),
                    key=lambda nid: -profile.mastery[nid])[:5]
    plan = planner.plan(profile, batch=3)
    suggested = plan["items"][0]["node_id"] if plan["items"] else None
    corrects = sum(1 for a in quiz_state.answers if a[2]) if quiz_state else 0
    total = len(quiz_state.answers) if quiz_state else 0
    accuracy = round(corrects / total, 2) if total else 0.0
    return {
        "weak": [kg.nodes[n].name for n in weak],
        "strong": [kg.nodes[n].name for n in strong],
        "band": band,
        "suggested": kg.nodes[suggested].name if suggested else "",
        "covered": len(quiz_state.covered) if quiz_state else 0,
        "accuracy": accuracy,
        "correct": corrects,
        "wrong": max(total - corrects, 0),
        "total_questions": total,
        "stop_reason": quiz_state.stop_reason if quiz_state else "",
        "needs_review": [kg.nodes[n].name for n in list(profile.needs_review)[:5]],
        "cognitive": cognitive_profile(profile, kg),
    }


# ---------- 画像指标汇总（诊断报告生成用） ----------
def profile_metrics(profile, kg, mem) -> dict:
    """画像页全部指标的结构化汇总（六维能力/掌握度/ZPD/布鲁姆/行为数据）。

    gen_profile_report 与 MockLLM 规则兜底共用，保证两种模式下指标口径一致。
    """
    import statistics

    mastery = profile.mastery
    total_nodes = max(len(kg.nodes), 1)
    # 未测节点（无证据且未自述）不计入「已掌握/学习中」，避免零基础学生画像虚高
    tested = {nid: v for nid, v in mastery.items()
              if not is_untested(profile, nid)}
    mastered = sum(1 for v in tested.values() if v >= 0.75)
    learning = sum(1 for v in tested.values() if 0.05 < v < 0.75)
    knowledge = sum(mastery.values()) / max(len(mastery), 1)
    high = [v for nid, v in mastery.items()
            if kg.nodes.get(nid) is not None and kg.nodes[nid].bloom >= 4]
    logic = sum(high) / len(high) if high else 0.0
    qs = mem.quiz_stats(profile.student_id)
    accuracy = qs["correct"] / qs["total"] if qs["total"] else 0.0
    hits = mem.correct_by_node(profile.student_id)
    ev = [min(1.0, hits.get(nid, 0) / 8)
          for nid, v in mastery.items() if v >= 0.75]
    retention = sum(ev) / len(ev) if ev else 0.0
    effort = effort_score(mem, profile.student_id)
    cats = {}
    for nid, node in kg.nodes.items():
        cats.setdefault(node.category, []).append(mastery.get(nid, 0.0))
    cat_avg = {c: round(statistics.mean(v), 3) for c, v in cats.items()}
    best_cat = max(cat_avg, key=cat_avg.get) if cat_avg else "—"
    weak_nodes = sorted(
        (nid for nid, t in mastery.items() if t < 0.4),
        key=lambda nid: mastery[nid])[:5]
    strong_nodes = sorted(
        (nid for nid, t in mastery.items() if t >= 0.75),
        key=lambda nid: -mastery[nid])[:5]
    cog = cognitive_profile(profile, kg)
    wrong_names = [w.get("node_name") or "" for w in
                   mem.wrong_attempts(profile.student_id)][:10]
    return {
        "student_id": profile.student_id, "name": profile.name or "同学",
        "major": profile.major or "", "goals": list(profile.goals),
        "abilities": {
            "学习进度": round(mastered / total_nodes * 100),
            "知识掌握": round(knowledge * 100),
            "逻辑理解": round(logic * 100),
            "答题正确率": round(accuracy * 100),
            "记忆巩固": round(retention * 100),
            "学习投入": round(effort * 100),
        },
        "mastery": {
            "mean": round(knowledge, 3), "mastered": mastered,
            "learning": learning, "fresh": max(total_nodes - mastered - learning, 0),
            "total": total_nodes,
        },
        "categories": cat_avg,
        "strong_nodes": [kg.nodes[n].name for n in strong_nodes],
        "weak_nodes": [kg.nodes[n].name for n in weak_nodes],
        "best_category": best_cat,
        "weakest_category": min(cat_avg, key=cat_avg.get) if cat_avg else "—",
        "zpd": {"z_low": None, "z_high": None},  # 由调用方填 planner.zpd_band
        "bloom": {"level": cog["level"], "label": cog["label"]},
        "behavior": {
            "total_questions": qs["total"], "correct": qs["correct"],
            "wrong": qs["wrong"], "accuracy": round(accuracy, 3),
            "duration_sec": mem.total_duration(profile.student_id),
        },
        "needs_review": [kg.nodes[n].name
                         for n in list(profile.needs_review)[:5]],
        "wrong_topics": sorted({w for w in wrong_names if w})[:6],
    }


PROFILE_REPORT_PROMPT = """你是知途伴学智能体的学情诊断专家。请根据学生画像指标，
写一段 150~250 字的学情诊断，用 Markdown 分三小节：**学习优势**、**薄弱环节**、
**学习建议**。要求：
- 优势：结合掌握度高的知识点、六维能力中的高分项与答题正确率，具体到知识点；
- 薄弱：结合低掌握度节点、待复习节点、错题涉及的知识点与布鲁姆认知层级短板；
- 建议：结合 ZPD 带，给出可执行的学习路径建议（从哪个知识点入手、优先补哪类
  认知层级），再加一条行为建议（基于答题正确率与学习时长）；
- 语言像一位了解学生的老师，自然、具体、不写空话套话。"""


def gen_profile_report(llm, profile, kg, mem, band) -> str:
    """AI 学情诊断：真实 LLM 生成 / MockLLM 规则兜底（TPL:profile_report）"""
    import json
    from src.llm.base import sys, usr

    m = profile_metrics(profile, kg, mem)
    m["zpd"] = {"z_low": round(band.get("z_low", 0), 3),
                "z_high": round(band.get("z_high", 0), 3)}
    blob = json.dumps(m, ensure_ascii=False)
    # [stats_json=...] 是 MockLLM 的路由键，真实大模型视其为普通上下文
    messages = [sys("profile_report", PROFILE_REPORT_PROMPT),
                usr(f"[stats_json={blob}]")]
    # 诊断报告是重要生成场景：真实模式走大模型，Mock 模式走规则兜底
    return llm.chat(messages)


# ---------- 诊断置信度（画像页展示 + 提示补测） ----------
def node_confidence(profile, nid) -> int:
    """单知识点诊断置信度 0~100 = 证据充分度 × 判定明确度

    证据充分度：evidence_count / 3（3 次作答算充分）——只答 1 题的结论不可靠；
    判定明确度：θ 距 0.5 的距离 / 0.25——θ 越接近 0.5，「会 / 不会」越难判定。
    """
    n = profile.evidence_count.get(nid, 0)
    if n <= 0:
        return 0
    theta = profile.mastery.get(nid, 0.0)
    evidence = min(1.0, n / 3.0)
    decisive = min(1.0, abs(theta - 0.5) / 0.25)
    return int(round(100 * evidence * decisive))


def confidence_summary(profile, kg) -> dict:
    """置信度总览：低置信节点（有作答证据但判定不明确）清单，供画像页提示补测"""
    rows = {nid: node_confidence(profile, nid) for nid in kg.nodes}
    low = [nid for nid, c in rows.items()
           if c < 40 and profile.evidence_count.get(nid, 0) > 0]
    low.sort(key=lambda nid: rows[nid])
    return {"rows": rows, "low": low,
            "low_names": [kg.nodes[nid].name for nid in low[:6]]}


def proficiency(accuracy: float, avg_sec) -> float:
    """熟练度 0~1 = 正确率 × 速度系数（平均每题 ≤40 秒视为熟练，越慢系数越低）"""
    speed = 0.7 if not avg_sec else min(1.0, max(0.4, 40.0 / float(avg_sec)))
    return round(accuracy * speed, 3)


def effort_score(mem, student_id) -> float:
    """学习投入 0~1 = 答对题数 / 60（60 道答对算满）

    与其余五维保持同一口径：只有答对才会提升，答错与单纯挂机时长都不计入。
    六维雷达（components.ability_raw）与本函数必须同口径。
    """
    hits = mem.correct_by_node(student_id)
    return min(1.0, sum(hits.values()) / 60.0)
