"""pytest 全局配置：强制离线 Mock 模式，隔离 .env 里的真实 API Key。

项目支持「真实大模型 / MockLLM 离线兜底」双通道。为保证测试确定、秒级完成，
无论本机 .env 是否配置了真实 Key，测试一律走 MockLLM（不联网）。

若不隔离：.env 存在有效 Key 时，UI 冒烟用例（test_app_ui.py）会经 build_env
构造真实大模型并发起网络调用，推理模型响应慢会导致用例挂起。
"""
import os

# 置为 mock 并清空 Key，避免 load_settings 读到 .env 的 LLM_API_KEY。
# 注意用空串覆盖而非 pop：_load_dotenv 只设置「不存在的键」，空串可阻止其回填。
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""
