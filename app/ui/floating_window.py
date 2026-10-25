"""The floating assistant window (view only; logic lives in main_window.AppController).

Layout: toolbar | [sidebar: queue + capture] [main: OCR text, conversation, composer] | status bar
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QProgressBar, QPushButton, QSplitter, QStackedWidget, QTextBrowser,
                               QTextEdit, QVBoxLayout, QWidget)

from app.ai.prompts import MODE_LABELS
from app.config import SHORTCUT_LABELS
from app.ui.screenshot_queue import ScreenshotQueuePanel
from app.ui.widgets import ActionButton, G, StatusPill, chat_css, icon_button

INPUT_MODE_LABELS = {"text": "Text (OCR)", "vision": "Vision", "hybrid": "Hybrid"}

SUGGESTIONS = {
    "explain": ["Explain what is on my screen", "Summarize this", "What does this error mean?"],
    "coding": ["Explain this code line by line", "Why does this error occur?", "Suggest a fix"],
    "general": ["Summarize the key points", "What is unclear or missing?", "Help me with this"],
}

DEFAULT_STATUS = "Capture is user-initiated only — nothing is captured automatically."


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


class FloatingWindow(QWidget):
    capture_clicked = Signal()
    submit_clicked = Signal()
    cancel_clicked = Signal()
    retry_clicked = Signal()
    followup_submitted = Signal(str)
    retry_ocr_clicked = Signal()
    text_edited = Signal(int, str)
    clear_text_clicked = Signal()
    mode_changed = Signal(str)
    input_mode_changed = Signal(str)
    pause_toggled = Signal(bool)
    aot_toggled = Signal(bool)
    settings_clicked = Signal()
    clear_conversation_clicked = Signal()
    exit_clicked = Signal()
    hidden_by_user = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Local Screen AI")
        self.resize(1000, 690)
        self.setMinimumSize(780, 520)
        self._current_sid = -1
        self._loading_text = False
        self._has_conv = False
        self._busy = False
        self._shortcuts: dict[str, str] = {}
        self._default_status = (DEFAULT_STATUS, False)
        self._response_raw = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())
        self.loading = QProgressBar(); self.loading.setRange(0, 0); self.loading.setTextVisible(False)
        self.loading.setFixedHeight(2); self.loading.setVisible(False)
        root.addWidget(self.loading)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)
        split.addWidget(self._build_sidebar())
        split.addWidget(self._build_main())
        split.setSizes([310, 690])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        root.addWidget(self._build_statusbar())

        self.apply_theme("dark")
        self.set_conversation_active(False)
        self._refresh_suggestions()
        self.load_text(-1, "")

    # ------------------------------------------------------------ builders
    def _build_toolbar(self) -> QFrame:
        bar = QFrame(); bar.setObjectName("toolbar"); bar.setFixedHeight(48)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(8)
        badge = QLabel("AI"); badge.setFixedSize(24, 24); badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("background:#7c6bff; color:white; border-radius:6px; font-weight:700; font-size:11px;")
        brand = QLabel("Local Screen AI"); brand.setObjectName("brand")
        lay.addWidget(badge); lay.addWidget(brand); lay.addSpacing(14)

        self.mode = QComboBox(); self.mode.setObjectName("toolCombo")
        for k, v in MODE_LABELS.items():
            self.mode.addItem(v, k)
        self.mode.setToolTip("Assistant mode")
        self.mode.setFixedWidth(150)
        self.mode.currentIndexChanged.connect(self._on_mode)
        self.input_mode = QComboBox(); self.input_mode.setObjectName("toolCombo")
        for k, v in INPUT_MODE_LABELS.items():
            self.input_mode.addItem(v, k)
        self.input_mode.setFixedWidth(116)
        self.input_mode.setToolTip("Text = OCR text only (fast). Vision/Hybrid send screenshots to a local "
                                   "vision model (slow on this hardware).")
        self.input_mode.currentIndexChanged.connect(lambda _: self.input_mode_changed.emit(self.input_mode.currentData()))
        lay.addWidget(self.mode); lay.addWidget(self.input_mode)
        lay.addStretch(1)

        self.status = StatusPill("Checking Ollama…")
        lay.addWidget(self.status)
        lay.addSpacing(8)

        self.btn_aot = icon_button(G["pin"], "Keep on top", checkable=True)
        self.btn_aot.toggled.connect(self.aot_toggled)
        self.btn_pause = icon_button(G["pause"], "Pause capture", checkable=True, tone="warn")
        self.btn_pause.toggled.connect(self._on_pause)
        self.btn_settings = icon_button(G["settings"], "Settings")
        self.btn_settings.clicked.connect(self.settings_clicked)
        self.btn_hide = icon_button(G["hide"], "Hide to tray")
        self.btn_hide.clicked.connect(self.hide_window)
        self.btn_exit = icon_button(G["power"], "Exit Local Screen AI", danger=True)
        self.btn_exit.clicked.connect(self.exit_clicked)
        for b in (self.btn_aot, self.btn_pause, self.btn_settings, self.btn_hide, self.btn_exit):
            lay.addWidget(b)
        return bar

    def _build_sidebar(self) -> QFrame:
        side = QFrame(); side.setObjectName("sidebar")
        side.setMinimumWidth(250); side.setMaximumWidth(380)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.queue = ScreenshotQueuePanel()
        lay.addWidget(self.queue, 1)
        foot = QVBoxLayout()
        foot.setContentsMargins(12, 8, 12, 12)
        foot.setSpacing(8)
        self.btn_capture = ActionButton(G["capture"], "Capture", "primary")
        self.btn_capture.setToolTip("Capture the screen and add it to the queue")
        self.btn_capture.clicked.connect(self.capture_clicked)
        self.btn_submit_queue = ActionButton(G["send"], "Submit queue", "secondary")
        self.btn_submit_queue.setToolTip("Start a new conversation from the selected screenshots")
        self.btn_submit_queue.clicked.connect(self.submit_clicked)
        self.btn_submit_queue.setMinimumHeight(30)
        foot.addWidget(self.btn_capture)
        foot.addWidget(self.btn_submit_queue)
        lay.addLayout(foot)
        return side

    def _build_main(self) -> QFrame:
        main = QFrame(); main.setObjectName("main")
        lay = QVBoxLayout(main)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        # OCR card (collapsible)
        self.ocr_card = QFrame(); self.ocr_card.setObjectName("ocrCard")
        ol = QVBoxLayout(self.ocr_card)
        ol.setContentsMargins(10, 6, 8, 8)
        ol.setSpacing(2)
        oh = QHBoxLayout(); oh.setSpacing(2)
        self.btn_ocr_toggle = icon_button(G["up"], "Collapse / expand", small=True)
        self.btn_ocr_toggle.clicked.connect(self._toggle_ocr)
        self.ocr_title = QLabel("Extracted text"); self.ocr_title.setObjectName("section")
        oh.addWidget(self.btn_ocr_toggle); oh.addWidget(self.ocr_title); oh.addStretch()
        self.btn_copy_text = icon_button(G["copy"], "Copy text", small=True)
        self.btn_copy_text.clicked.connect(self._copy_text)
        self.btn_retry_ocr = icon_button(G["retry"], "Retry OCR", small=True)
        self.btn_retry_ocr.clicked.connect(self.retry_ocr_clicked)
        self.btn_clear_text = icon_button(G["erase"], "Clear text", small=True, danger=True)
        self.btn_clear_text.clicked.connect(self.clear_text_clicked)
        for b in (self.btn_copy_text, self.btn_retry_ocr, self.btn_clear_text):
            oh.addWidget(b)
        ol.addLayout(oh)
        self.text_edit = QTextEdit(); self.text_edit.setObjectName("ocr")
        self.text_edit.setAcceptRichText(False)
        self.text_edit.setPlaceholderText("Select a screenshot to view or edit its OCR text.")
        self.text_edit.setMinimumHeight(70)
        self.text_edit.setMaximumHeight(170)
        self.text_edit.textChanged.connect(self._on_text_changed)
        ol.addWidget(self.text_edit)
        lay.addWidget(self.ocr_card)

        # Conversation
        ch = QHBoxLayout(); ch.setContentsMargins(2, 0, 0, 0); ch.setSpacing(2)
        cap = QLabel("CONVERSATION"); cap.setObjectName("caption")
        ch.addWidget(cap); ch.addStretch()
        self.btn_retry = icon_button(G["retry"], "Regenerate last answer")
        self.btn_retry.clicked.connect(self.retry_clicked)
        self.btn_copy = icon_button(G["copy"], "Copy last answer")
        self.btn_copy.clicked.connect(self._copy_response)
        self.btn_clear_conv = icon_button(G["delete"], "Clear conversation", danger=True)
        self.btn_clear_conv.clicked.connect(self.clear_conversation_clicked)
        for b in (self.btn_retry, self.btn_copy, self.btn_clear_conv):
            ch.addWidget(b)
        lay.addLayout(ch)

        self.stack = QStackedWidget()
        self.empty_chat = QWidget()
        el = QVBoxLayout(self.empty_chat)
        el.setAlignment(Qt.AlignCenter)
        ic = QLabel(G["chat"]); ic.setObjectName("glyph")
        ic.setStyleSheet("font-size:30px; color:#71717a;"); ic.setAlignment(Qt.AlignCenter)
        t = QLabel("Ask about your screen"); t.setObjectName("emptyTitle"); t.setAlignment(Qt.AlignCenter)
        s = QLabel("Capture, check the extracted text, then submit. Answers appear here and are never executed.")
        s.setObjectName("muted"); s.setAlignment(Qt.AlignCenter); s.setWordWrap(True)
        el.addWidget(ic); el.addWidget(t); el.addWidget(s); el.addSpacing(8)
        self.chip_row = QHBoxLayout(); self.chip_row.setAlignment(Qt.AlignCenter)
        el.addLayout(self.chip_row)
        self.stack.addWidget(self.empty_chat)
        self.response = QTextBrowser(); self.response.setObjectName("chat")
        self.response.setOpenExternalLinks(False)
        self.stack.addWidget(self.response)
        lay.addWidget(self.stack, 1)

        # Inline banner (errors / setup hints)
        self.banner = QFrame(); self.banner.setObjectName("banner"); self.banner.setVisible(False)
        bl = QHBoxLayout(self.banner); bl.setContentsMargins(10, 6, 4, 6)
        self.error = QLabel(""); self.error.setObjectName("bannerText"); self.error.setWordWrap(True)
        self.error.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bx = icon_button(G["close"], "Dismiss", small=True)
        bx.clicked.connect(lambda: self.show_error(""))
        bl.addWidget(self.error, 1); bl.addWidget(bx, 0, Qt.AlignTop)
        lay.addWidget(self.banner)

        # Composer
        self.composer = QFrame(); self.composer.setObjectName("composer")
        cl = QHBoxLayout(self.composer); cl.setContentsMargins(10, 6, 6, 6); cl.setSpacing(8)
        self.prompt = QLineEdit()
        self.prompt.returnPressed.connect(self._on_send)
        self.prompt.installEventFilter(self)
        self.btn_submit = ActionButton(G["send"], "Submit queue", "primary")
        self.btn_submit.clicked.connect(self._on_send)
        self.btn_submit.setFixedWidth(150)
        self.btn_stop = ActionButton(G["stop"], "Stop", "stop")
        self.btn_stop.clicked.connect(self.cancel_clicked)
        self.btn_stop.setFixedWidth(110); self.btn_stop.setVisible(False)
        cl.addWidget(self.prompt, 1); cl.addWidget(self.btn_submit); cl.addWidget(self.btn_stop)
        lay.addWidget(self.composer)
        return main

    def _build_statusbar(self) -> QFrame:
        bar = QFrame(); bar.setObjectName("statusbar"); bar.setFixedHeight(28)
        lay = QHBoxLayout(bar); lay.setContentsMargins(14, 0, 8, 0); lay.setSpacing(10)
        self.status_msg = QLabel(DEFAULT_STATUS); self.status_msg.setObjectName("muted")
        self.capture_status = self.status_msg  # backwards-compatible alias
        lay.addWidget(self.status_msg, 1)
        self.model_label = QLabel(""); self.model_label.setObjectName("muted")
        lay.addWidget(self.model_label)
        self.btn_shortcuts = QPushButton("⌨  Shortcuts"); self.btn_shortcuts.setObjectName("link")
        self.btn_shortcuts.setCursor(Qt.PointingHandCursor)
        self.btn_shortcuts.clicked.connect(self._show_shortcuts)
        lay.addWidget(self.btn_shortcuts)
        self._status_timer = QTimer(self); self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self._show_status(*self._default_status))
        return bar

    # ------------------------------------------------------------ theme / state
    def apply_theme(self, name: str) -> None:
        self.response.document().setDefaultStyleSheet(chat_css(name))
        if self._response_raw:
            self.response.setMarkdown(self._response_raw)

    def _show_status(self, text: str, warn: bool) -> None:
        self.status_msg.setText(text)
        self.status_msg.setStyleSheet("color:#fbbf24;" if warn else "")

    def set_capture_status(self, text: str, warn: bool = False, persistent: bool = False) -> None:
        """Transient message in the status bar; persistent=True sets the resting message."""
        if persistent:
            self._default_status = (text, warn)
            self._status_timer.stop()
        else:
            self._status_timer.start(6000)
        self._show_status(text, warn)

    def set_shortcuts(self, shortcuts: dict[str, str]) -> None:
        self._shortcuts = dict(shortcuts)
        cap = self._shortcuts.get("capture", "")
        sub = self._shortcuts.get("submit", "")
        self.btn_capture.set_chip(cap)
        self.btn_submit_queue.set_chip(sub)
        self.btn_capture.setToolTip(f"Capture the screen and add it to the queue ({cap})")

    def set_shortcut_hint(self, text: str) -> None:  # kept for compatibility
        self.btn_shortcuts.setToolTip(text)

    def _show_shortcuts(self) -> None:
        m = QMenu(self)
        for action, label in SHORTCUT_LABELS.items():
            a = m.addAction(f"{label}    {self._shortcuts.get(action, '')}")
            a.setEnabled(False)
        m.addSeparator()
        m.addAction("Change in Settings…", self.settings_clicked.emit)
        h = m.sizeHint()
        m.exec(self.btn_shortcuts.mapToGlobal(self.btn_shortcuts.rect().topRight()) - QPoint(h.width(), h.height()))

    def _on_mode(self) -> None:
        self._refresh_suggestions()
        self.mode_changed.emit(self.mode.currentData())

    def _refresh_suggestions(self) -> None:
        while self.chip_row.count():
            it = self.chip_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for text in SUGGESTIONS.get(self.mode.currentData() or "explain", []):
            b = QPushButton(text); b.setObjectName("chipBtn"); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=text: (self.prompt.setText(t), self.prompt.setFocus()))
            self.chip_row.addWidget(b)

    def _on_pause(self, paused: bool) -> None:
        self.btn_pause.setText(G["play"] if paused else G["pause"])
        self.btn_pause.setToolTip("Resume capture" if paused else "Pause capture")
        self.pause_toggled.emit(paused)

    def set_conversation_active(self, active: bool) -> None:
        self._has_conv = active
        self.btn_submit.setText("Send" if active else "Submit queue")
        self.btn_submit.set_chip("" if active else self._shortcuts.get("submit", ""))
        self.btn_submit_queue.setVisible(active)
        self.prompt.setPlaceholderText(
            "Ask a follow-up…" if active else "Add an instruction (optional), then submit the queue…")

    def update_composer(self, busy: bool, has_selected: bool) -> None:
        self.btn_submit.setEnabled(not busy and (self._has_conv or has_selected))
        self.btn_submit_queue.setEnabled(not busy and has_selected)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.loading.setVisible(busy)
        self.btn_stop.setVisible(busy)
        self.btn_submit.setVisible(not busy)
        self.btn_retry.setEnabled(not busy)

    def show_error(self, msg: str) -> None:
        self.error.setText(msg)
        self.banner.setVisible(bool(msg))

    def set_response(self, markdown: str) -> None:
        self._response_raw = markdown
        self.stack.setCurrentIndex(1 if markdown.strip() else 0)
        sb = self.response.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        self.response.setMarkdown(markdown)
        if at_bottom:
            sb.setValue(sb.maximum())

    def response_text(self) -> str:
        return self._response_raw

    def _copy_response(self) -> None:
        QGuiApplication.clipboard().setText(self._response_raw)

    def _copy_text(self) -> None:
        QGuiApplication.clipboard().setText(self.text_edit.toPlainText())

    def _on_send(self) -> None:
        if self._busy:
            return
        if self._has_conv:
            q = self.prompt.text().strip()
            if q:
                self.prompt.clear()
                self.followup_submitted.emit(q)
        else:
            self.submit_clicked.emit()

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.prompt and ev.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.composer.setProperty("focused", ev.type() == QEvent.FocusIn)
            _repolish(self.composer)
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------ OCR text panel
    def _toggle_ocr(self) -> None:
        vis = not self.text_edit.isVisible()
        self.text_edit.setVisible(vis)
        self.btn_ocr_toggle.setText(G["up"] if vis else G["down"])

    def load_text(self, sid: int, text: str, title: str = "") -> None:
        self._current_sid = sid
        self._loading_text = True
        self.text_edit.setPlainText(text)
        self._loading_text = False
        self.text_edit.setEnabled(sid != -1)
        for b in (self.btn_retry_ocr, self.btn_clear_text, self.btn_copy_text):
            b.setEnabled(sid != -1)
        self.ocr_title.setText(title or "Extracted text")

    def _on_text_changed(self) -> None:
        if not self._loading_text and self._current_sid != -1:
            self.text_edited.emit(self._current_sid, self.text_edit.toPlainText())

    # ------------------------------------------------------------ window behaviour
    def set_always_on_top(self, on: bool) -> None:
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.btn_aot.blockSignals(True); self.btn_aot.setChecked(on); self.btn_aot.blockSignals(False)
        if was_visible:
            self.show()

    def hide_window(self) -> None:
        self.hide()
        self.hidden_by_user.emit()

    def closeEvent(self, e: QCloseEvent) -> None:
        # The X button hides to the tray; use "Exit" to quit.
        e.ignore()
        self.hide_window()
