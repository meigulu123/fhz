"""命令行端到端：诊断 → 路径（Day1 验收脚本，Mock 离线模式）

模拟一名学生：诊断先验 + 自适应测验（程序化模拟作答）→ 诊断报告 → ZPD 路径。
用法：python scripts/e2e_cli.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import load_settings
from src.kg.loader import KnowledgeGraph
from src.student.profile import StudentProfile, init_mastery
from src.student.update import mastery_update
from src.student.diagnosis import AdaptiveQuiz, build_report
from src.path.planner import PathPlanner
from src.path.pacing import pace_params


def main():
    cfg = load_settings()
    kg = KnowledgeGraph.load(cfg["paths"]["kg"])
    questions = json.loads(
        Path(cfg["paths"]["questions"]).read_text(encoding="utf-8"))["questions"]

    print("=" * 60)
    print("知途伴学 · 命令行端到端（诊断 → 路径）")
    print("=" * 60)

    # 1. 学生画像（模拟对话诊断结果：数学强、ML 概念了解、无深度学习基础）
    profile = StudentProfile(
        student_id="demo001", name="小明", major="人工智能",
        goals=["想系统掌握深度学习并在课程设计中应用"],
        goal_keywords=["深度学习", "神经网络", "Transformer"],
        style_tags=["视觉型", "需要示例"],
        prior={"m01": 1.0, "m03": 0.5, "m04": 1.0, "b01": 0.5},
    )
    init_mastery(profile, kg)
    print(f"\n[画像] {profile.name}（{profile.major}）")
    print(f"[目标] {profile.goals[0]}")
    print(f"[初始掌握度] 平均 {sum(profile.mastery.values())/len(profile.mastery):.3f}，"
          f"共 {len(profile.mastery)} 节点")

    # 2. 自适应测验（程序化模拟作答：主链前半对、后半错，制造可解释的诊断）
    quiz = AdaptiveQuiz(kg, questions)
    state = quiz.new_state()
    print("\n[测验] 自适应测验开始（主链锚点双向搜索）")
    sim_pattern = iter([True, False, True, False, True, False, True, False,
                        True, False, True, False])
    while not state.finished:
        q = quiz.next_question(state)
        if q["id"] is None:
            break
        correct = next(sim_pattern, False)
        quiz.record(state, q, correct)
        mastery_update(profile, kg, q["node_id"], correct, kind="quiz")
        print(f"  题{state.questions_asked:2d} [{q['node_id']}] "
              f"{'答对' if correct else '答错'} → 当前节点 {state.current_node}")
    print(f"[测验] 结束：{state.stop_reason}，覆盖 {len(state.covered)} 节点，"
          f"共 {state.questions_asked} 题")

    # 3. 诊断报告
    report = build_report(profile, kg, PathPlanner(kg), state)
    print("\n[诊断报告]")
    print(f"  掌握较好：{report['strong'] or '无'}")
    print(f"  需要加强：{report['weak'] or '无'}")
    print(f"  ZPD 带：{report['band']}")
    print(f"  建议起点：{report['suggested']}")
    print(f"  答题正确率：{report['accuracy']}")

    # 4. 路径规划
    planner = PathPlanner(kg)
    pace = pace_params(report["accuracy"], stuck_count=0)
    plan = planner.plan(profile, batch=pace["batch"])
    print(f"\n[路径] 节奏 pace={pace['pace']}，本批 {pace['batch']} 个知识点：")
    for i, item in enumerate(plan["items"], 1):
        print(f"  {i}. {item['name']} [{item['tier']}档] "
              f"难度{item['difficulty']} 掌握度{item['mastery']} "
              f"评分{item['score']}")
        print(f"     → {item['reason']}")

    # 5. 重规划规则兜底演示
    replan = planner.replan_rules(profile, "stuck_l3", "d02")
    print(f"\n[重规划] 卡死触发 → {replan}")

    print("\n" + "=" * 60)
    print("端到端跑通：画像 → 测验 → 诊断报告 → ZPD 路径 → 重规划")
    print("=" * 60)


if __name__ == "__main__":
    main()
