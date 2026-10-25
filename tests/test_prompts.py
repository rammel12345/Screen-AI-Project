from PIL import Image
from app.ai.prompts import (SYSTEM_PROMPTS, build_initial_messages, build_screen_context,
                            build_followup, trim_history, DEFAULT_PROMPTS)
from app.models import Screenshot, ChatMessage


def shot(text):
    s = Screenshot(Image.new("RGB", (10, 10)))
    s.text = text
    return s


def test_three_distinct_modes():
    assert set(SYSTEM_PROMPTS) == {"explain", "coding", "general"}
    assert len(set(SYSTEM_PROMPTS.values())) == 3
    assert "never" in SYSTEM_PROMPTS["coding"].lower() or "cannot execute" in SYSTEM_PROMPTS["coding"]


def test_order_and_edited_text_used():
    ctx = build_screen_context([shot("FIRST"), shot("SECOND")])
    assert ctx.index("FIRST") < ctx.index("SECOND")
    assert "Screenshot 1" in ctx and "Screenshot 2" in ctx


def test_empty_text_marked():
    assert "no text recognized" in build_screen_context([shot("")])


def test_initial_messages_text_mode_has_no_images():
    msgs = build_initial_messages("coding", "why?", [shot("Traceback")], 4096)
    assert msgs[0].role == "system" and msgs[1].role == "user"
    assert "Traceback" in msgs[1].content and "why?" in msgs[1].content
    assert msgs[1].images is None


def test_blank_prompt_uses_default():
    msgs = build_initial_messages("explain", "  ", [shot("x")], 4096)
    assert DEFAULT_PROMPTS["explain"] in msgs[1].content


def test_truncation_to_context():
    msgs = build_initial_messages("general", "q", [shot("a" * 100000)], 2048)
    assert len(msgs[1].content) < 2048 * 3
    assert "truncated" in msgs[1].content


def test_vision_mode_images_only():
    msgs = build_initial_messages("general", "q", [shot("x")], 4096, images=["AAA"], include_text=False)
    assert msgs[1].images == ["AAA"] and "OCR text" not in msgs[1].content


def test_hybrid_has_text_and_images():
    msgs = build_initial_messages("general", "q", [shot("hello")], 4096, images=["AAA"], include_text=True)
    assert msgs[1].images == ["AAA"] and "hello" in msgs[1].content


def test_followup_does_not_mutate():
    h = [ChatMessage("system", "s"), ChatMessage("user", "u")]
    out = build_followup(h, "next")
    assert len(h) == 2 and out[-1].content == "next"


def test_trim_keeps_head_and_latest():
    h = [ChatMessage("system", "S"), ChatMessage("user", "U")]
    for i in range(50):
        h += [ChatMessage("assistant", "a" * 500), ChatMessage("user", f"q{i}")]
    t = trim_history(h, 2048)
    assert t[:2] == h[:2] and t[-1].content == "q49" and len(t) < len(h)
