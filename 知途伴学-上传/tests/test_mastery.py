"""P1 验证：掌握度初始化公式、BKT+Elo 更新、遗忘衰减、先修传播"""
from pathlib import Path

import pytest

from src.kg.loader import KnowledgeGraph
from src.student.profile import StudentProfile, init_mastery
from src.student.update import mastery_update, apply_forgetting

KG_PATH = Path(__file__).resolve().parent.parent / "data" / "kg" / "ml_kg.json"


@pytest.fixture(scope="module")
def kg():
    return KnowledgeGraph.load(str(KG_PATH))


def new_profile(**kw):
    return StudentProfile(student_id="t001", name="测试", **kw)


def test_init_bounds(kg):
    p = new_profile()
    init_mastery(p, kg)
    for nid, theta in p.mastery.items():
        assert 0.05 <= theta <= 0.85, f"{nid}: {theta} 越界"


def test_init_prior_effect(kg):
    """先验越高、先修越强，初始掌握度越高"""
    weak = new_profile(prior={})
    strong = new_profile(prior={"m01": 1.0, "m04": 1.0, "b01": 1.0})
    init_mastery(weak, kg)
    init_mastery(strong, kg)
    assert strong.mastery["b01"] > weak.mastery["b01"]
    assert strong.mastery["s02"] > weak.mastery["s02"]


def test_init_prereq_penalty(kg):
    """存在未达标先修时，惩罚项 −0.15 生效"""
    ok_prior = new_profile(prior={"m01": 1.0, "m04": 1.0})
    broken = new_profile(prior={"m01": 0.0, "m04": 1.0})  # b01 先修 m01 崩塌
    init_mastery(ok_prior, kg)
    init_mastery(broken, kg)
    assert ok_prior.mastery["b01"] > broken.mastery["b01"]


def test_update_monotone_increase(kg):
    """连续答对：θ 单调上升且收敛不越界"""
    p = new_profile()
    init_mastery(p, kg)
    prev = p.mastery["s02"]
    for _ in range(8):
        cur = mastery_update(p, kg, "s02", True, kind="quiz")
        assert cur >= prev, "连续答对应单调不减"
        assert 0.01 <= cur <= 0.99
        prev = cur
    # 初始 0.625，8 次连续答对（Elo 学习率递减）应升至约 0.76
    assert p.mastery["s02"] > 0.72


def test_update_learning_rate_decays(kg):
    """Elo 自适应学习率：证据越多，单次更新幅度越小"""
    p = new_profile()
    init_mastery(p, kg)
    theta0 = p.mastery["s02"]
    d1 = mastery_update(p, kg, "s02", True, kind="quiz") - theta0
    mastery_update(p, kg, "s02", True, kind="quiz")
    mastery_update(p, kg, "s02", True, kind="quiz")
    theta3 = p.mastery["s02"]
    d4 = mastery_update(p, kg, "s02", True, kind="quiz") - theta3
    assert abs(d4) < abs(d1)


def test_update_wrong_decreases(kg):
    p = new_profile(prior={"s02": 1.0})
    init_mastery(p, kg)
    before = p.mastery["s02"]
    after = mastery_update(p, kg, "s02", False, kind="quiz")
    assert after < before


def test_forgetting_decay(kg):
    p = new_profile()
    init_mastery(p, kg)
    before = p.mastery["s02"]
    after = apply_forgetting(p, "s02", days=30)
    assert after < before
    assert abs(after - before * 0.5488) < 0.01  # exp(−0.02·30)


def test_propagation_correct_successor(kg):
    p = new_profile()
    init_mastery(p, kg)
    succ = "s03"
    before = p.mastery[succ]
    mastery_update(p, kg, "s02", True, kind="quiz")   # 答对 s02 → 后继 +0.05
    assert p.mastery[succ] == pytest.approx(min(0.99, before + 0.05), abs=1e-9)


def test_propagation_wrong_prereq(kg):
    p = new_profile()
    init_mastery(p, kg)
    prereq = "s02"
    before = p.mastery[prereq]
    mastery_update(p, kg, "s03", False, kind="quiz")  # 答错 s03 → 先修 −0.03
    assert p.mastery[prereq] == pytest.approx(max(0.01, before - 0.03), abs=1e-9)
    assert "s02" in p.needs_review or "b02" in p.needs_review


def test_dialog_soft_evidence_smaller_step(kg):
    """对话软证据（c=1）更新幅度小于测验硬证据"""
    p1, p2 = new_profile(), new_profile()
    init_mastery(p1, kg)
    init_mastery(p2, kg)
    d_quiz = mastery_update(p1, kg, "s02", True, kind="quiz") - 0.45 * 0  # noqa
    quiz_after = p1.mastery["s02"]
    dialog_after = mastery_update(p2, kg, "s02", 1.0, kind="dialog")
    assert abs(quiz_after - 0.45) > abs(dialog_after - 0.45)
