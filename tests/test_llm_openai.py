"""OpenAI 兼容层测试：本地假服务验证真实 LLM 代码路径（无真实 Key 也可验证）

覆盖：chat 文本补全、失败重试与重试耗尽、chat_json（response_format 注入、
JSON 解析、网络失败降级普通补全）、配置切换（provider+Key→真实 / 无 Key→Mock）。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.llm.base import LLMError
from src.llm.openai_compat import OpenAICompatLLM


def _ok(content):
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture()
def fake_server():
    """本地 OpenAI 兼容假服务：按队列返回 (status, payload)，记录全部请求"""
    state = {"requests": [], "queue": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            state["requests"].append((self.path, body))
            if state["queue"]:
                status, payload = state["queue"].pop(0)
            else:
                status, payload = 200, _ok("ok")
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # 静默访问日志
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", state
    srv.shutdown()
    t.join(timeout=5)


def make_llm(base_url):
    return OpenAICompatLLM(base_url=base_url, api_key="test-key",
                           model="lite", max_retries=2)


def test_chat_returns_content(fake_server):
    base, state = fake_server
    state["queue"].append((200, _ok("你好，同学")))
    reply = make_llm(base).chat([{"role": "user", "content": "你好"}])
    assert reply == "你好，同学"
    path, body = state["requests"][0]
    assert path == "/v1/chat/completions"
    assert body["model"] == "lite"
    assert body["messages"] == [{"role": "user", "content": "你好"}]
    assert body["temperature"] == 0.7


def test_chat_retries_then_succeeds(fake_server):
    base, state = fake_server
    state["queue"] += [(500, {"error": "boom"}), (200, _ok("恢复"))]
    assert make_llm(base).chat([{"role": "user", "content": "x"}]) == "恢复"
    assert len(state["requests"]) == 2


def test_chat_raises_after_exhaustion(fake_server):
    base, state = fake_server
    state["queue"] += [(500, {"error": "e"})] * 3
    with pytest.raises(LLMError):
        make_llm(base).chat([{"role": "user", "content": "x"}])
    assert len(state["requests"]) == 3  # max_retries=2 → 共 3 次，不叠加 SDK 重试


def test_chat_json_injects_response_format_and_parses(fake_server):
    base, state = fake_server
    state["queue"].append((200, _ok('{"intent": "answer", "choice": "B"}')))
    result = make_llm(base).chat_json([{"role": "user", "content": "选B"}])
    assert result == {"intent": "answer", "choice": "B"}
    assert state["requests"][0][1]["response_format"] == {"type": "json_object"}


def test_chat_json_network_fail_falls_back_to_plain(fake_server):
    base, state = fake_server
    state["queue"] += [(500, {"error": "e"})] * 3            # JSON 模式网络失败耗尽
    state["queue"].append((200, _ok('{"action": "continue"}')))  # 降级普通补全
    result = make_llm(base).chat_json([{"role": "user", "content": "x"}])
    assert result == {"action": "continue"}
    assert len(state["requests"]) == 4
    assert "response_format" not in state["requests"][-1][1]


def test_parse_json_markdown_fence():
    text = "好的，输出如下：\n```json\n{\"action\": \"reorder\"}\n```"
    assert OpenAICompatLLM._parse_json(text) == {"action": "reorder"}


def test_build_llm_switching(tmp_path):
    """有 provider+Key → ResilientLLM(真实, Mock 兜底)；无 Key → MockLLM"""
    from config.settings import build_llm, load_settings
    from src.llm.mock import MockLLM
    from src.llm.resilient import ResilientLLM
    cfg = load_settings({"paths": {"db": str(tmp_path / "t.db")},
                         "llm": {"provider": "openai", "api_key": "k",
                                 "base_url": "http://127.0.0.1:9/v1"}})
    llm = build_llm(cfg)
    assert isinstance(llm, ResilientLLM)
    assert isinstance(llm.primary, OpenAICompatLLM)
    assert isinstance(llm.fallback, MockLLM)
    cfg2 = load_settings({"paths": {"db": str(tmp_path / "t.db")},
                          "llm": {"provider": "openai", "api_key": ""}})
    assert isinstance(build_llm(cfg2), MockLLM)


def test_resilient_falls_back():
    """主通道故障时 ResilientLLM 自动降级到兜底，且计数递增"""
    from src.llm.resilient import ResilientLLM

    class _Boom:
        def chat(self, messages):
            raise LLMError("down")

        def chat_json(self, messages):
            raise LLMError("down")

    class _Ok:
        def chat(self, messages):
            return "fallback-text"

        def chat_json(self, messages):
            return {"intent": "answer"}

    r = ResilientLLM(_Boom(), _Ok())
    assert r.chat([{"role": "user", "content": "x"}]) == "fallback-text"
    assert r.chat_json([{"role": "user", "content": "x"}]) == {"intent": "answer"}
    assert r.fallbacks == 2
