"""应用环境构建（app.py 缓存包装；测试可绕过 Streamlit 直接调用）"""
from __future__ import annotations

import json
import re
from pathlib import Path

from config.settings import build_llm, load_settings
from src.agent.orchestrator import Orchestrator
from src.kg.loader import KnowledgeGraph
from src.memory.db import MemoryStore
from src.path.planner import PathPlanner

# 稀有 Unicode 排版码位 → 通用 ASCII 写法。
# 这些码位集中在「语音扩展 / 上下标 / 数学符号 A / 杂项技术」等字体覆盖很差的区段，
# 在字体不全的客户端会显示成方框（tofu），题面/选项看起来就成了“乱码”；
# 在构建环境时统一替换一次，题库文件保持原样，所有消费方（弹窗/对话/报告）拿到的一致。
# 注意：多字符组合必须排在被拆分的单字符之前（dict 按插入顺序替换）。
_GLYPH_MAP = {
    # 多字符组合
    "\u207b\u00b9": "^-1",          # ⁻¹
    "\u207b\u1dbb": "^-z",          # ⁻ᶻ（e⁻ᶻ）
    "\u207d\u02b2\u207e": "^(j)",   # ⁽ʲ⁾
    "c\u0303": "\u0109",            # c̃ → ĉ（预组合，字体通用）
    # 上标字母/数字
    "\u1d40": "^T",                 # ᵀ
    "\u1d50": "^m",                 # ᵐ
    "\u1d57": "^t",                 # ᵗ
    "\u1dbb": "^z",                 # ᶻ
    "\u02e3": "^x",                 # ˣ
    "\u02b2": "^j",                 # ʲ
    "\u2070": "^0", "\u00b9": "^1", "\u00b2": "^2", "\u00b3": "^3",
    "\u2077": "^7", "\u2078": "^8",
    "\u207d": "^(", "\u207e": ")",
    "\u207b": "^-",                 # ⁻
    # 下标字母/数字
    "\u1d62": "_i",                 # ᵢ
    "\u2c7c": "_j",                 # ⱼ
    "\u2080": "_0", "\u2081": "_1", "\u2082": "_2",
    "\u2093": "_x", "\u2096": "_k",
    # 数学符号 A / 通用标点
    "\u27e8": "<", "\u27e9": ">",   # ⟨ ⟩
    "\u2032": "'", "\u2033": "''",  # ′ ″
    "\u2016": "||",                 # ‖
    "\u2308": "ceil(", "\u2309": ")",  # ⌈ ⌉
    # 箭头
    "\u2192": "->", "\u2190": "<-", "\u21d2": "=>", "\u21d4": "<=>",
    # 组合符：帽子表示估计值 → 上标 ^
    "\u0302": "^",
    "\u0175": "w^",                 # ŵ（与 ŵ 写法统一）
}
_COMBINING_RE = re.compile(r"[\u0300-\u036f]+")


def _fix_glyphs(text):
    """把一段文案里的稀有数学码位替换为通用写法（非字符串原样返回）"""
    if not isinstance(text, str) or not text:
        return text
    for src, dst in _GLYPH_MAP.items():
        text = text.replace(src, dst)
    return _COMBINING_RE.sub("", text)


def normalize_questions(questions: list) -> list:
    """题库文案去 tofu：清理题干/选项/解析/提示里的稀有数学码位"""
    out = []
    for q in questions:
        nq = dict(q)
        for key in ("stem", "explanation"):
            if key in nq:
                nq[key] = _fix_glyphs(nq[key])
        if isinstance(nq.get("options"), list):
            nq["options"] = [_fix_glyphs(o) for o in nq["options"]]
        if isinstance(nq.get("hints"), dict):
            nq["hints"] = {k: _fix_glyphs(v) for k, v in nq["hints"].items()}
        out.append(nq)
    return out


def build_env(overrides: dict | None = None) -> dict:
    """构造 kg/llm/mem/planner/orch 环境。overrides 合并进配置（测试隔离用）"""
    cfg = load_settings(overrides)
    kg = KnowledgeGraph.load(cfg["paths"]["kg"])
    data = json.loads(Path(cfg["paths"]["questions"]).read_text(encoding="utf-8"))
    questions = normalize_questions(data["questions"])
    mem = MemoryStore(cfg["paths"]["db"])
    llm = build_llm(cfg)
    planner = PathPlanner(kg)
    orch = Orchestrator(kg, llm, mem, planner, questions)
    return {"kg": kg, "questions": questions, "mem": mem, "llm": llm,
            "planner": planner, "orch": orch, "cfg": cfg}
