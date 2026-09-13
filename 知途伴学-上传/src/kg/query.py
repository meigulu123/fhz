"""图谱查询辅助：中心性、难度分布、概要表"""
from .loader import KnowledgeGraph


def degree_centrality(kg: KnowledgeGraph, normalize=True) -> dict:
    """先修图度数中心性（入度+出度），用于路径评分"""
    deg = {nid: 0 for nid in kg.nodes}
    for e in kg.prereq_edges:
        deg[e.source] += 1
        deg[e.target] += 1
    if normalize:
        mx = max(deg.values()) or 1
        return {k: v / mx for k, v in deg.items()}
    return deg


def node_table(kg: KnowledgeGraph) -> list:
    """全部节点概要行（附录知识点清单/探针展示用）"""
    rows = []
    for nid in sorted(kg.nodes):
        n = kg.nodes[nid]
        rows.append({
            "id": n.id, "name": n.name, "category": n.category,
            "difficulty": n.difficulty, "bloom": n.bloom,
            "minutes": n.minutes, "prereqs": kg.prereqs_of(nid),
        })
    return rows


def difficulty_distribution(kg: KnowledgeGraph) -> list:
    """按难度区间统计节点数（画像页 ZPD 带叠图用）"""
    buckets = {f"{i/10:.1f}~{(i+1)/10:.1f}": 0 for i in range(10)}
    for n in kg.nodes.values():
        idx = min(int(n.difficulty * 10), 9)
        key = f"{idx/10:.1f}~{(idx+1)/10:.1f}"
        buckets[key] += 1
    return list(buckets.items())
