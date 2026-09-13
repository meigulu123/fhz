"""OpenAI 兼容客户端（星火/DeepSeek/Qwen/GLM 通用）"""
from openai import OpenAI

from .base import BaseLLM, LLMError


class OpenAICompatLLM(BaseLLM):
    def __init__(self, base_url, api_key, model, temperature=0.7,
                 max_retries=1, timeout=30, max_tokens=2048):
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        # max_retries=0：重试由本类的重试循环统一控制，避免与 SDK 默认重试叠加放大
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout,
                             max_retries=0)

    def _create(self, messages, **extra):
        # max_tokens 必须显式设上限：推理模型（如 spark-x2.5-4b）会先把大量 token
        # 花在 reasoning_content 思维链上，不设上限则单次调用几十秒甚至超时，
        # 登录开场白/教学等短文本场景会被阻塞到「进不去」。上限覆盖思考+正文。
        return self.client.chat.completions.create(
            model=self.model, messages=messages,
            temperature=self.temperature, max_tokens=self.max_tokens, **extra,
        )

    def chat(self, messages) -> str:
        last_err = None
        for _ in range(self.max_retries + 1):
            try:
                resp = self._create(messages)
                return resp.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001 —— 兼容层统一吞掉供应商异常后重试
                last_err = exc
        raise LLMError(f"LLM 请求失败（已重试 {self.max_retries} 次）：{last_err}")

    def chat_json(self, messages) -> dict:
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._create(messages, response_format={"type": "json_object"})
                return self._parse_json(resp.choices[0].message.content or "")
            except LLMError:
                if attempt == self.max_retries:
                    raise
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        # 结构化请求失败后降级：普通补全 + 通用解析
        try:
            return self._parse_json(self.chat(messages))
        except LLMError as exc:
            raise LLMError(f"JSON 模式失败且降级解析失败：{last_err}；{exc}") from exc
