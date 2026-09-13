"""P1 验证：ZPD 带计算、前沿集门槛、路径评分排序、节奏参数"""
from pathlib import Path

import pytest

from src.kg.loader import KnowledgeGraph
from src.path.pacing import pace_params
from src.path.planner import PathPlanner
from src.student.profile import StudentProfile, init_mastery

KG_PATH = Path(__file__).resolve().parent.parent / "data" / "kg" / "ml_kg.json"


@pytest.fixture(scope="module")
def kg():
    return KnowledgeGraph.load(str(KG_PATH))


@pytest.fixture()
def planner(kg):
    return PathPlanner(kg)


def uniform_profile(kg, theta):
    p = StudentProfile(student_id="t001")
    init_mastery(p, kg)
    for nid in p.mastery:
        p.mastery[nid] = theta
    return p


def test_zpd_band_uniform(planner, kg):
    """均匀掌握度 0.3：z_low=0.3，σ=0 → z_high=0.45"""
    p = uniform_profile(kg, 0.3)
    band = planner.zpd_band(p)
    assert band["z_low"] == pytest.approx(0.3, abs=1e-6)
    assert band["z_high"] == pytest.approx(0.45, abs=1e-6)


def test_zpd_band_high_mastery_capped(planner, kg):
    """高掌握度时 z_high 不超过 0.95"""
    p = uniform_profile(kg, 0.9)
    band = planner.zpd_band(p)
    assert band["z_high"] <= 0.95


def test_frontier_all_mastered_empty(planner, kg):
    p = uniform_profile(kg, 0.8)
    assert planner.frontier(p) == []


def test_frontier_gate(planner, kg):
    """θ=0.3 时只有无先修节点进入前沿集"""
    p = uniform_profile(kg, 0.3)
    frontier = planner.frontier(p)
    assert set(frontier) == {"m01", "m03", "m04"}


def test_frontier_prereq_gate_release(planner, kg):
    """先修达标（≥0.6）后，后继节点进入前沿集"""
    p = uniform_profile(kg, 0.0)
    p.mastery["m01"] = 0.7
    p.mastery["m04"] = 0.7
    frontier = planner.frontier(p)
    assert "m02" in frontier   # 先修 m01 达标
    assert "b01" in frontier   # 先修 m01、m04 均达标
    assert "m05" in frontier   # 先修 m04=0.7 达标 → 进入前沿集


def test_plan_tiers_within_band(planner, kg):
    """A 档节点难度落在 ZPD 带内；items 按评分降序"""
    p = uniform_profile(kg, 0.3)
    plan = planner.plan(p, batch=10)
    assert plan["items"], "应有可排路径"
    scores = [it["score"] for it in plan["items"]]
    assert scores == sorted(scores, reverse=True)
    for it in plan["items"]:
        if it["tier"] == "A":
            assert plan["band"]["z_low"] <= it["difficulty"] <= plan["band"]["z_high"]


def test_plan_skips_too_hard(planner, kg):
    """难度高于 ZPD 带的节点不排入"""
    p = uniform_profile(kg, 0.15)
    plan = planner.plan(p, batch=50)
    for it in plan["items"]:
        assert it["difficulty"] <= plan["band"]["z_high"]


def test_replan_rules_stuck_l3(planner, kg):
    p = uniform_profile(kg, 0.4)
    r = planner.replan_rules(p, "stuck_l3", "s03")
    assert r["action"] == "review_prereq"
    assert r["node_id"] in kg.prereqs_of("s03")


def test_pace_params(planner):
    fast = pace_params(1.0, 0)
    assert fast["pace"] == pytest.approx(0.74, abs=0.01)
    assert fast["batch"] == 2
    slow = pace_params(0.4, 2)
    assert slow["pace"] == 0.4                      # 被下限裁剪
    assert slow["batch"] == 1
    cap = pace_params(1.0, 0)  # 上限验证
    assert pace_params(1.0, -10)["pace"] == 1.6
