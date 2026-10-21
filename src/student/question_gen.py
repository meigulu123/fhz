"""动态出题：题库耗尽时按学生画像与知识图谱节点现场生成一道新题

两条通道共用同一套校验（question_gen.gen_question）：
- 真实大模型：[TPL:gen_question] 模板输出结构化 JSON（题干/四选项/答案/解析）；
- 离线 Mock / 模型输出不合法：rule_question 用节点真实内容（概述/讲义/类别）
  确定性组装一道单选题，保证无网无 Key 也能继续出题，且可 pytest 回归。

约定：生成题的 id 形如 gen_<node_id>_<序号>，便于编排器按节点限额；题目一定
带 L0~L3 提示，脚手架才能照常逐级引导。
"""
from __future__ import annotations

import json

from src.llm.base import sys, usr

LETTERS = "ABCD"

PROMPT = (
    "你是机器学习命题助手。围绕指定知识点，为这位学生新出一道单选题，"
    "只输出 JSON：{\"stem\": 题干, \"options\": [\"A. ..\", \"B. ..\", \"C. ..\", \"D. ..\"],"
    " \"answer\": \"A|B|C|D\", \"explanation\": 解析}。"
    "要求：四个选项、有且只有一个正确项、干扰项合理、题干不得泄露答案；"
    "难度贴合学生当前掌握度（掌握度高则加大难度），解析要讲清为什么。"
)


def gen_question(llm, kg, node_id, profile=None, variant: int = 0) -> dict | None:
    """生成一道新题：真实大模型优先，任何异常/非法输出都退回离线规则题

    variant 为同节点第几次生成（0 起），用于让规则题的干扰项与答案位置轮转，
    保证多次生成不会完全重复。返回题目 dict；无法生成返回 None。
    """
    node = kg.nodes.get(node_id)
    if node is None:
        return None
    messages = [
        sys("gen_question", PROMPT),
        usr(f"[node={node_id}][variant={variant}]"
            f"[stats_json={json.dumps(_stats(node, profile), ensure_ascii=False)}]"),
    ]
    try:
        data = llm.chat_json(messages)
    except Exception:  # noqa: BLE001 —— 任何生成失败都退回规则题，不能中断教学
        data = None
    q = _normalize(data, kg, node, variant)
    if q is None:
        q = rule_question(kg, node_id, profile, variant=variant)
    return q


def _stats(node, profile) -> dict:
    """命题上下文：节点真实内容 + 学生当前掌握度与学习目标"""
    stats = {"node": node.id, "name": node.name, "category": node.category,
             "difficulty": round(node.difficulty, 3), "bloom": node.bloom,
             "summary": node.summary, "keywords": node.keywords[:6]}
    if profile is not None:
        stats["mastery"] = round(profile.mastery.get(node.id, 0.0), 3)
        stats["goals"] = list(profile.goals or [])[:2]
    return stats


def rule_question(kg, node_id, profile=None, variant: int = 0,
                  difficulty: float | None = None) -> dict | None:
    """离线规则题：用节点真实概述作正确项、其它节点概述作干扰项

    确定性可回归：同 (node_id, variant) 必得同一道题；正确项字母按 variant 轮转，
    干扰项优先取同类别节点的概述（同类别才有辨析价值），不足则补其它类别。
    """
    node = kg.nodes.get(node_id)
    if node is None or not node.summary:
        return None
    same = sorted((n for n in kg.nodes.values()
                   if n.id != node_id and n.category == node.category and n.summary),
                  key=lambda n: n.id)
    other = sorted((n for n in kg.nodes.values()
                    if n.id != node_id and n.category != node.category and n.summary),
                   key=lambda n: n.id)
    pool = same + other
    if len(pool) < 3:
        return None
    picks = [pool[(variant + i) % len(pool)] for i in range(3)]
    texts = [_clip(n.summary, 72) for n in picks]
    idx = variant % len(LETTERS)
    texts.insert(idx, _clip(node.summary, 72))
    answer = LETTERS[idx]
    body = _lecture_body(node)
    hints = {
        "L0": f"先想清楚：「{node.name}」是解决什么问题的？它和相近概念的区别在哪？",
        "L1": f"提示：「{node.name}」属于「{node.category}」类，难度 {node.difficulty:.2f}；"
              "注意分辨它和同类别其它概念的边界。",
        "L2": f"回看讲义会有帮助：{_clip(body, 90) if body else node.summary}",
        "L3": f"正确说法是：{_clip(node.summary, 80)}（即选项 {answer}）。",
    }
    return {
        "id": f"gen_{node_id}_{variant}", "node_id": node_id, "type": "single",
        "difficulty": round(difficulty if difficulty is not None else node.difficulty, 3),
        "stem": f"下列关于「{node.name}」的说法，哪一项是正确的？",
        "options": [f"{LETTERS[i]}. {t}" for i, t in enumerate(texts)],
        "answer": answer,
        "explanation": f"{node.name}：{node.summary}（本题由系统按你的学情现场生成）",
        "hints": hints, "generated": True,
    }


def _normalize(data, kg, node, variant: int) -> dict | None:
    """校验并规范化大模型输出；不合规则返回 None（由调用方退回规则题）

    提示词缺 L0~L3 时，用规则题的提示补齐，保证脚手架不会因生成题而断档。
    """
    if not isinstance(data, dict):
        return None
    stem = str(data.get("stem") or "").strip()
    raw = data.get("options")
    if not stem or not isinstance(raw, list) or len(raw) < 3:
        return None
    opts = [_clip(str(o).strip(), 90) for o in raw if str(o).strip()]
    if len(opts) < 3:
        return None
    # 补上选项字母前缀（模型可能只给正文）
    opts = [o if (o[:1].upper() in LETTERS and o[1:2] in (".", "、", " "))
            else f"{LETTERS[i]}. {o}" for i, o in enumerate(opts)]
    ans = str(data.get("answer") or "").strip().upper()[:1]
    if ans not in LETTERS[:len(opts)]:
        return None
    hints = data.get("hints") if isinstance(data.get("hints"), dict) else None
    if not hints or not all(hints.get(f"L{i}") for i in range(4)):
        base = rule_question(kg, node.id, variant=variant) or {}
        hints = base.get("hints") or {}
    return {
        "id": f"gen_{node.id}_{variant}", "node_id": node.id, "type": "single",
        "difficulty": round(float(data.get("difficulty") or node.difficulty), 3),
        "stem": stem, "options": opts, "answer": ans,
        "explanation": str(data.get("explanation") or node.summary),
        "hints": hints, "generated": True,
    }


def _lecture_body(node) -> str:
    """讲义首段正文（去掉 [ASK:] 提问位）"""
    for block in (node.lecture or "").split("\n\n"):
        text = block.strip()
        if text and not text.startswith("[ASK:]"):
            return text
    return ""


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"
