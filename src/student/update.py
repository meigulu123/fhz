"""掌握度更新：BKT 简化 + Elo 自适应学习率 + 先修传播 + 遗忘衰减

全系统数值核心。所有更新必须经本模块，保证画像与路径一致。
"""
import math


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


K_QUIZ = 0.18          # 测验硬证据的基础学习率
K_DIALOG = 0.09        # 对话软证据的基础学习率（约为测验的一半）
FIRST_EVIDENCE_BOOST = 3.0   # 首个证据的放大系数


def learning_rate(n: int, kind: str = "quiz") -> float:
    """单次作答的学习率 k(n)。

    - Elo 自适应：证据越多越保守，k = k_base·3/(n+3)。
    - 首个证据放大：n==0（该节点此前毫无观测）时一次作答对 θ 的修正最大。
      未测节点的初始化先验被刻意压得很低（画像上按「未测」灰档展示），
      若不放大首次修正，零基础学生在一个节点的有限题量里连续答对也只能
      升到 ~0.7 出头，「已掌握」几乎不可达，画像会与实际答题结果脱节。
    """
    k_base = K_QUIZ if kind == "quiz" else K_DIALOG
    k = k_base * (1.0 - n / (n + 3.0))
    if n == 0:
        k *= FIRST_EVIDENCE_BOOST
    return k


def mastery_update(profile, kg, node_id: str, correct, kind: str = "quiz") -> float:
    """答对/答错后更新掌握度并做先修传播，返回新 θ。

    correct: True/False，或对话软证据 c∈{0, 0.5, 1}（kind="dialog" 时）
    """
    theta = profile.mastery.get(node_id, 0.45)
    c = 1.0 if correct is True else (0.0 if correct is False else float(correct))
    p = sigmoid(8.0 * (theta - 0.5))          # 当前掌握度下的预期答对概率
    n = profile.evidence_count.get(node_id, 0)
    k = learning_rate(n, kind)                 # Elo 自适应学习率 + 首个证据放大
    theta_new = min(0.99, max(0.01, theta + k * (c - p)))
    profile.mastery[node_id] = theta_new
    profile.evidence_count[node_id] = n + 1
    _propagate(profile, kg, node_id, c)
    return theta_new


def _propagate(profile, kg, node_id: str, c: float):
    """先修传播：答对 → 后继 +0.05；答错 → 先修 −0.03 并标记 needs_review"""
    if c >= 0.5:
        for s in kg.successors_of(node_id):
            if s in profile.mastery:
                profile.mastery[s] = min(0.99, profile.mastery[s] + 0.05)
    else:
        for p in kg.prereqs_of(node_id):
            if p in profile.mastery:
                profile.mastery[p] = max(0.01, profile.mastery[p] - 0.03)
            profile.needs_review.add(p)


def propagate(profile, kg, node_id: str, correct) -> None:
    """公开的先修传播入口（供撤销旧作答后重新施加新作答时调用）"""
    _propagate(profile, kg, node_id, correct)


def undo_propagate(profile, kg, node_id: str, correct) -> None:
    """撤销一次作答的先修传播影响（_propagate 的逆；needs_review 标记保留）"""
    if correct is True:
        for s in kg.successors_of(node_id):
            if s in profile.mastery:
                profile.mastery[s] = max(0.01, profile.mastery[s] - 0.05)
    else:
        for p in kg.prereqs_of(node_id):
            if p in profile.mastery:
                profile.mastery[p] = min(0.99, profile.mastery[p] + 0.03)


def revise_mastery(profile, kg, node_id: str, sequence, base_theta,
                   base_evidence) -> float:
    """改动历史作答后，按新对错序列重算某节点 θ 与证据数（不做先修传播）。

    以该节点首次作答前的 θ/证据为基准逐题重放，保证画像与最终统计一致；
    先修传播由调用方另行撤销/重施（见 undo_propagate / propagate）。
    """
    theta, n = float(base_theta), int(base_evidence)
    for correct in sequence:
        c = 1.0 if correct is True else 0.0
        p = sigmoid(8.0 * (theta - 0.5))
        k = learning_rate(n, "quiz")
        theta = min(0.99, max(0.01, theta + k * (c - p)))
        n += 1
    profile.mastery[node_id] = theta
    profile.evidence_count[node_id] = n
    return theta


def apply_forgetting(profile, node_id: str, days: float) -> float:
    """遗忘衰减：θ ← θ·exp(−0.02·Δt天)；30 天约衰减到 55%"""
    theta = profile.mastery.get(node_id, 0.45)
    theta_new = max(0.01, theta * math.exp(-0.02 * days))
    profile.mastery[node_id] = theta_new
    return theta_new
