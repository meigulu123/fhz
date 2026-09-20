"""自然对话风格模块：多样化回复模板，减少机械感

每个场景提供多种说法，随机选择，让对话更像真人老师。
"""
import random
from typing import List


# ---------- 答对反馈 ----------
CORRECT_REPLIES = [
    "回答正确！思路很清晰。",
    "太棒了，答对了！这个点掌握得不错。",
    "没错！你理解得很到位。",
    "正确！看来这块你已经吃透了。",
    "答对了！继续保持这个节奏。",
    "漂亮！完全正确，思路很顺。",
    "对的！你已经掌握这个知识点了。",
]

# ---------- 答错反馈 ----------
WRONG_REPLIES = [
    "答错了也没关系，先不公布答案——我们一起来找思路：",
    "这道题确实有点绕，我们一起拆解一下：",
    "没关系，错了正好暴露问题。我们一步步来：",
    "差一点点！我们重新理一理思路：",
    "不对哦，不过没关系——现在搞懂比什么都重要：",
    "这道题踩坑很正常，我们一起看看问题出在哪：",
]

# ---------- 卡住安慰 ----------
STUCK_REASSURE = [
    "没关系，我们放慢一点，我来带你一步步想。",
    "别急，这道题确实有难度，我们慢慢理。",
    "卡住很正常，我来给你搭个台阶，我们一步步走。",
    "没问题，这种题第一次见都容易懵，我来引导你。",
]

# ---------- 节点完成鼓励 ----------
NODE_DONE_PRAISE = [
    "回答正确！思路很清晰。",
    "太棒了！这个知识点你已经完全掌握了。",
    "漂亮！恭喜你拿下这个知识点。",
    "完美！你对这个点的理解很扎实。",
    "很好！这个知识点学到位了。",
]

# ---------- 诊断开场白 ----------
GREETING_NEW = [
    "你好！我是你的伴学智能体知途。"
    "我们先聊几句，了解一下你的基础和目标，"
    "然后做几道题，我就能为你定制一条学习路线。准备好了吗？",

    "嗨！很高兴认识你～ 我是知途，你的专属AI学习伙伴。"
    "先简单聊几句，让我了解你的情况，这样才能帮你学得更高效。"
    "咱们开始吧？",

    "你好呀！我是知途伴学，专门帮你量身定制学习计划的。"
    "花两分钟做个小诊断，之后我就能给你安排最适合的学习路径。"
    "准备好了就告诉我吧～",
]

# ---------- 欢迎回来 ----------
WELCOME_BACK = [
    "欢迎回来！",
    "好久不见！",
    "你回来啦～",
    "又见到你了！",
]

# ---------- 测验开始 ----------
QUIZ_START = [
    "好的，你的情况我记下了！接下来做几道题，看看你的真实水平分布——"
    "答错没关系，题目会自动跟着你的表现调整难度。",

    "了解了！接下来我们做几道小测试，不用紧张，"
    "题目会根据你的答题情况自动调整难度，就是为了摸清楚你的真实水平。",

    "好嘞！现在进入摸底环节，几道题而已，轻松答就行。"
    "答对了说明这块没问题，答错了正好帮我们找到需要补的地方。",
]

# ---------- 诊断确认 ----------
DIAGNOSIS_CONFIRM = [
    "我已经了解你的情况啦！先跟你确认一下：",
    "好的，我整理了一下你的信息，你看看对不对：",
    "我大概掌握你的情况了，咱们对一下：",
]

# ---------- 路径开始 ----------
PATH_BEGIN = [
    "我们从「{name}」开始",
    "接下来我们学「{name}」",
    "第一个知识点是「{name}」",
    "好，先来啃「{name}」这块硬骨头～",
]

# ---------- 讲义继续 ----------
CONTINUE_LECTURE = [
    "好的，我们继续往下看：",
    "接着往下讲：",
    "好，继续下一部分：",
    "我们接着说：",
]

# ---------- 题完反馈 ----------
ALL_QUESTIONS_DONE = [
    "这个知识点你已经练完啦！",
    "太棒了，这个节点的题都做完了！",
    "好样的，这个知识点的练习全部完成了！",
]

# ---------- 批次完成 ----------
BATCH_COMPLETE = [
    "这一批学习计划全部完成！",
    "恭喜！这一批知识点都拿下了！",
    "太棒了！本批学习目标达成！",
]


def pick(templates: List[str]) -> str:
    """从模板列表中随机选一个"""
    return random.choice(templates)


def correct_reply() -> str:
    """答对反馈"""
    return pick(CORRECT_REPLIES)


def wrong_reply() -> str:
    """答错反馈"""
    return pick(WRONG_REPLIES)


def stuck_reassure() -> str:
    """卡住安慰"""
    return pick(STUCK_REASSURE)


def node_done_praise() -> str:
    """节点完成鼓励"""
    return pick(NODE_DONE_PRAISE)


def greeting_new() -> str:
    """新学生开场白"""
    return pick(GREETING_NEW)


def welcome_back() -> str:
    """欢迎回来"""
    return pick(WELCOME_BACK)


def quiz_start() -> str:
    """测验开始"""
    return pick(QUIZ_START)


def diagnosis_confirm() -> str:
    """诊断确认"""
    return pick(DIAGNOSIS_CONFIRM)


def path_begin(node_name: str) -> str:
    """路径开始"""
    template = pick(PATH_BEGIN)
    return template.format(name=node_name)


def continue_lecture() -> str:
    """讲义继续"""
    return pick(CONTINUE_LECTURE)


def all_questions_done() -> str:
    """题目做完"""
    return pick(ALL_QUESTIONS_DONE)


def batch_complete() -> str:
    """批次完成"""
    return pick(BATCH_COMPLETE)
