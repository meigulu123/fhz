"""知识图谱数据模型：KGNode / KGEdge"""
from dataclasses import dataclass
from typing import List


@dataclass
class KGNode:
    id: str
    name: str
    category: str
    difficulty: float      # 0~1，由浅入深
    bloom: int             # 布鲁姆认知层级 1~6
    objectives: List[str]  # 学习目标
    minutes: int           # 建议学习时长（分钟）
    summary: str           # 一句话概述（画像/路径卡片用）
    lecture: str           # markdown 分段讲义，内嵌 [ASK:] 提问位
    keywords: List[str]    # 关键词（目标相似度评分/记忆检索用）

    @classmethod
    def from_dict(cls, d: dict) -> "KGNode":
        return cls(**d)


@dataclass
class KGEdge:
    source: str
    target: str
    type: str     # prerequisite（先修）| related（关联）
    weight: float

    @classmethod
    def from_dict(cls, d: dict) -> "KGEdge":
        return cls(**d)
