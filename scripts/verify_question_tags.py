"""验证题库目标导向优化效果"""
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

print('=== 题库目标导向优化效果验证 ===')
print()

# 测试节点：d02 反向传播（深度学习方向）
node_id = 'd02'
print(f'测试节点：{node_id} ({kg.nodes[node_id].name})')
print()

# 学生A：深度学习方向
pA = StudentProfile(student_id='A', goals=['深度学习方向'], goal_keywords=[])
tagsA = goals_to_tags(pA)
print(f'学生A（深度学习方向）目标标签：{tagsA}')
qA = next_question_for_node(qs_by_node[node_id], tagsA, [])
print(f'  推荐第1题：{qA["id"]} - {qA["stem"][:50]}...')
print(f'  题目标签：{qA.get("goal_tags", [])}')
print()

# 学生B：面试求职方向
pB = StudentProfile(student_id='B', goals=['面试求职准备'], goal_keywords=[])
tagsB = goals_to_tags(pB)
print(f'学生B（面试求职方向）目标标签：{tagsB}')
qB = next_question_for_node(qs_by_node[node_id], tagsB, [])
print(f'  推荐第1题：{qB["id"]} - {qB["stem"][:50]}...')
print(f'  题目标签：{qB.get("goal_tags", [])}')
print()

# 学生C：期末备考方向
pC = StudentProfile(student_id='C', goals=['期末备考'], goal_keywords=[])
tagsC = goals_to_tags(pC)
print(f'学生C（期末备考方向）目标标签：{tagsC}')
qC = next_question_for_node(qs_by_node[node_id], tagsC, [])
print(f'  推荐第1题：{qC["id"]} - {qC["stem"][:50]}...')
print(f'  题目标签：{qC.get("goal_tags", [])}')
print()

# 验证同一节点三道题标签不同
print('该节点三道题完整标签：')
for q in qs_by_node[node_id]:
    print(f'  {q["id"]}: {q.get("goal_tags", [])}')

print()
print('=== 标签分布统计 ===')
from collections import Counter
tag_counts = Counter()
for q in questions:
    for t in q.get('goal_tags', []):
        tag_counts[t] += 1
for tag, cnt in tag_counts.most_common():
    print(f'  {tag}: {cnt}题')
