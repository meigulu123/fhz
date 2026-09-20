"""Agent 状态机：FSM 相位 + 可序列化会话状态（Streamlit session_state 持久化）

AgentState 运行期持有活动对象（StudentProfile/QuizState/ScaffoldState），
to_dict/from_dict 提供完整序列化（探针页验证 rerun 后状态不丢）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.student.diagnosis import QuizState
from src.student.profile import StudentProfile
from src.tutor.scaffold import ScaffoldState

# FSM 相位
IDLE = "idle"
DIAGNOSING = "diagnosing"
QUIZZING = "quizzing"
TEACHING = "teaching"
INTERVENING = "intervening"
REFLECTING = "reflecting"
PRACTICING = "practicing"

PHASE_LABELS = {
    IDLE: "等待开始", DIAGNOSING: "学情诊断", QUIZZING: "自适应测验",
    TEACHING: "教学讲解", INTERVENING: "脚手架干预", REFLECTING: "会话反思",
    PRACTICING: "自主练习",
}


def _quiz_to_dict(qs: QuizState | None) -> dict | None:
    if qs is None:
        return None
    return {
        "current_node": qs.current_node, "chain_idx": qs.chain_idx,
        "covered": sorted(qs.covered), "questions_asked": qs.questions_asked,
        "last_results": list(qs.last_results),
        "answers": [list(a) for a in qs.answers],
        "finished": qs.finished, "stop_reason": qs.stop_reason,
        "goal_tags": list(qs.goal_tags),
    }


def _quiz_from_dict(d: dict | None) -> QuizState | None:
    if d is None:
        return None
    qs = QuizState()
    qs.current_node = d["current_node"]
    qs.chain_idx = d["chain_idx"]
    qs.covered = set(d.get("covered", []))
    qs.questions_asked = d["questions_asked"]
    qs.last_results = list(d.get("last_results", []))
    qs.answers = [tuple(a) for a in d.get("answers", [])]
    qs.finished = d["finished"]
    qs.stop_reason = d.get("stop_reason", "")
    qs.goal_tags = set(d.get("goal_tags", []))
    return qs


@dataclass
class AgentState:
    """单会话完整状态；全部字段可序列化"""
    student_id: str
    phase: str = IDLE
    diagnosis_step: int = 0
    profile: StudentProfile | None = None
    quiz_state: QuizState | None = None
    plan: dict = field(default_factory=dict)
    plan_idx: int = 0
    current_node: str = ""
    lecture_para: int = 0
    current_question: dict | None = None   # 当前待答题目（或变式题）
    scaffold: ScaffoldState = field(default_factory=ScaffoldState)
    last_results: list = field(default_factory=list)   # 近 8 次作答对错
    done_nodes: list = field(default_factory=list)
    interaction_count: int = 0
    session_id: int = 0
    report: dict = field(default_factory=dict)
    memory_ctx: str = ""                # 本轮检索到的跨会话记忆上下文
    history: list = field(default_factory=list)        # 对话记录（UI 渲染）
    used_qids: list = field(default_factory=list)      # 本会话已出过的题目 id
    practice_node: str = ""                            # 自主练习目标节点（独立于 current_node）
    resume_phase: str = ""                             # 进入练习前的相位，退出时恢复
    _milestones_done: set = field(default_factory=set)  # 已达成的里程碑 id 集合（不序列化）

    def to_dict(self) -> dict:
        sc = self.scaffold.__dict__.copy() if self.scaffold else {}
        return {
            "student_id": self.student_id, "phase": self.phase,
            "diagnosis_step": self.diagnosis_step,
            "profile": self.profile.to_dict() if self.profile else None,
            "quiz_state": _quiz_to_dict(self.quiz_state),
            "plan": self.plan, "plan_idx": self.plan_idx,
            "current_node": self.current_node, "lecture_para": self.lecture_para,
            "current_question": self.current_question,
            "scaffold": sc,
            "last_results": list(self.last_results),
            "done_nodes": list(self.done_nodes),
            "interaction_count": self.interaction_count,
            "session_id": self.session_id, "report": self.report,
            "memory_ctx": self.memory_ctx,
            "history": list(self.history),
            "used_qids": list(self.used_qids),
            "practice_node": self.practice_node,
            "resume_phase": self.resume_phase,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentState":
        d = dict(d)
        state = cls(student_id=d["student_id"], phase=d.get("phase", IDLE))
        state.diagnosis_step = d.get("diagnosis_step", 0)
        state.profile = StudentProfile.from_dict(d["profile"]) if d.get("profile") else None
        state.quiz_state = _quiz_from_dict(d.get("quiz_state"))
        state.plan = d.get("plan", {})
        state.plan_idx = d.get("plan_idx", 0)
        state.current_node = d.get("current_node", "")
        state.lecture_para = d.get("lecture_para", 0)
        state.current_question = d.get("current_question")
        sc = ScaffoldState()
        sc.__dict__.update(d.get("scaffold", {}))
        state.scaffold = sc
        state.last_results = list(d.get("last_results", []))
        state.done_nodes = list(d.get("done_nodes", []))
        state.interaction_count = d.get("interaction_count", 0)
        state.session_id = d.get("session_id", 0)
        state.report = d.get("report", {})
        state.memory_ctx = d.get("memory_ctx", "")
        state.history = list(d.get("history", []))
        state.used_qids = list(d.get("used_qids", []))
        state.practice_node = d.get("practice_node", "")
        state.resume_phase = d.get("resume_phase", "")
        return state

    def reset_for_new_session(self):
        """同一学生开新会话：保留 profile，清空会话级状态"""
        self.phase = IDLE
        self.diagnosis_step = 0
        self.quiz_state = None
        self.plan = {}
        self.plan_idx = 0
        self.current_node = ""
        self.lecture_para = 0
        self.current_question = None
        self.scaffold.reset()
        self.last_results = []
        self.done_nodes = []
        self.interaction_count = 0
        self.session_id = 0
        self.report = {}
        self.memory_ctx = ""
        self.used_qids = []
        self.practice_node = ""
        self.resume_phase = ""
