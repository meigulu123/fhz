"""间隔重复复习排程：算每个知识点的复习到期与紧迫度

间隔序列 1 / 3 / 7 / 15 天（答对次数越多间隔越长，SM-2 简化），
到期日 = 最近一次接触该知识点的时间 + 间隔。逾期越多紧迫度越高：
①作为路径评分的第 6 个因子（到期未复习的节点会被排到前面）；
②在路径页「今日待复习」区块展示。

最近接触时间取自 interactions 表（跨会话有效）：排程随时要算，不能等
会话开始才回填的 profile.last_seen。
"""
from __future__ import annotations

import time

INTERVALS = (1, 3, 7, 15)   # 已答对 0/1/2/3+ 次对应的复习间隔（天）
MASTERED = 0.75             # θ ≥ 0.75 且未被标记待复习 → 不排复习
FRESH = 0.05                # θ ≤ 0.05 且未被标记 → 视作未开始，不排复习
_DAYS = 86400.0
_URGENT_WINDOW = 3.0        # 距到期 3 天以上视为不紧迫（紧迫度线性衰减到 0）


def urgency(days_left: float) -> float:
    """紧迫度 0~1：已逾期 = 1，距到期 ≥3 天 = 0（线性衰减）"""
    if days_left <= 0:
        return 1.0
    return max(0.0, 1.0 - days_left / _URGENT_WINDOW)


def due_reviews(profile, kg, hits=None, last_map=None, now=None) -> list:
    """待复习清单（按紧迫度降序）

    hits：每知识点答对次数（mem.correct_by_node），决定复习间隔档位；
    last_map：每知识点最近一次交互时间戳（mem.last_ts_by_node），决定到期日。
    返回项：{node_id, name, mastery, interval_days, days_left, overdue, urgency}
    """
    hits = hits or {}
    last_map = last_map or {}
    now = now or time.time()
    out = []
    for nid, node in kg.nodes.items():
        theta = profile.mastery.get(nid, 0.0)
        flagged = nid in profile.needs_review
        if not flagged and (theta >= MASTERED or theta <= FRESH):
            continue
        last = last_map.get(nid)
        if not last:
            continue                    # 从没学过/无接触记录：属于新学内容，不排复习
        interval = INTERVALS[min(hits.get(nid, 0), len(INTERVALS) - 1)]
        days_left = interval - (now - last) / _DAYS
        out.append({
            "node_id": nid, "name": node.name,
            "mastery": round(theta, 3),
            "interval_days": interval,
            "days_left": round(days_left, 1),
            "overdue": days_left <= 0,
            "urgency": round(urgency(days_left), 3),
        })
    out.sort(key=lambda r: (-r["urgency"], r["mastery"]))
    return out


def urgency_map(profile, kg, hits=None, last_map=None, now=None) -> dict:
    """知识点 → 复习紧迫度（路径评分用）"""
    return {r["node_id"]: r["urgency"]
            for r in due_reviews(profile, kg, hits, last_map, now)}
