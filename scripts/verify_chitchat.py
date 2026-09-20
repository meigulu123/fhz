"""验证对话自然度优化效果"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.chitchat import (
    greeting_new, quiz_start, diagnosis_confirm,
    correct_reply, wrong_reply, stuck_reassure,
    node_done_praise, welcome_back, path_begin
)

print("=== 对话自然度优化效果验证 ===")
print()

print("--- 新学生开场白（随机3次）---")
for i in range(3):
    print(f"  {i+1}. {greeting_new()[:50]}...")
print()

print("--- 测验开始（随机3次）---")
for i in range(3):
    print(f"  {i+1}. {quiz_start()[:50]}...")
print()

print("--- 诊断确认（随机3次）---")
for i in range(3):
    print(f"  {i+1}. {diagnosis_confirm()}")
print()

print("--- 答对反馈（随机5次）---")
for i in range(5):
    print(f"  {i+1}. {correct_reply()}")
print()

print("--- 答错反馈（随机5次）---")
for i in range(5):
    print(f"  {i+1}. {wrong_reply()[:50]}...")
print()

print("--- 卡住安慰（随机3次）---")
for i in range(3):
    print(f"  {i+1}. {stuck_reassure()[:50]}...")
print()

print("--- 节点完成鼓励（随机5次）---")
for i in range(5):
    print(f"  {i+1}. {node_done_praise()}")
print()

print("--- 路径开始（随机3次）---")
for i in range(3):
    print(f"  {i+1}. {path_begin('线性回归')}")
print()

print("=== 总结 ===")
print("每个场景提供多种模板，随机选择，避免每次回复一模一样")
print("语气更亲切、更像真人老师，减少机械感")
