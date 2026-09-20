"""验证不同节点的题目推荐效果"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from src.kg.loader import KnowledgeGraph
from src.student.question_filter import goals_to_tags, next_question_for_node
from src.student.profile import StudentProfile

kg = KnowledgeGraph.load('data/kg/ml_kg.json')
questions = json.load(open('data/kg/questions.json', 'r', encoding='utf-8'))['questions']
qs_by_node = {}
for q in questions:
    qs_by_node.setdefault(q['node_id'], []).append(q)

print('=== 不同学习目标的题目推荐对比 ===')
print()

# 测试节点：s05 决策树（经典算法方向）
for node_id in ['s05', 'v01']:
    print(f'--- 节点：{node_id} ({kg.nodes[node_id].name}) ---')
    print()

    # 学生：深度学习方向
    pA = StudentProfile(student_id='A', goals=['深度学习方向'], goal_keywords=[])
    tagsA = goals_to_tags(pA)
    qA = next_question_for_node(qs_by_node[node_id], tagsA, [])
    print(f'深度学习学生 → {qA["id"]}: {qA["stem"][:40]}...')
    print(f'  标签: {qA.get("goal_tags", [])}')

    # 学生：面试求职方向
    pB = StudentProfile(student_id='B', goals=['面试求职'], goal_keywords=[])
    tagsB = goals_to_tags(pB)
    qB = next_question_for_node(qs_by_node[node_id], tagsB, [])
    print(f'面试学生 → {qB["id"]}: {qB["stem"][:40]}...')
    print(f'  标签: {qB.get("goal_tags", [])}')

    # 学生：期末备考方向
    pC = StudentProfile(student_id='C', goals=['期末备考'], goal_keywords=[])
    tagsC = goals_to_tags(pC)
    qC = next_question_for_node(qs_by_node[node_id], tagsC, [])
    print(f'期末学生 → {qC["id"]}: {qC["stem"][:40]}...')
    print(f'  标签: {qC.get("goal_tags", [])}')
    print()

    # 三道题完整标签
    print('三道题标签:')
    for q in qs_by_node[node_id]:
        print(f'  {q["id"]}: {q.get("goal_tags", [])}')
    print()
