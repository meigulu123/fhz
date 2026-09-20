"""P1 验证：知识图谱加载、拓扑分层、无环校验"""
from pathlib import Path

import pytest

from src.kg.loader import KnowledgeGraph

KG_PATH = Path(__file__).resolve().parent.parent / "data" / "kg" / "ml_kg.json"


@pytest.fixture(scope="module")
def kg():
    return KnowledgeGraph.load(str(KG_PATH))


def test_50_nodes_7_categories(kg):
    assert len(kg.nodes) == 50
    cats = kg.categories()
    assert set(cats) == {"数学基础", "ML概论", "经典监督学习",
                         "集成学习", "神经网络深度学习", "评估调优", "无监督学习"}
    assert {k: len(v) for k, v in cats.items()} == {
        "数学基础": 8, "ML概论": 4, "经典监督学习": 12, "集成学习": 5,
        "神经网络深度学习": 12, "评估调优": 6, "无监督学习": 3,
    }


def test_acyclic_topological_layers(kg):
    """先修图无环：Kahn 分层覆盖全部 50 节点"""
    layers = kg.topological_layers()
    assert len(layers) == 50
    # 无先修节点在 0 层
    assert layers["m01"] == 0
    assert layers["m03"] == 0
    assert layers["m04"] == 0
    # 后继层数严格大于先修层数
    for e in kg.prereq_edges:
        assert layers[e.target] > layers[e.source]


def test_prereq_queries(kg):
    assert "s02" in kg.prereqs_of("s03")       # 线性回归 → 逻辑回归
    assert "m02" in kg.prereqs_of("s02")       # 矩阵 → 线性回归
    assert "e03" in kg.prereqs_of("e04")      # GBDT 链：e01→e03→e04
    assert kg.prereqs_of("m01") == []
    assert "s03" in kg.successors_of("s02")
    assert "d02" in kg.successors_of("d01")


def test_related_edges_exist_and_do_not_affect_topo(kg):
    assert kg.related_edges, "应存在 related 边"
    layers = kg.topological_layers()
    # related 边可以出现在任意层（不参与先修约束），仅验证图结构完整
    assert len(kg.prereq_edges) + len(kg.related_edges) == len(kg.edges)


def test_lecture_fields_present(kg):
    """P0 门之一：全部节点有讲义占位字段（内容合并由 build_demo_data 校验）"""
    for nid, n in kg.nodes.items():
        assert isinstance(n.lecture, str)
        assert n.summary and n.keywords and n.objectives
