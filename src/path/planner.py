"""ZPD 最近发展区路径规划

拓扑分层 → 前沿集（先修加权达标且未掌握）→ ZPD 难度带筛选 →
加权评分排序 → 取 batch 个。LLM 重规划触发时输出 JSON 建议（Mock 规则兜底）。
"""
import statistics

from src.kg.query import degree_centrality
from src.student.profile import cognitive_profile

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
    def score(self, nid: str, profile, band: dict) -> float:
        """score = 0.30·(1−|d−z_center|) + 0.25·(1−θ) + 0.20·中心性 + 0.15·目标相似度 + 0.10·认知契合"""
        node = self.kg.nodes[nid]
        term_z = 1.0 - abs(node.difficulty - band["z_center"])
        term_m = 1.0 - profile.mastery.get(nid, 0.0)
        term_c = self.centrality.get(nid, 0.0)
        term_g = self._goal_sim(node, profile)
        term_b = self._bloom_fit(node, profile)
        return 0.30 * term_z + 0.25 * term_m + 0.20 * term_c + 0.15 * term_g + 0.10 * term_b

    def _bloom_fit(self, node, profile) -> float:
        """认知层级契合度：目标 = 略高于当前认知层级（最近发展区），距离越近越高。
        认知画像带缓存：同批次评分只算一次。
        """
        level = cognitive_profile(profile, self.kg)["level"]
        target = max(1, min(6, int(round(level)) + 1))
        return 1.0 - abs(node.bloom - target) / 5.0

    @staticmethod
    def _goal_sim(node, profile) -> float:
        if not profile.goal_keywords:
            return 0.5
        inter = set(node.keywords) & set(profile.goal_keywords)
        return len(inter) / max(1, len(profile.goal_keywords))

    def _tier(self, node_difficulty: float, band: dict) -> str:
        if node_difficulty < band["z_low"]:
            return "复习"
        if node_difficulty > band["z_high"]:
            return "暂缓"
        return "A"

    # ---------- 出计划 ----------
    def plan(self, profile, batch: int = 5) -> dict:
        """返回 {items, band, frontier}；items 每项含 node_id/name/tier/score/原因"""
        band = self.zpd_band(profile)
        frontier = self.frontier(profile)
        scored = []
        for nid in frontier:
            tier = self._tier(self.kg.nodes[nid].difficulty, band)
            if tier == "暂缓":
                continue  # 超出 ZPD 带，暂不排入
            scored.append((self.score(nid, profile, band), nid, tier))
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
                "reason": self._reason_text(tier, band),
            })
        return {"items": items, "band": band, "frontier": frontier}

    @staticmethod
    def _reason_text(tier: str, band: dict) -> str:
        if tier == "A":
            return f"难度位于 ZPD 带（{band['z_low']}~{band['z_high']}）内，适合当前水平主修"
        return "难度低于 ZPD 带，作为复习巩固项排入"

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
