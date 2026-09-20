"""学习里程碑与成就系统

跟踪学生学习过程中的关键节点，达成时给予正向反馈。
里程碑类型：
- 知识点数量里程碑（学完 1/5/10/20/30 个）
- 正确率里程碑（连续答对 5/10 题）
- 掌握度里程碑（平均掌握度达 0.5/0.7/0.85）
- 类别里程碑（完成某一整类知识）
- 坚持里程碑（累计学习时长 1/5/10 小时）
"""
from __future__ import annotations

# 里程碑定义：id -> (名称, 检测函数描述, 达成文案)
MILESTONES = {
    # 知识点数量
    "first_node": ("第一个知识点", "🎉 恭喜你完成第一个知识点！学习之旅正式开始了！"),
    "five_nodes": ("五连学者", "🌟 太棒了！你已经完成了 5 个知识点，继续保持！"),
    "ten_nodes": ("十全十美", "🏆 了不起！10 个知识点已攻克，你已经入门了！"),
    "twenty_nodes": ("二十而立", "💪 20 个知识点！你已经掌握了机器学习的核心框架！"),
    "thirty_nodes": ("三十而立", "🚀 30 个知识点！你的知识体系已经相当扎实了！"),
    # 正确率
    "five_correct": ("五连胜", "🔥 连续答对 5 题！你的思路越来越清晰了！"),
    "ten_correct": ("十连胜", "⚡ 连续答对 10 题！太强了！这就是融会贯通的感觉！"),
    # 掌握度
    "mastery_05": ("半程达人", "📈 平均掌握度达到 0.5！你已经从入门走向理解了！"),
    "mastery_07": ("七成高手", "🎯 平均掌握度达到 0.7！你已经超过了大多数初学者！"),
    "mastery_085": ("八五精英", "👑 平均掌握度达到 0.85！你已经是机器学习的精英学习者了！"),
    # 类别完成
    "cat_math": ("数学基石", "📐 完成全部数学基础知识点！这是机器学习的坚实基石！"),
    "cat_basic": ("入门达人", "🌱 完成机器学习概论！你正式进入了 ML 的世界！"),
    "cat_supervised": ("监督学习能手", "🎓 完成全部监督学习算法！这是 ML 最核心的应用领域！"),
    # 坚持
    "study_1h": ("一小时坚持", "⏰ 累计学习 1 小时！坚持就是胜利！"),
    "study_5h": ("五小时专注", "⏳ 累计学习 5 小时！你的专注度令人钦佩！"),
    "study_10h": ("十小时深耕", "🏅 累计学习 10 小时！你已经真正投入了这项学习！"),
}


def check_milestones(state, kg, mem) -> list:
    """检查并返回本次新达成的里程碑列表

    每次完成节点后调用；返回新达成的里程碑 id 列表。
    已达成的里程碑记录在 state.done_nodes 旁边的 _milestones_done 集合中。
    """
    profile = state.profile
    if profile is None:
        return []

    done = set(getattr(state, "_milestones_done", set()))
    new_milestones = []

    # 知识点数量里程碑
    n_done = len(state.done_nodes)
    for threshold, mid in [(1, "first_node"), (5, "five_nodes"),
                           (10, "ten_nodes"), (20, "twenty_nodes"),
                           (30, "thirty_nodes")]:
        if n_done >= threshold and mid not in done:
            new_milestones.append(mid)
            done.add(mid)

    # 连续答对里程碑
    recent_correct = 0
    for c in reversed(state.last_results):
        if c:
            recent_correct += 1
        else:
            break
    for threshold, mid in [(5, "five_correct"), (10, "ten_correct")]:
        if recent_correct >= threshold and mid not in done:
            new_milestones.append(mid)
            done.add(mid)

    # 掌握度里程碑
    thetas = list(profile.mastery.values())
    mean = sum(thetas) / len(thetas) if thetas else 0
    for threshold, mid in [(0.5, "mastery_05"), (0.7, "mastery_07"),
                           (0.85, "mastery_085")]:
        if mean >= threshold and mid not in done:
            new_milestones.append(mid)
            done.add(mid)

    # 类别完成里程碑
    cat_done = {}
    for nid in state.done_nodes:
        if nid in kg.nodes:
            cat = kg.nodes[nid].category
            cat_done[cat] = cat_done.get(cat, 0) + 1
    cat_total = {}
    for nid, node in kg.nodes.items():
        cat_total[node.category] = cat_total.get(node.category, 0) + 1
    for cat, mid in [("数学基础", "cat_math"),
                     ("ML概论", "cat_basic"),
                     ("经典监督学习", "cat_supervised")]:
        if (cat in cat_done and cat in cat_total
                and cat_done[cat] >= cat_total[cat]
                and mid not in done):
            new_milestones.append(mid)
            done.add(mid)

    # 学习时长里程碑
    try:
        duration_min = mem.total_duration(profile.student_id) / 60.0
        for threshold, mid in [(60, "study_1h"), (300, "study_5h"),
                               (600, "study_10h")]:
            if duration_min >= threshold and mid not in done:
                new_milestones.append(mid)
                done.add(mid)
    except Exception:
        pass  # 时长统计失败不影响里程碑检测

    # 保存已达成的里程碑
    setattr(state, "_milestones_done", done)
    return new_milestones


def milestone_message(milestone_ids: list) -> str:
    """生成里程碑达成的展示文案"""
    if not milestone_ids:
        return ""
    lines = ["\n\n---\n\n🎉 **达成新里程碑！**"]
    for mid in milestone_ids:
        if mid in MILESTONES:
            name, msg = MILESTONES[mid]
            lines.append(f"\n{msg}")
    return "\n".join(lines)
