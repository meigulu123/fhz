"""LLM 抽象层：业务代码只依赖 chat / chat_json 两个接口。

约定：
- messages 为 OpenAI 风格 [{"role": "system"|"user"|"assistant", "content": str}]
- system 首条可用 "[TPL:模板名]" 标记模板类型，MockLLM 据此做规则路由
- 上下文中可嵌入 "[node=<id>]"、"[question_id=<id>]"、"[level=L1]"、
  "[stats_json={...}]" 等标记——真实 LLM 视其为上下文，MockLLM 视其为路由键
"""
import json
import re
from abc import ABC, abstractmethod


class LLMError(Exception):
    pass


class BaseLLM(ABC):
    """所有大模型（含 Mock）的统一接口"""

    @abstractmethod
    def chat(self, messages) -> str:
        """文本补全"""

    def chat_local(self, messages) -> str:
        """本地快速通道：低价值/低延迟敏感的确定性文本（如开场白）走离线模板，
        不等待真实推理模型长考。默认即普通 chat；真实 LLM 包装器覆盖为走兜底 Mock。"""
        return self.chat(messages)

    def chat_json(self, messages) -> dict:
        """结构化输出：要求模型返回 JSON 对象"""
        text = self.chat(messages)
        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{.*\}", text, re.S)  # 提取首个 {...} 块
        if not m:
            raise LLMError(f"模型输出无法解析为 JSON：{text[:200]}")
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError(f"JSON 修复失败：{exc}；原文：{text[:200]}")


# ---------- 消息构造辅助 ----------

def sys(tpl: str, content: str) -> dict:
    """system 消息：tpl 为模板名（Mock 路由键），content 为提示词正文"""
    return {"role": "system", "content": f"[TPL:{tpl}]\n{content}"}


def usr(content: str) -> dict:
    return {"role": "user", "content": content}
