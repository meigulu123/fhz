"""记忆检索（无 embedding）：关键词余弦 + 时间衰减 + 重要性加权

score = 0.5·keyword_cosine(jieba) + 0.3·exp(−0.10·天数) + 0.2·importance
重要性由交互类型、对错、是否卡住等因素综合决定。
节点相关性增强：查询涉及知识点时，该节点相关记忆优先。
"""
import json
import math
import time

import jieba

IMPORTANT_KINDS = {"quiz", "report", "plan", "scaffold"}
# 各交互类型的基础重要性权重
KIND_WEIGHT = {
    "quiz": 1.0,
    "report": 1.2,
    "plan": 1.1,
    "scaffold": 1.15,   # 卡住经历对后续教学价值高
    "teach": 0.6,
    "message": 0.4,
    "qa": 0.5,
}
MAX_ITEMS = 8
MAX_CONTEXT_CHARS = 300


def _tf(text: str) -> dict:
    if not text:
        return {}
    tf = {}
    for w in jieba.cut(text):
        if len(w.strip()) >= 2:
            tf[w] = tf.get(w, 0) + 1
    return tf


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _importance_score(item: dict) -> float:
    """记忆重要性评分：交互类型 + 对错 + 是否卡住

    返回 0.5~1.5 之间的加权系数。
    """
    kind = item.get("kind", "message")
    base = KIND_WEIGHT.get(kind, 0.5)
    # 答对/答错调整：错题和卡住经历更重要
    delta = 0.0
    try:
        md = json.loads(item.get("mastery_delta_json") or "{}")
        if isinstance(md, dict):
            if md.get("correct") is False:
                delta += 0.2   # 错题更值得记住
            if md.get("theta") is not None:
                # 掌握度大幅波动的记忆更重要
                delta += 0.1
    except (json.JSONDecodeError, TypeError):
        pass
    # scaffold 类记忆（卡住经历）额外加权
    if kind == "scaffold":
        delta += 0.15
    return max(0.5, min(1.5, base + delta))


def retrieve(mem, student_id: str, query: str, now=None) -> list:
    """按相关度排序返回记忆条目（interactions 表）

    综合评分：关键词余弦(0.5) + 时间衰减(0.3) + 重要性(0.2)
    """
    now = now or time.time()
    qv = _tf(query)
    scored = []
    for item in mem.recent_interactions(student_id, limit=200):
        cv = _tf(item.get("content") or "")
        keyword_score = _cosine(qv, cv)
        days = max(0.0, (now - (item.get("ts") or now)) / 86400.0)
        recency = math.exp(-0.10 * days)
        importance = _importance_score(item)
        score = 0.5 * keyword_score + 0.3 * recency + 0.2 * importance
        # 重要事件 ×1.5 保留兼容（新公式已含重要性项）
        if item.get("kind") in IMPORTANT_KINDS and item.get("kind") not in KIND_WEIGHT:
            score *= 1.5
        scored.append((score, item))
    scored.sort(key=lambda t: -t[0])
    return [item for _, item in scored[:MAX_ITEMS] if _ > 0.05]


def retrieve_node(kg, query: str, top_k: int = 3) -> list:
    """在知识图谱中检索与 query 最相关的节点（无 embedding，jieba 关键词）。

    名称/关键词直接命中权重最高；否则按名称/关键词/概述三路余弦加权。
    返回 top_k 个 node_id（score > 0.1），无命中返回空列表。
    """
    qv = _tf(query)
    scored = []
    for nid, node in kg.nodes.items():
        name_cos = _cosine(qv, _tf(node.name))
        kw_cos = max([_cosine(qv, _tf(k)) for k in node.keywords] or [0.0])
        sum_cos = _cosine(qv, _tf(node.summary))
        if node.name in query or any(k in query for k in node.keywords):
            name_cos = max(name_cos, 0.9)
        score = 0.5 * name_cos + 0.3 * kw_cos + 0.2 * sum_cos
        scored.append((score, nid))
    scored.sort(key=lambda t: -t[0])
    return [nid for score, nid in scored[:top_k] if score > 0.1]


def retrieve_node_memories(mem, student_id: str, node_id: str,
                           limit: int = 5) -> list:
    """检索与指定知识点相关的历史记忆（教学上下文增强用）

    优先返回该节点的 quiz/scaffold/teach 记录，按时间倒序。
    """
    rows = mem.recent_interactions(student_id, limit=100)
    node_rows = [r for r in rows if r.get("node_id") == node_id
                 and r.get("kind") in ("quiz", "scaffold", "teach")]
    return node_rows[:limit]


def build_context(mem, student_id: str, query: str, last_reflection=None) -> str:
    """≤300 字记忆上下文（注入 system prompt；Mock 模式下模板拼接）"""
    parts = []
    if last_reflection and last_reflection.get("next_session_preview"):
        parts.append(f"上次会话：{last_reflection['next_session_preview']}")
    for item in retrieve(mem, student_id, query):
        kind = item.get("kind")
        content = (item.get("content") or "")[:60]
        node = item.get("node_id") or ""
        parts.append(f"[{kind}{'/' + node if node else ''}] {content}")
    ctx = "；".join(parts)
    return ctx[:MAX_CONTEXT_CHARS]


def stats_json(profile, kg, report=None, done_nodes=None) -> dict:
    """画像统计（诊断报告/反思/重规划的 Mock 模板输入 [stats_json=...]）"""
    thetas = list(profile.mastery.values()) or [0.45]
    weak_ids = sorted((nid for nid, t in profile.mastery.items() if t < 0.4),
                      key=lambda nid: profile.mastery[nid])[:5]
    weak = [kg.nodes[nid].name for nid in weak_ids]
    strong_ids = sorted((nid for nid, t in profile.mastery.items() if t >= 0.75),
                        key=lambda nid: profile.mastery[nid])[:5]
    done = done_nodes or []
    # 真正学过的知识点（按完成顺序），供反思/开场白引用，避免引用从未学过的节点
    done_names = [kg.nodes[nid].name for nid in done if nid in kg.nodes]
    return {
        "name": profile.name,
        "mean_theta": round(sum(thetas) / len(thetas), 3),
        "done": len(done),
        "done_names": done_names,
        "last_done": done_names[-1] if done_names else "",
        "recent": done_names[-3:],
        "weak": weak,
        "strong": [kg.nodes[nid].name for nid in strong_ids],
        "prereqs": {nid: round(t, 3) for nid, t in profile.mastery.items()},
        "suggested": (report or {}).get("suggested", ""),
        "covered": (report or {}).get("covered", 0),
        "accuracy": (report or {}).get("accuracy", 0),
        "band": (report or {}).get("band", {}),
    }
