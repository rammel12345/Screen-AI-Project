"""Configuration: non-sensitive preferences only, stored in a local JSON file."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_SHORTCUTS = {
    "capture": "ctrl+shift+s",
    "submit": "ctrl+shift+enter",
    "toggle": "ctrl+shift+space",
    "clear": "ctrl+shift+backspace",
}
SHORTCUT_LABELS = {
    "capture": "Capture screen",
    "submit": "Submit queue",
    "toggle": "Show/hide window",
    "clear": "Clear queue",
}

MODIFIERS = {"ctrl", "shift", "alt", "win"}
NAMED_KEYS = {
    "enter", "space", "backspace", "tab", "esc", "delete", "insert", "home", "end",
    "pageup", "pagedown", "up", "down", "left", "right",
} | {f"f{i}" for i in range(1, 13)}

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
VALID_MODES = ("explain", "coding", "general")
VALID_INPUT_MODES = ("text", "vision", "hybrid")
VALID_THEMES = ("dark", "light")


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "LocalScreenAI"


def config_path() -> Path:
    return config_dir() / "config.json"


def normalize_shortcut(s: str) -> str:
    parts = [p.strip().lower() for p in re.split(r"\+", s or "") if p.strip()]
    mods = [m for m in ("ctrl", "shift", "alt", "win") if m in parts]
    keys = [p for p in parts if p not in MODIFIERS]
    return "+".join(mods + keys)


def validate_shortcut(s: str) -> str | None:
    """Return an error message, or None if valid."""
    if not s or not s.strip():
        return "Shortcut is empty."
    parts = [p.strip().lower() for p in s.split("+")]
    if any(not p for p in parts):
        return "Shortcut has an empty part."
    mods = [p for p in parts if p in MODIFIERS]
    keys = [p for p in parts if p not in MODIFIERS]
    if len(set(mods)) != len(mods):
        return "Duplicate modifier."
    if not mods:
        return "Shortcut needs at least one modifier (Ctrl, Shift, Alt, Win)."
    if len(keys) != 1:
        return "Shortcut needs exactly one non-modifier key."
    k = keys[0]
    if not (len(k) == 1 and k.isalnum()) and k not in NAMED_KEYS:
        return f"Unsupported key '{k}'."
    return None


def find_shortcut_conflicts(shortcuts: dict[str, str]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    out = []
    for action, sc in shortcuts.items():
        n = normalize_shortcut(sc)
        if n in seen:
            out.append((seen[n], action))
        else:
            seen[n] = action
    return out


def validate_shortcuts(shortcuts: dict[str, str]) -> list[str]:
    errors = []
    for action in DEFAULT_SHORTCUTS:
        if action not in shortcuts:
            errors.append(f"Missing shortcut for {action}.")
            continue
        e = validate_shortcut(shortcuts[action])
        if e:
            errors.append(f"{SHORTCUT_LABELS[action]}: {e}")
    for a, b in find_shortcut_conflicts({k: v for k, v in shortcuts.items() if k in DEFAULT_SHORTCUTS}):
        errors.append(f"Conflict: '{a}' and '{b}' use the same shortcut.")
    return errors


def is_local_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and (p.hostname or "") in LOCAL_HOSTS


@dataclass
class Config:
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:3b"
    vision_model: str = "qwen2.5vl:3b"
    assistant_mode: str = "explain"
    input_mode: str = "text"
    context_length: int = 4096
    max_response_tokens: int = 512
    temperature: float = 0.2
    request_timeout: int = 180
    max_screenshots: int = 5
    queue_limit: int = 10
    shortcuts: dict = field(default_factory=lambda: dict(DEFAULT_SHORTCUTS))
    monitor: int = 1
    ocr_language: str = "eng"
    tesseract_path: str = ""
    preprocess_grayscale: bool = True
    preprocess_threshold: bool = False
    preprocess_upscale: bool = True
    max_image_dimension: int = 2560
    vision_max_dimension: int = 1024
    always_on_top: bool = True
    theme: str = "dark"

    RANGES = {
        "context_length": (512, 32768),
        "max_response_tokens": (32, 4096),
        "request_timeout": (5, 3600),
        "max_screenshots": (1, 20),
        "queue_limit": (1, 50),
        "max_image_dimension": (640, 7680),
        "vision_max_dimension": (256, 4096),
        "monitor": (0, 16),
    }

    def validate(self) -> list[str]:
        errs = []
        if not is_local_url(self.ollama_url):
            errs.append("Ollama URL must point to localhost (127.0.0.1/localhost).")
        for k, (lo, hi) in self.RANGES.items():
            v = getattr(self, k)
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                errs.append(f"{k} must be an integer between {lo} and {hi}.")
        if not isinstance(self.temperature, (int, float)) or not 0 <= self.temperature <= 2:
            errs.append("temperature must be between 0 and 2.")
        if self.assistant_mode not in VALID_MODES:
            errs.append("Invalid assistant mode.")
        if self.input_mode not in VALID_INPUT_MODES:
            errs.append("Invalid input mode.")
        if self.theme not in VALID_THEMES:
            errs.append("Invalid theme.")
        if not self.model:
            errs.append("Model name is empty.")
        errs += validate_shortcuts(self.shortcuts)
        return errs

    def sanitize(self) -> "Config":
        """Reset any invalid field to its default."""
        d = Config()
        if not is_local_url(self.ollama_url):
            self.ollama_url = d.ollama_url
        for k, (lo, hi) in self.RANGES.items():
            v = getattr(self, k)
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                setattr(self, k, getattr(d, k))
        if not isinstance(self.temperature, (int, float)) or not 0 <= self.temperature <= 2:
            self.temperature = d.temperature
        if self.assistant_mode not in VALID_MODES:
            self.assistant_mode = d.assistant_mode
        if self.input_mode not in VALID_INPUT_MODES:
            self.input_mode = d.input_mode
        if self.theme not in VALID_THEMES:
            self.theme = d.theme
        if not self.model:
            self.model = d.model
        if not isinstance(self.shortcuts, dict):
            self.shortcuts = dict(DEFAULT_SHORTCUTS)
        merged = {**DEFAULT_SHORTCUTS, **{k: v for k, v in self.shortcuts.items() if k in DEFAULT_SHORTCUTS}}
        if validate_shortcuts(merged):
            merged = dict(DEFAULT_SHORTCUTS)
        self.shortcuts = {k: normalize_shortcut(v) for k, v in merged.items()}
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        names = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in (data or {}).items() if k in names})
        return cfg.sanitize()


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return Config.from_dict(data)
    except (OSError, ValueError):
        return Config()


def save_config(cfg: Config, path: Path | None = None) -> None:
    path = Path(path or config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
