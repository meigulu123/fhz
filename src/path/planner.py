"""ZPD 最近发展区路径规划

拓扑分层 → 前沿集（先修加权达标且未掌握）→ ZPD 难度带筛选 →
加权评分排序 → 取 batch 个。LLM 重规划触发时输出 JSON 建议（Mock 规则兜底）。
"""
from __future__ import annotations

import statistics

from src.kg.query import degree_centrality
from src.student.profile import cognitive_profile, goal_keyword_set

MASTERED = 0.75    # θ≥0.75 视为已掌握
GATE = 0.6         # 先修加权平均 θ≥0.6 视为达标


class PathPlanner:
    def __init__(self, kg):
        self.kg = kg
        self.centrality = degree_centrality(kg)

    # ---------- ZPD 带 ----------
    def zpd_band(self, profile) -> dict:
        """z_low = mean(θ)，z_high = min(mean + 0.15 + 0.35σ, 0.95)"""
        thetas = list(profile.mastery.values()) or [0.45]
        mean = statistics.mean(thetas)
        sigma = statistics.pstdev(thetas) if len(thetas) > 1 else 0.10
        z_low = mean
        z_high = min(mean + 0.15 + 0.35 * sigma, 0.95)
        return {"z_low": round(z_low, 3), "z_high": round(z_high, 3),
                "z_center": round((z_low + z_high) / 2, 3)}

    # ---------- 前沿集 ----------
    def frontier(self, profile) -> list:
        """先修加权达标（≥0.6）且未掌握（θ<0.75）的节点"""
        out = []
        for nid in self.kg.nodes:
            if profile.mastery.get(nid, 0.0) >= MASTERED:
                continue
            prereqs = self.kg.prereqs_of(nid)
            if prereqs:
                avg = sum(profile.mastery.get(p, 0.0) for p in prereqs) / len(prereqs)
                if avg < GATE:
                    continue
            out.append(nid)
        return out

    # ---------- 评分 ----------
    def score_terms(self, nid: str, profile, band: dict, review=None) -> dict:
        """评分六因子明细（权重和为 1，供路径页展示「为什么排它在前」）

        ZPD 贴近 0.28 + 掌握度缺口 0.22 + 图谱中心性 0.17 + 目标关联 0.13
        + 认知契合 0.10 + 复习紧迫 0.10
        review：知识点 → 复习紧迫度（src.path.review.urgency_map）。
        """
        node = self.kg.nodes[nid]
        return {
            "ZPD 贴近": 0.28 * (1.0 - abs(node.difficulty - band["z_center"])),
            "掌握度缺口": 0.22 * (1.0 - profile.mastery.get(nid, 0.0)),
            "图谱中心性": 0.17 * self.centrality.get(nid, 0.0),
            "目标关联": 0.13 * self._goal_sim(node, profile),
            "认知契合": 0.10 * self._bloom_fit(node, profile),
            "复习紧迫": 0.10 * (review or {}).get(nid, 0.0),
        }

    def score(self, nid: str, profile, band: dict, review=None) -> float:
        return round(sum(self.score_terms(nid, profile, band, review).values()), 4)

    def _bloom_fit(self, node, profile) -> float:
        """认知层级契合度：目标 = 略高于当前认知层级（最近发展区），距离越近越高。
        认知画像带缓存：同批次评分只算一次。
        """
        level = cognitive_profile(profile, self.kg)["level"]
        target = max(1, min(6, int(round(level)) + 1))
        return 1.0 - abs(node.bloom - target) / 5.0

    def _goal_sim(self, node, profile) -> float:
        if not profile.goal_keywords:
            return 0.5
        kws = goal_keyword_set(profile, self.kg)
        inter = set(node.keywords) & kws
        return len(inter) / max(1, len(kws))

    def _tier(self, node_difficulty: float, band: dict) -> str:
        if node_difficulty < band["z_low"]:
            return "复习"
        if node_difficulty > band["z_high"]:
            return "暂缓"
        return "A"

    # ---------- 出计划 ----------
    def plan(self, profile, batch: int = 5, pace: float | None = None,
             review=None) -> dict:
        """返回 {items, band, frontier, pacing}；items 每项含 node_id/name/tier/score/原因

        review：知识点 → 复习紧迫度（第 6 个评分因子），使「到期该复习」的节点在
        同等条件下排到前面；不传则该项恒为 0（公式前五项权重之和仍为 0.90）。

        节奏适配：pace 由近 10 题正确率与卡壳次数算出（见 pacing.pace_params）。
        慢节奏（pace<0.8）只取 ZPD 带内偏易的一段，快节奏（pace>1.2）允许放宽到
        带上界去挑战更难的知识点；每批知识点数由 batch 控制。
        """
        band = self.zpd_band(profile)
        focus = "先修达标且难度落在 ZPD 带内的知识点"
        if pace is not None:
            span = band["z_high"] - band["z_low"]
            if pace < 0.8:
                band = dict(band, z_high=round(band["z_low"] + span * 0.7, 3))
                focus = "放慢节奏：只在 ZPD 带内偏易的一段里选，先把基础打牢"
            elif pace > 1.2:
                band = dict(band,
                            z_high=round(min(band["z_high"] + 0.05, 0.95), 3))
                focus = "加快节奏：难度带上界放宽，可以适当挑战更难的知识点"
        frontier = self.frontier(profile)
        scored = []
        for nid in frontier:
            tier = self._tier(self.kg.nodes[nid].difficulty, band)
            if tier == "暂缓":
                continue  # 超出 ZPD 带，暂不排入
            scored.append((self.score(nid, profile, band, review), nid, tier))
        scored.sort(key=lambda t: -t[0])
        items = []
        for s, nid, tier in scored[:batch]:
            node = self.kg.nodes[nid]
            items.append({
                "node_id": nid,
                "name": node.name,
                "score": round(s, 3),
                "tier": tier,
                "difficulty": node.difficulty,
                "mastery": round(profile.mastery.get(nid, 0.0), 3),
                "terms": {k: round(v, 3) for k, v in
                          self.score_terms(nid, profile, band, review).items()},
                "reason": self._personal_reason(nid, profile, band, tier),
            })
        return {"items": items, "band": band, "frontier": frontier,
                "pacing": {"pace": pace, "batch": batch, "focus": focus}}

    def _personal_reason(self, nid, profile, band: dict, tier: str) -> str:
        """逐条理由：结合该生自己的掌握度、难度、ZPD 带与学习目标"""
        node = self.kg.nodes[nid]
        theta = round(profile.mastery.get(nid, 0.0), 2)
        if tier == "复习":
            return (f"难度 {node.difficulty:.2f} 低于你的 ZPD 带，当前掌握度 {theta}，"
                    f"作为复习巩固项排入，补上它后面才走得稳")
        goal_hit = set(node.keywords) & goal_keyword_set(profile, self.kg)
        if goal_hit:
            return (f"难度 {node.difficulty:.2f} 正好落在你的 ZPD 带（{band['z_low']}~"
                    f"{band['z_high']}）内，且与你的学习目标直接相关"
                    f"（命中 {len(goal_hit)} 个目标关键词），掌握度 {theta}，优先主修")
        return (f"难度 {node.difficulty:.2f} 落在你的 ZPD 带（{band['z_low']}~"
                f"{band['z_high']}）内，当前掌握度 {theta}，适合作为当前水平的主修内容")

    # ---------- 重规划（规则兜底；LLM 模式由真实模型输出同构 JSON） ----------
    def replan_rules(self, profile, trigger: str, node_id: str) -> dict:
        if trigger in ("stuck_l3", "prereq_collapse"):
            prereqs = self.kg.prereqs_of(node_id)
            if prereqs:
                weakest = min(prereqs, key=lambda p: profile.mastery.get(p, 0.0))
                return {
                    "action": "review_prereq",
                    "node_id": weakest,
                    "reason": "当前知识点反复卡住，先回补最薄弱的先修知识点",
                    "new_order": [weakest, node_id],
                }
        return {
            "action": "reorder",
            "node_id": node_id,
            "reason": "按最新掌握度重排学习顺序",
            "new_order": [node_id],
        }
