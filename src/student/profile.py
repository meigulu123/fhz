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
    # 缓存：认知画像指纹与结果，掌握度变化时自动失效
    _cog_fingerprint: str = field(default_factory=str, repr=False)
    _cog_cache: dict = field(default_factory=dict, repr=False)
    # 缓存：掌握度统计指纹
    _stats_fingerprint: str = field(default_factory=str, repr=False)
    _stats_cache: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        """可序列化（session_state 持久化探针/落库用）
        缓存字段不序列化，每次恢复后自然重建（避免跨版本兼容问题）
        """
        d = self.__dict__.copy()
        d["needs_review"] = sorted(d["needs_review"])
        # 缓存字段不持久化
        for k in ("_cog_fingerprint", "_cog_cache",
                  "_stats_fingerprint", "_stats_cache"):
            d.pop(k, None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StudentProfile":
        d = dict(d)
        d["needs_review"] = set(d.get("needs_review", []))
        # 清理旧版本可能残留的缓存字段
        for k in ("_cog_fingerprint", "_cog_cache",
                  "_stats_fingerprint", "_stats_cache"):
            d.pop(k, None)
        return cls(**d)

    def mastery_fingerprint(self) -> str:
        """掌握度指纹：mastery + evidence_count 的紧凑哈希，用于缓存失效判定"""
        import hashlib
        # 只取核心字段做指纹，避免序列化开销
        items = sorted(f"{k}:{round(v,4)}" for k, v in self.mastery.items())
        return hashlib.md5("|".join(items).encode()).hexdigest()[:12]

    def get_cognitive_cache(self, fingerprint: str):
        """获取缓存的认知画像，指纹不匹配返回 None"""
        if self._cog_fingerprint == fingerprint and self._cog_cache:
            return dict(self._cog_cache)
        return None

    def set_cognitive_cache(self, fingerprint: str, result: dict):
        """缓存认知画像结果"""
        self._cog_fingerprint = fingerprint
        self._cog_cache = dict(result)

    def get_stats_cache(self, fingerprint: str):
        """获取缓存的掌握度统计"""
        if self._stats_fingerprint == fingerprint and self._stats_cache:
            return dict(self._stats_cache)
        return None

    def set_stats_cache(self, fingerprint: str, result: dict):
        """缓存掌握度统计结果"""
        self._stats_fingerprint = fingerprint
        self._stats_cache = dict(result)


def init_mastery(profile: StudentProfile, kg) -> Dict[str, float]:
    """掌握度初始化（按拓扑顺序逐层计算，保证 prereq_avg 引用已算值）：

    已测节点（对话诊断自述学过）：
    θ_k⁰ = clip(0.25 + 0.40·prior + 0.35·prereq_avg − 0.15·I[∃先修 θ<0.6], 0.05, 0.85)
    未测节点（既未自述、也无答题证据）：
    θ_k⁰ = clip(0.12 + 0.30·prereq_avg − 0.5·penalty, 0.05, 0.85)

    未测节点不再给中性先验 0.5：零基础学生的画像不应被「没人测过的节点」
    抬到中等水平，否则雷达图与真实答题正确率严重不符。已测节点沿用原公式。
    """
    layers = kg.topological_layers()
    order = sorted(kg.nodes, key=lambda nid: layers[nid])
    for nid in order:
        prereqs = kg.prereqs_of(nid)
        avg = (sum(profile.mastery[p] for p in prereqs) / len(prereqs)) if prereqs else 0.5
        penalty = 0.15 if any(profile.mastery.get(p, 0.5) < 0.6 for p in prereqs) else 0.0
        if nid in profile.prior:
            theta = 0.25 + 0.40 * profile.prior[nid] + 0.35 * avg - penalty
        else:
            theta = 0.12 + 0.30 * avg - 0.5 * penalty
        profile.mastery[nid] = min(0.85, max(0.05, theta))
        profile.evidence_count[nid] = 0
    return profile.mastery


def is_untested(profile: StudentProfile, nid: str) -> bool:
    """未测节点：既无答题证据，也不在诊断先验里（画像上按「未测」灰档处理）"""
    return profile.evidence_count.get(nid, 0) == 0 and nid not in profile.prior


BLOOM_LABELS = {1: "记忆", 2: "理解", 3: "应用", 4: "分析", 5: "评价", 6: "创造"}


def goal_keyword_set(profile, kg) -> set:
    """归一化学习目标关键词集合：关键词字符串与知识点 ID 两种写法都接受。

    对话诊断的规则路径给出关键词字符串（与 node.keywords 同域），大模型路径
    给出知识点 ID；统一成关键词集合后，路径评分与目标命中判断才能一致生效。
    """
    out = set()
    for k in getattr(profile, "goal_keywords", []) or []:
        node = kg.nodes.get(k)
        if node is not None:
            out.update(node.keywords)
            out.add(node.name)
        else:
            out.add(k)
    return out


def goal_node_names(profile, kg, limit: int = 8) -> list:
    """与学习目标相关的知识点名称（画像统计与对话分析引用）"""
    raw = list(getattr(profile, "goal_keywords", []) or [])
    names = [kg.nodes[k].name for k in raw if k in kg.nodes]
    if not names:
        kws = set(raw)
        names = [n.name for n in kg.nodes.values() if set(n.keywords) & kws]
    return list(dict.fromkeys(names))[:limit]


def cognitive_profile(profile: StudentProfile, kg, use_cache: bool = True) -> dict:
    """认知水平画像：按掌握度加权的平均布鲁姆层级 + 各层级掌握度分布。

    level = Σ(θ_n · bloom_n) / Σθ_n；distribution = 各 bloom 层级(1~6)的平均掌握度。
    带缓存：掌握度指纹不变时直接返回缓存结果，避免全量遍历。
    """
    fp = profile.mastery_fingerprint()
    if use_cache:
        cached = profile.get_cognitive_cache(fp)
        if cached is not None:
            return cached
    dist = {b: [] for b in range(1, 7)}
    for nid, node in kg.nodes.items():
        dist[node.bloom].append(profile.mastery.get(nid, 0.0))
    distribution = {b: round(statistics.mean(v), 3) for b, v in dist.items() if v}
    total_w = sum(profile.mastery.get(nid, 0.0) for nid in kg.nodes)
    weighted = sum(kg.nodes[nid].bloom * profile.mastery.get(nid, 0.0)
                   for nid in kg.nodes)
    level = round(weighted / total_w, 2) if total_w else 0.0
    label = BLOOM_LABELS.get(max(1, min(6, int(round(level)))), "")
    result = {"level": level, "label": label, "distribution": distribution}
    if use_cache:
        profile.set_cognitive_cache(fp, result)
    return result
