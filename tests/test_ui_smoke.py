"""Headless end-to-end smoke test of the controller with mocked OCR and Ollama."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import pytest
from PIL import Image

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from app.config import Config
from app.models import OcrStatus
from app.ocr.ocr_engine import OcrResult
from app.ai.ollama_client import OllamaClient, ModelMissing
from app.shortcuts.shortcut_manager import ShortcutManager
from app.ui import main_window as mw


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def wait(qapp, cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def ctl(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(ShortcutManager, "register", lambda self, s: True)
    monkeypatch.setattr(mw, "save_config", lambda c, p=None: None)
    monkeypatch.setattr(OllamaClient, "version", lambda self: "0.0-test")
    monkeypatch.setattr(OllamaClient, "list_models", lambda self, include_cloud=False: [])
    monkeypatch.setattr(OllamaClient, "has_model", lambda self, m: True)
    sent = []

    def fake_stream(self, model, messages, ctx=4096, max_tokens=512, temperature=0.2):
        sent.append((model, messages))
        yield "Hello "
        yield "**world**"
    monkeypatch.setattr(OllamaClient, "chat_stream", fake_stream)
    c = mw.AppController(qapp, Config())
    monkeypatch.setattr(c.ocr, "extract", lambda img: OcrResult("line1\nline2", False))
    c.sent = sent
    yield c
    c.quit()
    qapp.processEvents()


def add_shot(c, qapp):
    s = c.session.add(Image.new("RGB", (200, 100), "white"))
    c._refresh_queue()
    c._run_ocr(s.id)
    assert wait(qapp, lambda: s.ocr_status == OcrStatus.COMPLETED)
    return s


def test_full_flow(ctl, qapp):
    s = add_shot(ctl, qapp)
    assert s.text == "line1\nline2"
    ctl.session.set_text(s.id, "edited text")          # user edit
    ctl.win.prompt.setText("What is this?")
    ctl.submit()
    assert wait(qapp, lambda: ctl._chat is None and ctl._last_answer)
    model, msgs = ctl.sent[0]
    assert model == "qwen2.5:3b"
    assert "edited text" in msgs[1].content and msgs[1].images is None
    assert "Hello **world**" in ctl._last_answer
    # follow-up without recapture
    ctl.followup("Tell me more")
    assert wait(qapp, lambda: len(ctl.sent) == 2 and ctl._chat is None)
    assert [m.role for m in ctl.sent[1][1]] == ["system", "user", "assistant", "user"]


def test_submit_requires_selection(ctl, qapp):
    ctl.submit()
    assert ctl.win.error.isVisible() or ctl.win.error.text()
    assert ctl.sent == []


def test_no_auto_submit_after_capture(ctl, qapp):
    add_shot(ctl, qapp)
    qapp.processEvents()
    assert ctl.sent == []


def test_pause_blocks_capture(ctl, qapp):
    ctl._pause_toggled(True)
    ctl.capture()
    assert ctl.session.queue == []


def test_missing_model_shows_command(ctl, qapp, monkeypatch):
    monkeypatch.setattr(OllamaClient, "has_model", lambda self, m: False)
    offered = []
    monkeypatch.setattr(ctl, "_offer_pull", lambda m: offered.append(m))
    add_shot(ctl, qapp)
    ctl.submit()
    assert wait(qapp, lambda: offered)
    assert "ollama pull qwen2.5:3b" in ctl.win.error.text()


def test_empty_text_blocked_in_text_mode(ctl, qapp, monkeypatch):
    monkeypatch.setattr(ctl.ocr, "extract", lambda img: OcrResult("", True))
    s = ctl.session.add(Image.new("RGB", (50, 50)))
    ctl._run_ocr(s.id)
    assert wait(qapp, lambda: s.ocr_status == OcrStatus.COMPLETED)
    ctl.submit()
    assert ctl.sent == [] and "No extracted text" in ctl.win.error.text()


def test_clear_all(ctl, qapp, monkeypatch):
    add_shot(ctl, qapp)
    ctl.session.start_conversation("general", "x", 4096)
    monkeypatch.setattr(ctl, "_confirm", lambda *a: True)
    ctl.clear_all()
    assert ctl.session.queue == [] and ctl.session.history == []


def test_vision_mode_sends_images(ctl, qapp, monkeypatch):
    monkeypatch.setattr(OllamaClient, "supports_vision", lambda self, m: True)
    monkeypatch.setattr(ctl, "_confirm", lambda *a: True)
    ctl.cfg.input_mode = "hybrid"
    add_shot(ctl, qapp)
    ctl.submit()
    assert wait(qapp, lambda: ctl.sent)
    model, msgs = ctl.sent[0]
    assert model == "qwen2.5vl:3b" and msgs[1].images and "line1" in msgs[1].content


def test_vision_rejected_for_text_model(ctl, qapp, monkeypatch):
    monkeypatch.setattr(OllamaClient, "supports_vision", lambda self, m: False)
    monkeypatch.setattr(ctl, "_confirm", lambda *a: True)
    ctl.cfg.input_mode = "vision"
    add_shot(ctl, qapp)
    ctl.submit()
    assert wait(qapp, lambda: "does not support image input" in ctl.win.error.text())
    assert ctl.sent == []
