"""记忆检索（无 embedding）：关键词余弦 + 时间衰减，top-8 压缩为上下文

score = 0.6·keyword_cosine(jieba) + 0.4·exp(−0.10·天数)；重要事件 ×1.5
"""
import json
import math
import time

import jieba

IMPORTANT_KINDS = {"quiz", "report", "plan"}
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


def retrieve(mem, student_id: str, query: str, now=None) -> list:
    """按相关度排序返回记忆条目（interactions 表）"""
    now = now or time.time()
    qv = _tf(query)
    scored = []
    for item in mem.recent_interactions(student_id, limit=200):
        cv = _tf(item.get("content") or "")
        keyword_score = _cosine(qv, cv)
        days = max(0.0, (now - (item.get("ts") or now)) / 86400.0)
        recency = math.exp(-0.10 * days)
        score = 0.6 * keyword_score + 0.4 * recency
        if item.get("kind") in IMPORTANT_KINDS:
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
