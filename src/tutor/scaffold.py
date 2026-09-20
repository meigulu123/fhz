"""脚手架干预：卡住判定 + L0→L3 四级阶梯升级

卡住判定（OR）：连错≥2 / 近3轮正确率<1/3 / 困惑词典或 intent=confusion /
连续2轮求助。升级条件：提示后学生仍错/求助；答对退出并记录 hint_profile；
L3 变式仍错 → 触发重规划。

双通道设计：消息同时携带标记（[question_id=][level=]，Mock 路由键）与题目原文
（真实 LLM 的干预素材）——Mock 只读标记从题库取 hints，真实 LLM 基于题目生成提示。
"""
from dataclasses import dataclass, field

LEVELS = ["L0", "L1", "L2", "L3"]
CONFUSION_WORDS = ["不会", "不懂", "卡住", "太难", "怎么办", "怎么做", "帮帮我",
                   "求助", "想不出来", "看不懂", "help"]


@dataclass
class ScaffoldState:
    active: bool = False
    level: int = 0               # 0~3 对应 L0~L3
    question_id: str = ""
    node_id: str = ""
    wrong_streak: int = 0        # 当前题连错次数
    help_streak: int = 0         # 连续求助次数
    last3: list = field(default_factory=list)   # 近 3 题对错
    variant_tried: bool = False  # L3 变式题是否已做过

    def reset(self):
        self.active = False
        self.level = 0
        self.question_id = ""
        self.node_id = ""
        self.wrong_streak = 0
        self.help_streak = 0
        self.last3 = []
        self.variant_tried = False


def detect_stuck(state: ScaffoldState, intent: str, text: str,
                 last_results: list) -> bool:
    """卡住判定（OR 信号）"""
    if intent == "confusion":
        return True
    if any(w in text for w in CONFUSION_WORDS):
        return True
    if state.wrong_streak >= 2:
        return True
    recent = last_results[-3:]
    if len(recent) == 3 and sum(1 for c in recent if c) / 3 < 1 / 3:
        return True
    if state.help_streak >= 2:
        return True
    return False


class Scaffolder:
    """脚手架控制器：依赖 llm（TPL:scaffold）与题库数据（真实 LLM 模式注入题目原文）"""

    def __init__(self, llm, questions=None, mem=None):
        self.llm = llm
        self.qbank = {q["id"]: q for q in questions or []}
        self.mem = mem

    def engage(self, state: ScaffoldState, question_id: str, node_id: str) -> dict:
        """首次卡住：进入 L0"""
        state.active = True
        state.level = 0
        state.question_id = question_id
        state.node_id = node_id
        state.wrong_streak = 0
        state.help_streak = 0
        state.variant_tried = False
        return self.hint(state)

    def hint(self, state: ScaffoldState) -> dict:
        """当前层级提示内容"""
        level = LEVELS[state.level]
        q = self.qbank.get(state.question_id, {})
        user = f"[question_id={state.question_id}][level={level}]"
        if q:
            opts = "\n".join(q.get("options", []))
            user += f"\n【题目原文】\n{q.get('stem', '')}\n{opts}\n"
            hint_text = (q.get("hints") or {}).get(level, "")
            if hint_text:
                user += (f"\n【本题{level}参考提示，请在此基础上引导，"
                         f"不超范围、不公布答案】\n{hint_text}\n")
        messages = [
            {"role": "system", "content": "[TPL:scaffold]\n你是伴学导师，进行脚手架式辅导，"
                                          "按层级给学生提示，不直接给答案；"
                                          "若给出参考提示，请在其基础上改写，不要超出范围。"},
            {"role": "user", "content": user},
        ]
        text = self.llm.chat(messages)
        return {"level": level, "text": text, "replan": False}

    def escalate(self, state: ScaffoldState) -> dict:
        """学生仍错/求助 → 升级一级；已在 L3 则返回 replan 信号"""
        if state.level >= 3:
            return {"level": "L3", "text": None, "replan": True}
        state.level += 1
        return self.hint(state)

    def on_wrong(self, state: ScaffoldState) -> dict:
        state.wrong_streak += 1
        if state.active:
            return self.escalate(state)
        return {"level": "L0", "text": None, "replan": False}

    def on_help(self, state: ScaffoldState) -> dict:
        state.help_streak += 1
        if state.active:
            return self.escalate(state)
        return {"level": "L0", "text": None, "replan": False}

    def on_correct(self, state: ScaffoldState, profile) -> None:
        """答对退出：记录 hint_profile（该节点最终退出层级）"""
        if state.active and state.node_id:
            profile.hint_profile[state.node_id] = state.level
        state.reset()
