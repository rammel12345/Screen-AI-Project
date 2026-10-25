from PIL import Image
from app.models import OcrStatus
from app.ocr import ocr_engine
from app.ocr.ocr_engine import OcrEngine
from app.ocr.text_preprocessor import clean_ocr_text, is_effectively_empty
from app.services.session_manager import SessionManager, QueueFull
import pytest


def img():
    return Image.new("RGB", (100, 50), "white")


def test_clean_preserves_lines_and_indent():
    raw = "def f():\r\n    return 1   \r\n\r\n\r\n\r\nprint(f())\x0c"
    assert clean_ocr_text(raw) == "def f():\n    return 1\n\nprint(f())"


def test_empty_detection():
    assert is_effectively_empty("") and is_effectively_empty(" \n .,- ")
    assert not is_effectively_empty("Error 404")


def test_engine_success(monkeypatch):
    monkeypatch.setattr(ocr_engine, "find_tesseract", lambda p="": "fake.exe")
    monkeypatch.setattr(ocr_engine, "run_tesseract", lambda i, l, psm=6: "Hello\nWorld\n")
    r = OcrEngine().extract(img())
    assert r.ok and r.text == "Hello\nWorld" and not r.empty


def test_engine_empty_result(monkeypatch):
    monkeypatch.setattr(ocr_engine, "find_tesseract", lambda p="": "fake.exe")
    monkeypatch.setattr(ocr_engine, "run_tesseract", lambda i, l, psm=6: "  \n\n")
    r = OcrEngine().extract(img())
    assert r.ok and r.empty and r.text == ""


def test_engine_missing_tesseract(monkeypatch):
    monkeypatch.setattr(ocr_engine, "find_tesseract", lambda p="": None)
    r = OcrEngine().extract(img())
    assert not r.ok and "Tesseract not found" in r.error


def test_engine_failure_is_caught(monkeypatch):
    monkeypatch.setattr(ocr_engine, "find_tesseract", lambda p="": "fake.exe")
    def boom(*a, **k): raise RuntimeError("bad lang")
    monkeypatch.setattr(ocr_engine, "run_tesseract", boom)
    r = OcrEngine().extract(img())
    assert not r.ok and "bad lang" in r.error


def test_no_confidence_field():
    from app.ocr.ocr_engine import OcrResult
    assert not hasattr(OcrResult("x", False), "confidence")


# ---- queue / session ----
def test_queue_add_remove_reorder():
    s = SessionManager()
    a, b, c = s.add(img()), s.add(img()), s.add(img())
    assert [x.id for x in s.queue] == [a.id, b.id, c.id]
    assert s.move(c.id, -1) and [x.id for x in s.queue] == [a.id, c.id, b.id]
    assert not s.move(a.id, -1)
    assert s.remove(c.id) and len(s.queue) == 2
    assert not s.remove(9999)


def test_queue_limit():
    s = SessionManager(queue_limit=2)
    s.add(img()); s.add(img())
    with pytest.raises(QueueFull):
        s.add(img())


def test_selection_and_edit():
    s = SessionManager()
    a, b = s.add(img()), s.add(img())
    b.selected = False
    s.set_ocr(a.id, OcrStatus.COMPLETED, "raw")
    s.set_text(a.id, "edited")
    assert [x.id for x in s.selected()] == [a.id]
    assert a.text == "edited" and a.ocr_status == OcrStatus.COMPLETED


def test_clear_all_wipes_everything():
    s = SessionManager()
    a = s.add(img()); a.text = "secret"
    s.start_conversation("general", "hi", 4096)
    s.add_assistant("ok")
    s.clear_all()
    assert s.queue == [] and s.history == []


def test_followup_requires_conversation():
    with pytest.raises(ValueError):
        SessionManager().followup("q", 4096)


def test_followup_appends():
    s = SessionManager()
    a = s.add(img()); a.text = "text"
    s.start_conversation("explain", "what?", 4096)
    s.add_assistant("answer")
    msgs = s.followup("and more?", 4096)
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]
