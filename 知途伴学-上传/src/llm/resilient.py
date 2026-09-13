"""ResilientLLM：主/备双通道 LLM 包装，主通道故障自动降级到兜底 Mock。

真实大模型模式（OpenAICompatLLM）在网络/限流/超时等故障时会抛 LLMError；
本包装把「降级到离线规则 MockLLM」收口到 LLM 层，使 Orchestrator / Scaffolder /
teach_segment / maybe_reflect 等所有 llm.chat / llm.chat_json 调用点无需各自
try/except 即可保证不因大模型故障而崩溃。
"""
import logging

from .base import BaseLLM

logger = logging.getLogger(__name__)


class ResilientLLM(BaseLLM):
    """主备包装：primary 失败自动回退 fallback；fallbacks 计数可观测降级次数。"""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback
        self.fallbacks = 0

    def chat(self, messages) -> str:
        try:
            return self.primary.chat(messages)
        except Exception as exc:  # noqa: BLE001 —— 真实 LLM 故障降级，保证不崩
            self.fallbacks += 1
            logger.warning("LLM 主通道失败，已降级到 Mock 兜底：%s", exc)
            return self.fallback.chat(messages)

    def chat_local(self, messages) -> str:
        """开场白等低延迟敏感文本直接走 Mock 兜底，跳过真实推理模型长考"""
        return self.fallback.chat(messages)

    def chat_json(self, messages) -> dict:
        try:
            return self.primary.chat_json(messages)
        except Exception as exc:  # noqa: BLE001
            self.fallbacks += 1
            logger.warning("LLM 主通道 JSON 失败，已降级到 Mock 兜底：%s", exc)
            return self.fallback.chat_json(messages)
