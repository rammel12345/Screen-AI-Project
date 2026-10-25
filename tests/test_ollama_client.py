import json
import pytest
import requests
from app.ai.ollama_client import (OllamaClient, OllamaError, OllamaUnavailable, ModelMissing,
                                  OllamaTimeout, OllamaCancelled)
from app.models import ChatMessage

BASE = "http://127.0.0.1:11434"
MSGS = [ChatMessage("system", "s"), ChatMessage("user", "hi")]


class FakeResp:
    def __init__(self, lines=(), status=200, body=None):
        self.lines, self.status_code, self._body = list(lines), status, body or {}
        self.text = json.dumps(self._body)
        self.ok = status < 400
        self.closed = False
    def json(self): return self._body
    def raise_for_status(self):
        if not self.ok: raise requests.HTTPError("x")
    def iter_lines(self):
        for l in self.lines:
            yield l if isinstance(l, bytes) else json.dumps(l).encode()
    def close(self): self.closed = True


def stream(chunks):
    out = [{"message": {"content": c}, "done": False} for c in chunks]
    out.append({"message": {"content": ""}, "done": True})
    return out


def test_remote_rejected():
    with pytest.raises(OllamaError):
        OllamaClient("http://example.com:11434")


def test_payload_format():
    p = OllamaClient.build_payload("qwen2.5:3b", MSGS, 2048, 256, 0.1)
    assert p["model"] == "qwen2.5:3b" and p["stream"] is True
    assert p["options"] == {"num_ctx": 2048, "num_predict": 256, "temperature": 0.1}
    assert p["messages"][0] == {"role": "system", "content": "s"}
    assert "images" not in p["messages"][1]


def test_payload_images():
    m = [ChatMessage("user", "x", images=["AAA"])]
    assert OllamaClient.build_payload("m", m, 1, 1, 0)["messages"][0]["images"] == ["AAA"]


def test_chat_stream_ok(monkeypatch):
    sent = {}
    def post(url, json=None, **kw):
        sent["url"], sent["json"] = url, json
        return FakeResp(stream(["Hel", "lo"]))
    monkeypatch.setattr(requests, "post", post)
    c = OllamaClient(BASE)
    assert c.chat("m", MSGS) == "Hello"
    assert sent["url"] == BASE + "/api/chat"


def test_connection_failure(monkeypatch):
    def post(*a, **k): raise requests.ConnectionError("refused")
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(OllamaUnavailable):
        OllamaClient(BASE).chat("m", MSGS)


def test_timeout(monkeypatch):
    def post(*a, **k): raise requests.Timeout()
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(OllamaTimeout):
        OllamaClient(BASE).chat("m", MSGS)


def test_missing_model_404(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(status=404, body={"error": "model 'x' not found"}))
    with pytest.raises(ModelMissing) as e:
        OllamaClient(BASE).chat("x", MSGS)
    assert e.value.command == "ollama pull x"
    assert "ollama pull x" in str(e.value)


def test_missing_model_in_stream(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp([{"error": "model not found"}]))
    with pytest.raises(ModelMissing):
        OllamaClient(BASE).chat("x", MSGS)


def test_inference_error(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp([{"error": "out of memory"}]))
    with pytest.raises(OllamaError, match="out of memory"):
        OllamaClient(BASE).chat("x", MSGS)


def test_malformed_json(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp([b"{not json"]))
    with pytest.raises(OllamaError, match="Malformed"):
        OllamaClient(BASE).chat("x", MSGS)


def test_truncated_stream(monkeypatch):
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: FakeResp([{"message": {"content": "a"}, "done": False}]))
    with pytest.raises(OllamaError, match="incomplete"):
        OllamaClient(BASE).chat("x", MSGS)


def test_http_500(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(status=500, body={"error": "boom"}))
    with pytest.raises(OllamaError, match="boom"):
        OllamaClient(BASE).chat("x", MSGS)


def test_cancel(monkeypatch):
    c = OllamaClient(BASE)
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(stream(["a", "b", "c"])))
    it = c.chat_stream("m", MSGS)
    assert next(it) == "a"
    c.cancel()
    with pytest.raises(OllamaCancelled):
        next(it)


def test_list_models_filters_cloud(monkeypatch):
    body = {"models": [{"name": "qwen2.5:3b", "size": 1}, {"name": "big:cloud"},
                       {"name": "x-cloud"}, {"name": "r", "remote_host": "https://ollama.com"}]}
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(body=body))
    c = OllamaClient(BASE)
    assert [m.name for m in c.list_models()] == ["qwen2.5:3b"]
    assert c.has_model("qwen2.5:3b") and not c.has_model("big:cloud")


def test_list_models_unavailable(monkeypatch):
    def get(*a, **k): raise requests.ConnectionError()
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(OllamaUnavailable):
        OllamaClient(BASE).list_models()
    assert OllamaClient(BASE).is_running() is False


def test_supports_vision_capabilities(monkeypatch):
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: FakeResp(body={"capabilities": ["completion", "vision"]}))
    assert OllamaClient(BASE).supports_vision("qwen2.5vl:3b")
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(body={"capabilities": ["completion"]}))
    assert not OllamaClient(BASE).supports_vision("qwen2.5vl:3b")


def test_supports_vision_missing(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(status=404))
    with pytest.raises(ModelMissing):
        OllamaClient(BASE).supports_vision("nope")
