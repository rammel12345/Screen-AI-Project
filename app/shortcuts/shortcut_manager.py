"""Global hotkeys using pynput. Triggers are user-initiated only.

Note: pynput observes keys; it cannot detect that another application has already
claimed the same combination. Internal duplicates are detected; for external
conflicts the user can change shortcuts in Settings.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from app.config import validate_shortcuts, normalize_shortcut

_KEY_MAP = {"ctrl": "<ctrl>", "shift": "<shift>", "alt": "<alt>", "win": "<cmd>",
            "enter": "<enter>", "space": "<space>", "backspace": "<backspace>",
            "tab": "<tab>", "esc": "<esc>", "delete": "<delete>", "insert": "<insert>",
            "home": "<home>", "end": "<end>", "pageup": "<page_up>", "pagedown": "<page_down>",
            "up": "<up>", "down": "<down>", "left": "<left>", "right": "<right>"}


def to_pynput(shortcut: str) -> str:
    out = []
    for p in normalize_shortcut(shortcut).split("+"):
        if p in _KEY_MAP:
            out.append(_KEY_MAP[p])
        elif p.startswith("f") and p[1:].isdigit():
            out.append(f"<{p}>")
        else:
            out.append(p)
    return "+".join(out)


def pretty(shortcut: str) -> str:
    return "+".join(p.capitalize() for p in normalize_shortcut(shortcut).split("+"))


class ShortcutManager:
    DEBOUNCE_SECONDS = 0.4

    def __init__(self, callbacks: dict[str, Callable[[], None]]):
        self.callbacks = callbacks
        self._listener = None
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.last_error = ""

    @property
    def running(self) -> bool:
        return self._listener is not None

    def _make(self, action: str):
        def fire():
            now = time.monotonic()
            with self._lock:
                if now - self._last.get(action, 0) < self.DEBOUNCE_SECONDS:
                    return  # avoid duplicate triggers from key repeat
                self._last[action] = now
            try:
                self.callbacks[action]()
            except Exception:
                pass  # never let a callback kill the listener thread
        return fire

    def register(self, shortcuts: dict[str, str]) -> bool:
        """Register all shortcuts. Returns False (and sets last_error) on failure."""
        self.unregister()
        errors = validate_shortcuts(shortcuts)
        if errors:
            self.last_error = "; ".join(errors)
            return False
        try:
            from pynput import keyboard
            mapping = {to_pynput(shortcuts[a]): self._make(a) for a in self.callbacks if a in shortcuts}
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
            self.last_error = ""
            return True
        except Exception as e:
            self._listener = None
            self.last_error = f"Could not register global shortcuts: {e}"
            return False

    def unregister(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
