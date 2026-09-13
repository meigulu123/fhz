"""掌握度更新：BKT 简化 + Elo 自适应学习率 + 先修传播 + 遗忘衰减

全系统数值核心。所有更新必须经本模块，保证画像与路径一致。
"""
import math


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def mastery_update(profile, kg, node_id: str, correct, kind: str = "quiz") -> float:
    """答对/答错后更新掌握度并做先修传播，返回新 θ。

    correct: True/False，或对话软证据 c∈{0, 0.5, 1}（kind="dialog" 时）
    """
    theta = profile.mastery.get(node_id, 0.45)
    c = 1.0 if correct is True else (0.0 if correct is False else float(correct))
    p = sigmoid(8.0 * (theta - 0.5))          # 当前掌握度下的预期答对概率
    n = profile.evidence_count.get(node_id, 0)
    k_base = 0.18 if kind == "quiz" else 0.09
    k = k_base * (1.0 - n / (n + 3.0))        # Elo 自适应学习率：证据越多越保守
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


def apply_forgetting(profile, node_id: str, days: float) -> float:
    """遗忘衰减：θ ← θ·exp(−0.02·Δt天)；30 天约衰减到 55%"""
    theta = profile.mastery.get(node_id, 0.45)
    theta_new = max(0.01, theta * math.exp(-0.02 * days))
    profile.mastery[node_id] = theta_new
    return theta_new


def touch(profile, node_id: str):
    """记录接触时间（会话开始时对历史节点统一做遗忘衰减用）"""
    import time
    profile.last_seen[node_id] = time.time()
