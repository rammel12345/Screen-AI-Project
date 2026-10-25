"""Shared UI helpers: design tokens + QSS, icon helpers, workers, small widgets."""
from __future__ import annotations

from typing import Any, Callable

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThread, Signal, Qt
from PySide6.QtGui import QFontDatabase, QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

# ------------------------------------------------------------------ icons
# Glyphs from Segoe Fluent Icons (Windows 11) / Segoe MDL2 Assets (Windows 10).
G = {
    "capture": "\uE722", "pin": "\uE718", "pause": "\uE769", "play": "\uE768",
    "settings": "\uE713", "hide": "\uE921", "power": "\uE7E8", "copy": "\uE8C8",
    "retry": "\uE72C", "delete": "\uE74D", "send": "\uE724", "more": "\uE712",
    "down": "\uE70D", "up": "\uE70E", "eye": "\uE7B3", "close": "\uE711",
    "stop": "\uE71A", "keyboard": "\uE765", "picture": "\uE91B", "chat": "\uE8BD",
    "check": "\uE73E", "erase": "\uE894",
}


def icon_family() -> str:
    fams = set(QFontDatabase.families())
    for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if f in fams:
            return f
    return "Segoe UI Symbol"


# ------------------------------------------------------------------ design tokens
DARK = {
    "bg": "#09090b", "sidebar": "#0f0f12", "s1": "#18181b", "s2": "#1f1f23", "s3": "#27272a",
    "border": "#27272a", "text": "#fafafa", "muted": "#a1a1aa", "faint": "#71717a",
    "accent": "#7c6bff", "accent_h": "#9080ff", "accent_p": "#6a59ec", "accent_text": "#a99bff",
    "code": "#131316", "focus": "rgba(124,107,255,60%)", "tint": "rgba(124,107,255,18%)",
    "sel": "#4c3fd1", "scroll": "#3f3f46", "scroll_h": "#52525b", "disabled": "#52525b",
    "danger_tint": "rgba(248,113,113,15%)", "press": "#303036", "on_accent": "#ffffff",
}
LIGHT = {
    "bg": "#fafafa", "sidebar": "#f4f4f5", "s1": "#ffffff", "s2": "#f4f4f5", "s3": "#e4e4e7",
    "border": "#e4e4e7", "text": "#18181b", "muted": "#52525b", "faint": "#71717a",
    "accent": "#6d5efc", "accent_h": "#7c6bff", "accent_p": "#5a4ae0", "accent_text": "#5a4ae0",
    "code": "#f4f4f5", "focus": "rgba(109,94,252,60%)", "tint": "rgba(109,94,252,14%)",
    "sel": "#c7c1ff", "scroll": "#d4d4d8", "scroll_h": "#a1a1aa", "disabled": "#a1a1aa",
    "danger_tint": "rgba(220,38,38,12%)", "press": "#d4d4d8", "on_accent": "#ffffff",
}

QSS_TEMPLATE = """
* { font-family: 'Segoe UI Variable Text','Segoe UI','Inter',sans-serif; font-size: 13px; }
QWidget { background: transparent; color: @text; }
QWidget#root, QDialog, QMessageBox { background: @bg; }
QLabel { background: transparent; }
QLabel#muted { color: @muted; font-size: 12px; }
QLabel#caption { color: @faint; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
QLabel#section { font-weight: 600; }
QLabel#title { font-size: 15px; font-weight: 600; }
QLabel#brand { font-size: 14px; font-weight: 600; }
QLabel#count { background: @s3; color: @muted; border-radius: 8px; padding: 0 7px; font-size: 11px; font-weight: 600; }
QLabel#emptyIcon { color: @faint; }
QLabel#emptyTitle { font-size: 14px; font-weight: 600; }
QLabel#glyph, QLabel#chipGlyph { font-family: '@icons'; font-size: 14px; }

QFrame#toolbar { background: @sidebar; border: none; border-bottom: 1px solid @border; }
QFrame#sidebar { background: @sidebar; border: none; border-right: 1px solid @border; }
QFrame#statusbar { background: @sidebar; border: none; border-top: 1px solid @border; }
QFrame#main { background: @bg; border: none; }
QFrame#card { background: @s1; border: none; border-radius: 8px; }
QFrame#ocrCard { background: @s1; border: none; border-radius: 8px; }
QFrame#composer { background: @s1; border: 1px solid transparent; border-radius: 8px; }
QFrame#composer[focused="true"] { border: 1px solid @focus; }
QFrame#banner { background: @danger_tint; border: none; border-radius: 6px; }
QLabel#bannerText { color: #f87171; }

/* Tier 1: primary */
QPushButton#primary { background: @accent; color: @on_accent; font-weight: 600; border: none;
  border-radius: 6px; padding: 0 14px; min-height: 34px; }
QPushButton#primary:hover { background: @accent_h; }
QPushButton#primary:pressed { background: @accent_p; }
QPushButton#primary:disabled { background: @s3; }
QPushButton#primary QLabel { color: @on_accent; font-weight: 600; background: transparent; }
QPushButton#primary QLabel#chip { background: rgba(255,255,255,18%); border-radius: 4px; padding: 1px 6px;
  font-size: 11px; font-weight: 500; color: rgba(255,255,255,85%); }
QPushButton#primary:disabled QLabel { color: @faint; }
QPushButton#primary:disabled QLabel#chip { background: @s2; }
QPushButton#stop { background: @s3; color: @text; font-weight: 600; border: none; border-radius: 6px;
  padding: 0 14px; min-height: 34px; }
QPushButton#stop:hover { background: @press; }

/* Tier 2: secondary */
QPushButton { background: @s2; border: none; border-radius: 6px; padding: 0 12px; min-height: 30px; }
QPushButton:hover { background: @s3; }
QPushButton:pressed { background: @press; }
QPushButton:disabled { color: @disabled; background: transparent; }
QPushButton#secondary QLabel { background: transparent; }
QPushButton#secondary:disabled QLabel { color: @disabled; }
QPushButton#secondary QLabel#chip { background: @s3; border-radius: 4px; padding: 1px 6px; font-size: 11px; color: @muted; }

/* Tier 3: ghost icon */
QPushButton#icon { font-family: '@icons'; font-size: 14px; background: transparent; color: @muted;
  min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; border-radius: 6px; }
QPushButton#icon:hover { background: @s3; color: @text; }
QPushButton#icon:pressed { background: @press; }
QPushButton#icon:checked { background: @tint; color: @accent_text; }
QPushButton#icon[tone="warn"]:checked { background: rgba(251,191,36,18%); color: #fbbf24; }
QPushButton#icon[danger="true"]:hover { background: @danger_tint; color: #f87171; }
QPushButton#icon:disabled { color: @disabled; background: transparent; }
QPushButton#iconSm { font-family: '@icons'; font-size: 11px; background: transparent; color: @faint;
  min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; padding: 0; border-radius: 5px; }
QPushButton#iconSm:hover { background: @s3; color: @text; }
QPushButton#iconSm[danger="true"]:hover { background: @danger_tint; color: #f87171; }
QPushButton#link { background: transparent; color: @muted; padding: 0 8px; min-height: 24px; font-size: 12px; }
QPushButton#link:hover { color: @text; background: @s2; }
QPushButton#chipBtn { background: @s1; color: @muted; border-radius: 12px; padding: 0 12px; min-height: 26px; font-size: 12px; }
QPushButton#chipBtn:hover { background: @s3; color: @text; }

QLineEdit, QTextEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {
  background: @s1; border: 1px solid transparent; border-radius: 6px; padding: 5px 8px;
  selection-background-color: @sel; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QKeySequenceEdit:focus { border-color: @focus; }
QDialog QLineEdit, QDialog QSpinBox, QDialog QDoubleSpinBox, QDialog QComboBox { border: 1px solid @border; }
QFrame#composer QLineEdit { background: transparent; border: none; padding: 6px 4px; }
QTextEdit#ocr { background: transparent; border: none; font-family: 'Cascadia Code','Consolas',monospace; font-size: 12px; padding: 4px 8px; }
QTextBrowser#chat { background: transparent; border: none; padding: 0 4px; }
QComboBox { padding: 3px 8px; min-height: 22px; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView { background: @s1; border: 1px solid @border; border-radius: 6px; padding: 4px;
  selection-background-color: @s3; outline: 0; }
QComboBox#toolCombo { background: @s2; }

QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { border-radius: 8px; margin: 2px 6px; }
QListWidget::item:hover { background: @s1; }
QListWidget::item:selected { background: @s2; border-left: 2px solid @accent; }

QMenu { background: @s1; border: 1px solid @border; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 4px; color: @text; }
QMenu::item:selected { background: @s3; }
QMenu::item:disabled { color: @muted; }
QMenu::separator { height: 1px; background: @border; margin: 4px 6px; }

QTabWidget::pane { border: 1px solid @border; border-radius: 8px; top: -1px; }
QTabBar::tab { background: transparent; color: @muted; padding: 7px 14px; border-radius: 6px; margin: 2px; }
QTabBar::tab:selected { background: @s2; color: @text; }
QTabBar::tab:hover { color: @text; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid @scroll; background: @s1; }
QCheckBox::indicator:hover { border-color: @accent; }
QCheckBox::indicator:checked { background: @accent; border-color: @accent; }
QProgressBar { background: transparent; border: none; max-height: 2px; min-height: 2px; }
QProgressBar::chunk { background: @accent; border-radius: 1px; }
QSplitter::handle { background: @border; }
QSplitter::handle:horizontal { width: 1px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: @scroll_h; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: @scroll; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QToolTip { background: @s3; color: @text; border: 1px solid @scroll; padding: 4px 8px; border-radius: 6px; }
"""

CHAT_CSS = ("pre {{ background:{code}; }} code {{ background:{code}; font-family:'Cascadia Code',Consolas,monospace; }} "
            "a {{ color:{accent_text}; }} h1,h2,h3 {{ font-weight:600; }}")


def tokens(name: str) -> dict:
    return LIGHT if name == "light" else DARK


def theme_qss(name: str) -> str:
    t = dict(tokens(name))
    t["icons"] = icon_family()
    out = QSS_TEMPLATE
    for k in sorted(t, key=len, reverse=True):
        out = out.replace("@" + k, t[k])
    return out


def chat_css(name: str) -> str:
    return CHAT_CSS.format(**tokens(name))


# ------------------------------------------------------------------ widgets
def pil_to_pixmap(img: Image.Image, max_size: tuple[int, int] | None = None) -> QPixmap:
    rgb = img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888).copy()
    pm = QPixmap.fromImage(qimg)
    if max_size:
        pm = pm.scaled(max_size[0], max_size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pm


def icon_button(glyph: str, tooltip: str, checkable: bool = False, danger: bool = False,
                tone: str = "", small: bool = False) -> QPushButton:
    b = QPushButton(glyph)
    b.setObjectName("iconSm" if small else "icon")
    b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.TabFocus)
    if danger:
        b.setProperty("danger", True)
    if tone:
        b.setProperty("tone", tone)
    return b


class ActionButton(QPushButton):
    """Button with leading glyph, label and optional hotkey chip."""

    def __init__(self, glyph: str, text: str, object_name: str = "primary", chip: str = ""):
        super().__init__()
        self.setObjectName(object_name)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 10, 0)
        lay.setSpacing(8)
        self._g = QLabel(glyph); self._g.setObjectName("glyph")
        self._t = QLabel(text)
        self._c = QLabel(chip); self._c.setObjectName("chip")
        for w in (self._g, self._t, self._c):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._g)
        lay.addWidget(self._t)
        lay.addStretch(1)
        lay.addWidget(self._c)
        self._c.setVisible(bool(chip))
        self.setMinimumHeight(34)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self._t.setText(text)

    def text(self) -> str:
        return self._t.text()

    def set_glyph(self, glyph: str) -> None:
        self._g.setText(glyph)

    def set_chip(self, chip: str) -> None:
        self._c.setText(chip)
        self._c.setVisible(bool(chip))


class StatusPill(QLabel):
    COLORS = {"ok": "#34d399", "warn": "#fbbf24", "bad": "#f87171", "idle": "#71717a"}

    def __init__(self, text: str = "", level: str = "idle"):
        super().__init__()
        self.set(text, level)

    def set(self, text: str, level: str = "idle", tooltip: str = "") -> None:
        c = self.COLORS.get(level, self.COLORS["idle"])
        self.setText(f"<span style='color:{c}'>●</span>&nbsp;&nbsp;{text}")
        self.setToolTip(tooltip or text)
        self.setStyleSheet("font-size:12px; font-weight:500;")


class FuncWorker(QThread):
    """Run a callable off the UI thread. Emits result or error message."""
    result = Signal(object)
    failed = Signal(object)

    def __init__(self, fn: Callable[[], Any], parent: QObject | None = None):
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            self.result.emit(self.fn())
        except Exception as e:  # surfaced to UI, never crashes the thread
            self.failed.emit(e)


class _OcrSignals(QObject):
    done = Signal(int, object)  # screenshot id, OcrResult


class OcrTask(QRunnable):
    def __init__(self, sid: int, image: Image.Image, engine):
        super().__init__()
        self.sid, self.image, self.engine = sid, image, engine
        self.signals = _OcrSignals()

    def run(self) -> None:
        res = self.engine.extract(self.image)
        try:
            self.signals.done.emit(self.sid, res)
        except RuntimeError:
            pass  # receiver destroyed during shutdown


class ChatWorker(QThread):
    token = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(object)
    cancelled = Signal(str)

    def __init__(self, client, model, messages, ctx, max_tokens, temperature, parent=None):
        super().__init__(parent)
        self.client, self.model, self.messages = client, model, messages
        self.ctx, self.max_tokens, self.temperature = ctx, max_tokens, temperature

    def cancel(self) -> None:
        self.client.cancel()

    def run(self) -> None:
        from app.ai.ollama_client import OllamaCancelled
        parts: list[str] = []
        try:
            for chunk in self.client.chat_stream(self.model, self.messages, self.ctx,
                                                 self.max_tokens, self.temperature):
                parts.append(chunk)
                self.token.emit(chunk)
            self.finished_ok.emit("".join(parts))
        except OllamaCancelled:
            self.cancelled.emit("".join(parts))
        except Exception as e:
            self.failed.emit(e)
