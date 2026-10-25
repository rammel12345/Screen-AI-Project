import pytest
from app.config import validate_shortcut, validate_shortcuts, find_shortcut_conflicts, DEFAULT_SHORTCUTS
from app.shortcuts.shortcut_manager import to_pynput, ShortcutManager


@pytest.mark.parametrize("s", ["ctrl+shift+s", "Ctrl+Shift+Enter", "alt+f4", "ctrl+alt+1", "win+space"])
def test_valid(s):
    assert validate_shortcut(s) is None


@pytest.mark.parametrize("s", ["", "s", "ctrl", "ctrl+shift", "ctrl+a+b", "ctrl+ctrl+a", "ctrl++a", "ctrl+@@"])
def test_invalid(s):
    assert validate_shortcut(s) is not None


def test_defaults_ok():
    assert validate_shortcuts(DEFAULT_SHORTCUTS) == []


def test_conflict_detected():
    sc = dict(DEFAULT_SHORTCUTS, submit="Shift+Ctrl+S")
    assert find_shortcut_conflicts(sc)
    assert any("Conflict" in e for e in validate_shortcuts(sc))


def test_to_pynput():
    assert to_pynput("ctrl+shift+enter") == "<ctrl>+<shift>+<enter>"
    assert to_pynput("ctrl+shift+s") == "<ctrl>+<shift>+s"
    assert to_pynput("alt+f5") == "<alt>+<f5>"


def test_register_rejects_invalid_without_crash():
    m = ShortcutManager({a: (lambda: None) for a in DEFAULT_SHORTCUTS})
    assert m.register({"capture": "s"}) is False
    assert m.last_error and not m.running


def test_debounce():
    hits = []
    m = ShortcutManager({"capture": lambda: hits.append(1)})
    f = m._make("capture")
    f(); f(); f()
    assert len(hits) == 1
