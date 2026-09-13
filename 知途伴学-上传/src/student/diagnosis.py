"""学情诊断：自适应测验（主链锚点双向搜索）+ 诊断报告

主链：机器学习课程的核心进阶链。答对沿主链上跳（变难），答错下钻先修（变易），
用最少的题锁定学生水平边界。
终止条件：覆盖≥6 主链节点 / 已做≥12 题 / 近 4 题对错交替（水平边界震荡）/
题库耗尽 / 学生叫停。
"""
from dataclasses import dataclass, field

from src.student.profile import cognitive_profile

MAIN_CHAIN = ["b01", "s02", "s03", "e01", "e04", "d01", "d02", "d08"]
MAX_QUESTIONS = 12
MIN_COVERED = 6


@dataclass
class QuizState:
    current_node: str = MAIN_CHAIN[0]
    chain_idx: int = 0
    covered: set = field(default_factory=set)
    questions_asked: int = 0
    last_results: list = field(default_factory=list)  # 最近 4 题对错
    answers: list = field(default_factory=list)       # [(node_id, qid, correct)]
    finished: bool = False
    stop_reason: str = ""


class AdaptiveQuiz:
    """自适应测验引擎。构造参数：kg、题库列表（含 node_id 字段）。"""

    def __init__(self, kg, questions, main_chain=MAIN_CHAIN):
        self.kg = kg
        self.main_chain = main_chain
        self.qs_by_node = {}
        for q in questions:
            self.qs_by_node.setdefault(q["node_id"], []).append(q)

    def new_state(self) -> QuizState:
        return QuizState()

    # ---------- 出题 ----------
    def next_question(self, state: QuizState) -> dict:
        """返回当前节点的一道未做过的题；该节点无题/题用完则移动后递归"""
        used = {a[1] for a in state.answers}
        for q in self.qs_by_node.get(state.current_node, []):
            if q["id"] not in used:
                return q
        if self._move(state):
            return self.next_question(state)
        state.finished = True
        state.stop_reason = "题库耗尽"
        return {"id": None}

    # ---------- 作答记录 ----------
    def record(self, state: QuizState, question: dict, correct: bool):
        state.answers.append((state.current_node, question["id"], correct))
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
        """答对沿主链上跳、答错下钻先修；返回是否发生了移动"""
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
        return False

    def _check_stop(self, state: QuizState):
        if state.questions_asked >= MAX_QUESTIONS:
            state.finished, state.stop_reason = True, "达到题量上限"
        elif len(state.covered) >= MIN_COVERED:
            state.finished, state.stop_reason = True, "已覆盖足够知识点"
        elif len(state.last_results) == 4:
            pat = state.last_results
            if pat[0] == pat[2] and pat[1] == pat[3] and pat[0] != pat[1]:
                state.finished, state.stop_reason = True, "水平边界震荡，诊断收敛"


# ---------- 诊断报告 ----------
def build_report(profile, kg, planner, quiz_state) -> dict:
    """诊断报告结构化数据（画像页/报告卡片/Mock 模板共用）"""
    band = planner.zpd_band(profile)
    weak = sorted((nid for nid, t in profile.mastery.items() if t < 0.4),
                  key=lambda nid: profile.mastery[nid])[:5]
    strong = sorted((nid for nid, t in profile.mastery.items() if t >= 0.75),
                    key=lambda nid: -profile.mastery[nid])[:5]
    plan = planner.plan(profile, batch=3)
    suggested = plan["items"][0]["node_id"] if plan["items"] else None
    corrects = sum(1 for _, _, c in quiz_state.answers if c) if quiz_state else 0
    total = len(quiz_state.answers) if quiz_state else 0
    accuracy = round(corrects / total, 2) if total else 0.0
    return {
        "weak": [kg.nodes[n].name for n in weak],
        "strong": [kg.nodes[n].name for n in strong],
        "band": band,
        "suggested": kg.nodes[suggested].name if suggested else "",
        "covered": len(quiz_state.covered) if quiz_state else 0,
        "accuracy": accuracy,
        "total_questions": total,
        "stop_reason": quiz_state.stop_reason if quiz_state else "",
        "needs_review": [kg.nodes[n].name for n in list(profile.needs_review)[:5]],
        "cognitive": cognitive_profile(profile, kg),
    }
