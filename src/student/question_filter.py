"""题目筛选：根据学生学习目标优先推荐匹配的题目

筛选逻辑：
1. 优先选择 goal_tags 与学生目标重叠的题目
2. 通用题(general)作为兜底
3. 同节点内按匹配度排序，匹配题优先，无匹配则退化为顺序取题
"""
from __future__ import annotations

# 学生目标关键词 → 题目标签映射
GOAL_KEYWORD_TO_TAG = {
    # 深度学习方向
    "深度学习": "deep_learning",
    "神经网络": "deep_learning",
    "transformer": "deep_learning",
    "卷积": "deep_learning",
    "cnn": "deep_learning",
    "rnn": "deep_learning",
    "lstm": "deep_learning",
    "大模型": "deep_learning",
    "预训练": "deep_learning",
    "微调": "deep_learning",
    # 经典算法方向
    "经典算法": "classical_ml",
    "传统机器学习": "classical_ml",
    "决策树": "classical_ml",
    "svm": "classical_ml",
    "支持向量机": "classical_ml",
    "集成学习": "classical_ml",
    "随机森林": "classical_ml",
    "boosting": "classical_ml",
    "kaggle": "classical_ml",
    # 面试方向
    "面试": "interview",
    "求职": "interview",
    "秋招": "interview",
    "春招": "interview",
    "找工作": "interview",
    "笔试": "interview",
    # 考试方向
    "考试": "exam",
    "期末": "exam",
    "备考": "exam",
    "测验": "exam",
    "课程": "exam",
}


def goals_to_tags(profile) -> set:
    """从学生画像提取目标标签集合"""
    tags = set()
    # goal_keywords 是节点ID，不是标签，需要从 goals 文本提取
    goals_text = " ".join(profile.goals or [])
    for kw, tag in GOAL_KEYWORD_TO_TAG.items():
        if kw in goals_text.lower():
            tags.add(tag)
    # 如果没有匹配到特定标签，默认包含 general
    if not tags:
        tags.add("general")
    return tags


def score_question_match(question: dict, goal_tags: set) -> float:
    """计算题目与学生目标的匹配度分数

    返回 0~1 之间的分数，越高越匹配
    """
    q_tags = set(question.get("goal_tags", []))
    if not q_tags or not goal_tags:
        return 0.5  # 中性分
    overlap = q_tags & goal_tags
    # 通用题永远匹配（给基础分）
    if "general" in q_tags:
        return 0.5 + 0.5 * len(overlap) / max(1, len(goal_tags))
    return len(overlap) / max(1, len(goal_tags))


def filter_questions_by_goal(questions: list, goal_tags: set,
                               used_qids: list = None) -> list:
    """按学习目标筛选并排序题目

    Args:
        questions: 候选题目列表（通常是同一节点的所有题）
        goal_tags: 学生目标标签集合
        used_qids: 已使用的题目ID列表

    Returns:
        排序后的题目列表（匹配度高的在前）
    """
    used = set(used_qids or [])
    available = [q for q in questions if q["id"] not in used]
    if not available:
        return []
    # 计算匹配度并排序
    scored = [(score_question_match(q, goal_tags), q) for q in available]
    scored.sort(key=lambda t: -t[0])
    return [q for _, q in scored]


def next_question_for_node(node_questions: list, goal_tags: set,
                            used_qids: list = None) -> dict | None:
    """从节点题目列表中选下一道题（按目标匹配度）"""
    ordered = filter_questions_by_goal(node_questions, goal_tags, used_qids)
    return ordered[0] if ordered else None
