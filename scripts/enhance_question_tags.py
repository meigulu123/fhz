"""题库目标标签增强脚本

为现有150道题批量添加目标标签(goal_tags)，支持：
- 深度学习(deep_learning)：神经网络/Transformer等深度相关
- 经典算法(classical_ml)：传统机器学习算法
- 面试求职(interview)：重原理/对比/优缺点
- 期末备考(exam)：重基础概念/公式计算
- 通用(general)：基础题，所有方向适用

题目编号规则：
- _01：基础概念/计算题 → exam + general
- _02：理解应用题 → 方向标签 + general
- _03：进阶对比/面试题 → interview + 方向标签
"""
import json
from pathlib import Path

# 节点类别 → 目标方向映射
CATEGORY_GOAL_MAP = {
    "数学基础": ["exam", "general"],
    "ML概论": ["general", "exam"],
    "经典监督学习": ["classical_ml", "interview"],
    "集成学习": ["classical_ml", "interview"],
    "神经网络深度学习": ["deep_learning", "interview"],
    "评估调优": ["interview", "exam", "general"],
    "无监督学习": ["classical_ml", "exam"],
}

# 题目序号 → 题型标签
# _01: 基础计算题 → 只标 exam + general（纯基础，不叠加方向标签）
# _02: 理解应用题 → 节点方向标签 + general
# _03: 进阶对比/面试题 → 节点方向标签 + interview
QUESTION_TYPE_MAP = {
    "01": ["exam", "general"],
    "02": ["general"],
    "03": ["interview"],
}


def load_data():
    root = Path(__file__).resolve().parent.parent
    kg_path = root / "data" / "kg" / "ml_kg.json"
    q_path = root / "data" / "kg" / "questions.json"
    kg = json.loads(kg_path.read_text(encoding="utf-8"))
    data = json.loads(q_path.read_text(encoding="utf-8"))
    return kg, data


def get_node_category(kg, node_id: str) -> str:
    for n in kg["nodes"]:
        if n["id"] == node_id:
            return n["category"]
    return ""


def add_goal_tags():
    kg, data = load_data()
    questions = data["questions"]
    tagged = 0

    for q in questions:
        node_id = q["node_id"]
        qid = q["id"]
        # 从题号提取序号（最后两位）
        num_suffix = qid.split("_")[-1]

        # 节点方向标签
        category = get_node_category(kg, node_id)
        node_goals = CATEGORY_GOAL_MAP.get(category, ["general"])

        # 题型标签（按题号决定是否叠加节点标签）
        if num_suffix == "01":
            # 第1题：纯基础题，不叠加节点方向，只标 exam + general
            type_goals = ["exam", "general"]
            all_goals = type_goals
        elif num_suffix == "02":
            # 第2题：理解应用，叠加节点方向 + general
            type_goals = ["general"]
            all_goals = list(dict.fromkeys(node_goals + type_goals))
        else:
            # 第3题：进阶/面试，叠加节点方向 + interview
            type_goals = ["interview"]
            all_goals = list(dict.fromkeys(node_goals + type_goals))

        q["goal_tags"] = all_goals
        tagged += 1

    # 保存
    root = Path(__file__).resolve().parent.parent
    out_path = root / "data" / "kg" / "questions.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"已为 {tagged} 道题添加目标标签")
    print("\n标签分布统计:")
    from collections import Counter
    tag_counts = Counter()
    for q in questions:
        for t in q["goal_tags"]:
            tag_counts[t] += 1
    for tag, cnt in tag_counts.most_common():
        print(f"  {tag}: {cnt}题")


if __name__ == "__main__":
    add_goal_tags()
