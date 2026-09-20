"""应用环境构建（app.py 缓存包装；测试可绕过 Streamlit 直接调用）"""
from __future__ import annotations

import json
from pathlib import Path

from config.settings import build_llm, load_settings
from src.agent.orchestrator import Orchestrator
from src.kg.loader import KnowledgeGraph
from src.memory.db import MemoryStore
from src.path.planner import PathPlanner


def build_env(overrides: dict | None = None) -> dict:
    """构造 kg/llm/mem/planner/orch 环境。overrides 合并进配置（测试隔离用）"""
    cfg = load_settings(overrides)
    kg = KnowledgeGraph.load(cfg["paths"]["kg"])
    data = json.loads(Path(cfg["paths"]["questions"]).read_text(encoding="utf-8"))
    questions = data["questions"]
    mem = MemoryStore(cfg["paths"]["db"])
    llm = build_llm(cfg)
    planner = PathPlanner(kg)
    orch = Orchestrator(kg, llm, mem, planner, questions)
    return {"kg": kg, "questions": questions, "mem": mem, "llm": llm,
            "planner": planner, "orch": orch, "cfg": cfg}
