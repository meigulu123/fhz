"""三级配置合并：config.yaml < 环境变量 < 运行时覆盖（UI sidebar）"""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """加载项目根目录 .env（仅设置尚未存在的环境变量，不覆盖已设值）。

    .env 已加入 .gitignore，用于存放 API Key 等本地敏感配置，避免随作品提交。
    """
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def load_settings(overrides: dict | None = None) -> dict:
    _load_dotenv()
    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    llm = cfg.get("llm", {})
    # 环境变量覆盖
    if os.getenv("LLM_PROVIDER"):
        llm["provider"] = os.environ["LLM_PROVIDER"]
    if os.getenv("LLM_API_KEY"):
        llm["api_key"] = os.environ["LLM_API_KEY"]
    if os.getenv("LLM_BASE_URL"):
        llm["base_url"] = os.environ["LLM_BASE_URL"]
    if os.getenv("LLM_MODEL"):
        llm["model"] = os.environ["LLM_MODEL"]
    cfg["llm"] = llm
    if os.getenv("GUOCHUANG_DB"):
        cfg["paths"]["db"] = os.environ["GUOCHUANG_DB"]
    # 运行时覆盖（键与 config.yaml 对齐）
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    # 相对路径转绝对路径
    cfg["paths"] = {
        k: (v if Path(v).is_absolute() else str(ROOT / v))
        for k, v in cfg["paths"].items()
    }
    return cfg


def build_llm(cfg: dict):
    """按配置构造 LLM 实例；provider=mock 或无 Key 时走 MockLLM（离线兜底）。

    真实模式额外包一层 ResilientLLM：主通道故障自动降级 Mock，保证不崩。
    """
    from src.kg.loader import KnowledgeGraph
    from src.llm.mock import MockLLM
    from src.llm.openai_compat import OpenAICompatLLM
    from src.llm.resilient import ResilientLLM

    llm = cfg["llm"]
    kg = KnowledgeGraph.load(cfg["paths"]["kg"])
    questions = json.loads(
        Path(cfg["paths"]["questions"]).read_text(encoding="utf-8"))
    fallback = MockLLM(kg, questions["questions"])
    if llm.get("provider") != "mock" and llm.get("api_key"):
        primary = OpenAICompatLLM(
            base_url=llm["base_url"], api_key=llm["api_key"],
            model=llm["model"], temperature=llm.get("temperature", 0.7),
            max_tokens=int(llm.get("max_tokens", 2048)),
        )
        return ResilientLLM(primary, fallback)
    return fallback
