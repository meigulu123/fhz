"""学生画像与掌握度初始化"""
import statistics
import time
from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class StudentProfile:
    student_id: str
    name: str = "同学"
    major: str = ""
    goals: List[str] = field(default_factory=list)          # 学习目标（文本）
    goal_keywords: List[str] = field(default_factory=list)  # 目标关键词（路径评分用）
    style_tags: List[str] = field(default_factory=list)     # 学习风格标签
    prior: Dict[str, float] = field(default_factory=dict)   # 诊断先验：node_id -> 0/0.5/1
    mastery: Dict[str, float] = field(default_factory=dict)
    evidence_count: Dict[str, int] = field(default_factory=dict)
    needs_review: Set[str] = field(default_factory=set)
    last_seen: Dict[str, float] = field(default_factory=dict)  # node_id -> 接触时间戳
    hint_profile: Dict[str, int] = field(default_factory=dict)  # node_id -> 退出层级 0~3
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """可序列化（session_state 持久化探针/落库用）"""
        d = self.__dict__.copy()
        d["needs_review"] = sorted(d["needs_review"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StudentProfile":
        d = dict(d)
        d["needs_review"] = set(d.get("needs_review", []))
        return cls(**d)


def init_mastery(profile: StudentProfile, kg) -> Dict[str, float]:
    """掌握度初始化（按拓扑顺序逐层计算，保证 prereq_avg 引用已算值）：

    θ_k⁰ = clip(0.25 + 0.40·prior + 0.35·prereq_avg − 0.15·I[∃先修 θ<0.6], 0.05, 0.85)

    prior 由对话诊断得 0/0.5/1.0；未诊断节点取中性先验 0.5。
    """
    layers = kg.topological_layers()
    order = sorted(kg.nodes, key=lambda nid: layers[nid])
    for nid in order:
        prior = profile.prior.get(nid, 0.5)
        prereqs = kg.prereqs_of(nid)
        avg = (sum(profile.mastery[p] for p in prereqs) / len(prereqs)) if prereqs else 0.5
        penalty = 0.15 if any(profile.mastery.get(p, 0.5) < 0.6 for p in prereqs) else 0.0
        theta = 0.25 + 0.40 * prior + 0.35 * avg - penalty
        profile.mastery[nid] = min(0.85, max(0.05, theta))
        profile.evidence_count[nid] = 0
    return profile.mastery


BLOOM_LABELS = {1: "记忆", 2: "理解", 3: "应用", 4: "分析", 5: "评价", 6: "创造"}


def cognitive_profile(profile: StudentProfile, kg) -> dict:
    """认知水平画像：按掌握度加权的平均布鲁姆层级 + 各层级掌握度分布。

    level = Σ(θ_n · bloom_n) / Σθ_n；distribution = 各 bloom 层级(1~6)的平均掌握度。
    """
    dist = {b: [] for b in range(1, 7)}
    for nid, node in kg.nodes.items():
        dist[node.bloom].append(profile.mastery.get(nid, 0.0))
    distribution = {b: round(statistics.mean(v), 3) for b, v in dist.items() if v}
    total_w = sum(profile.mastery.get(nid, 0.0) for nid in kg.nodes)
    weighted = sum(kg.nodes[nid].bloom * profile.mastery.get(nid, 0.0)
                   for nid in kg.nodes)
    level = round(weighted / total_w, 2) if total_w else 0.0
    label = BLOOM_LABELS.get(max(1, min(6, int(round(level)))), "")
    return {"level": level, "label": label, "distribution": distribution}
