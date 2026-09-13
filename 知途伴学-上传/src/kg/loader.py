"""知识图谱加载、拓扑分层、无环校验"""
import json
from collections import defaultdict, deque
from pathlib import Path

from .models import KGNode, KGEdge


class KnowledgeGraph:
    """先修图（prerequisite 边）+ 关联边（related）的统一查询结构。

    拓扑分层与无环校验只针对 prerequisite 边；related 边不参与。
    """

    def __init__(self, nodes, edges):
        self.nodes = {n.id: n for n in nodes}
        self.edges = edges
        self.prereq_edges = [e for e in edges if e.type == "prerequisite"]
        self.related_edges = [e for e in edges if e.type == "related"]
        self._prereq_out = defaultdict(list)   # node -> 后继（以它为先修的节点）
        self._prereq_in = defaultdict(list)    # node -> 先修节点
        for e in self.prereq_edges:
            self._prereq_out[e.source].append(e.target)
            self._prereq_in[e.target].append(e.source)
        self._check_acyclic()

    # ---------- 基本查询 ----------
    def prereqs_of(self, node_id: str):
        return list(self._prereq_in.get(node_id, []))

    def successors_of(self, node_id: str):
        return list(self._prereq_out.get(node_id, []))

    def categories(self) -> dict:
        """按类别分组节点 ID（保持定义顺序）"""
        out = {}
        for n in self.nodes.values():
            out.setdefault(n.category, []).append(n.id)
        return out

    def topological_layers(self) -> dict:
        """Kahn 算法对先修图分层，返回 {node_id: layer}（0 为无先修）"""
        indeg = {nid: len(self.prereqs_of(nid)) for nid in self.nodes}
        q = deque(nid for nid, d in indeg.items() if d == 0)
        layers, layer, visited = {}, 0, 0
        while q:
            for _ in range(len(q)):
                nid = q.popleft()
                layers[nid] = layer
                visited += 1
                for s in self.successors_of(nid):
                    indeg[s] -= 1
                    if indeg[s] == 0:
                        q.append(s)
            layer += 1
        if visited != len(self.nodes):
            raise ValueError("先修图存在环，无法完成拓扑分层")
        return layers

    # ---------- 校验 ----------
    def _check_acyclic(self):
        try:
            self.topological_layers()
        except ValueError as exc:
            raise ValueError(f"KG 先修图无环校验失败：{exc}") from exc

    @classmethod
    def load(cls, path) -> "KnowledgeGraph":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        nodes = [KGNode.from_dict(n) for n in data["nodes"]]
        edges = [KGEdge.from_dict(e) for e in data["edges"]]
        return cls(nodes, edges)
