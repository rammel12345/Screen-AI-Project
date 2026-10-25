"""Settings dialog."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QKeySequenceEdit, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from app.config import Config, SHORTCUT_LABELS, validate_shortcut, validate_shortcuts
from app.ui.widgets import FuncWorker, StatusPill

_QT_TO_OURS = {"return": "enter", "enter": "enter", "meta": "win", "esc": "esc", "escape": "esc",
               "del": "delete", "ins": "insert", "pgup": "pageup", "pgdown": "pagedown",
               "backspace": "backspace", "space": "space"}

PRIVACY_TEXT = """
<h3>Privacy</h3>
<ul>
<li>All OCR (Tesseract) and AI inference (Ollama) run <b>locally</b> on this computer.</li>
<li>No cloud AI, remote OCR, telemetry or remote backend is used. The Ollama endpoint is restricted to localhost.</li>
<li>Screenshots are captured <b>only</b> when you press the capture shortcut/button, and are kept in memory only.</li>
<li>Nothing is submitted to the AI until you explicitly submit.</li>
<li>Screenshots, prompts and conversations are <b>not</b> logged or saved. Only non-sensitive preferences are stored in a local config file.</li>
<li>The app does not start automatically with Windows.</li>
<li>Models are only downloaded after you confirm.</li>
</ul>
<p>Local inference does not remove all risk: the security of your computer and installed software remains your responsibility.</p>
"""


def qt_to_shortcut(seq_text: str) -> str:
    parts = []
    for p in seq_text.split("+"):
        p = p.strip()
        if not p:
            continue
        parts.append(_QT_TO_OURS.get(p.lower(), p.lower()))
    return "+".join(parts)


def shortcut_to_qt(sc: str) -> str:
    inv = {"enter": "Return", "win": "Meta", "pageup": "PgUp", "pagedown": "PgDown",
           "delete": "Del", "insert": "Ins", "esc": "Esc"}
    return "+".join(inv.get(p, p.capitalize()) for p in sc.split("+"))


class SettingsDialog(QDialog):
    clear_queue_requested = Signal()
    clear_conversation_requested = Signal()

    def __init__(self, cfg: Config, client_factory, monitors: list[str], ocr_status: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.cfg = copy.deepcopy(cfg)
        self._client_factory = client_factory
        self._workers: list[FuncWorker] = []
        self.resize(560, 560)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # --- AI tab ---
        ai = QWidget(); f = QFormLayout(ai)
        self.status = StatusPill("Checking…")
        f.addRow("Ollama status", self.status)
        self.model = QComboBox(); self.model.setEditable(True)
        self.model.setCurrentText(cfg.model)
        self.vision_model = QComboBox(); self.vision_model.setEditable(True)
        self.vision_model.setCurrentText(cfg.vision_model)
        refresh = QPushButton("Refresh models"); refresh.clicked.connect(self.refresh_models)
        row = QHBoxLayout(); row.addWidget(self.model, 1); row.addWidget(refresh)
        f.addRow("Text model", row)
        f.addRow("Vision model (optional)", self.vision_model)
        self.installed = QLabel("Installed: …"); self.installed.setObjectName("muted"); self.installed.setWordWrap(True)
        f.addRow("", self.installed)
        self.ctx = QSpinBox(); self.ctx.setRange(512, 32768); self.ctx.setSingleStep(512); self.ctx.setValue(cfg.context_length)
        self.max_tokens = QSpinBox(); self.max_tokens.setRange(32, 4096); self.max_tokens.setSingleStep(64); self.max_tokens.setValue(cfg.max_response_tokens)
        self.temp = QDoubleSpinBox(); self.temp.setRange(0, 2); self.temp.setSingleStep(0.1); self.temp.setValue(cfg.temperature)
        self.timeout = QSpinBox(); self.timeout.setRange(5, 3600); self.timeout.setSuffix(" s"); self.timeout.setValue(cfg.request_timeout)
        self.max_shots = QSpinBox(); self.max_shots.setRange(1, 20); self.max_shots.setValue(cfg.max_screenshots)
        f.addRow("Context length (tokens)", self.ctx)
        f.addRow("Max response tokens", self.max_tokens)
        f.addRow("Temperature", self.temp)
        f.addRow("Request timeout", self.timeout)
        f.addRow("Max screenshots / submission", self.max_shots)
        tabs.addTab(ai, "AI model")

        # --- Capture/OCR tab ---
        cap = QWidget(); f2 = QFormLayout(cap)
        self.monitor = QComboBox()
        for m in monitors:
            self.monitor.addItem(m)
        self.monitor.setCurrentIndex(min(cfg.monitor, max(0, self.monitor.count() - 1)))
        self.lang = QLineEdit(cfg.ocr_language); self.lang.setToolTip("Tesseract language code(s), e.g. eng or eng+fra")
        self.tess = QLineEdit(cfg.tesseract_path); self.tess.setPlaceholderText("Auto-detect (optional path to tesseract.exe)")
        self.ocr_status = QLabel(ocr_status); self.ocr_status.setObjectName("muted"); self.ocr_status.setWordWrap(True)
        self.gray = QCheckBox("Convert to grayscale (auto-inverts dark themes)"); self.gray.setChecked(cfg.preprocess_grayscale)
        self.thresh = QCheckBox("Apply binary threshold (can hurt anti-aliased text)"); self.thresh.setChecked(cfg.preprocess_threshold)
        self.upscale = QCheckBox("Upscale small images"); self.upscale.setChecked(cfg.preprocess_upscale)
        self.maxdim = QSpinBox(); self.maxdim.setRange(640, 7680); self.maxdim.setSingleStep(160); self.maxdim.setValue(cfg.max_image_dimension)
        self.vdim = QSpinBox(); self.vdim.setRange(256, 4096); self.vdim.setSingleStep(128); self.vdim.setValue(cfg.vision_max_dimension)
        self.qlimit = QSpinBox(); self.qlimit.setRange(1, 50); self.qlimit.setValue(cfg.queue_limit)
        f2.addRow("Monitor", self.monitor)
        f2.addRow("OCR language", self.lang)
        f2.addRow("Tesseract path", self.tess)
        f2.addRow("", self.ocr_status)
        f2.addRow(self.gray); f2.addRow(self.thresh); f2.addRow(self.upscale)
        f2.addRow("Max OCR image dimension (px)", self.maxdim)
        f2.addRow("Vision image dimension (px)", self.vdim)
        f2.addRow("Queue size limit", self.qlimit)
        tabs.addTab(cap, "Capture & OCR")

        # --- Shortcuts tab ---
        sc = QWidget(); v = QVBoxLayout(sc); f3 = QFormLayout(); v.addLayout(f3)
        self.sc_edits: dict[str, QKeySequenceEdit] = {}
        for action, label in SHORTCUT_LABELS.items():
            e = QKeySequenceEdit()
            try:
                e.setMaximumSequenceLength(1)
            except AttributeError:
                pass
            from PySide6.QtGui import QKeySequence
            e.setKeySequence(QKeySequence(shortcut_to_qt(cfg.shortcuts[action])))
            self.sc_edits[action] = e
            f3.addRow(label, e)
        hint = QLabel("Click a field and press the new combination. Needs at least one modifier. "
                      "These are global: they work while other apps are focused. If another app "
                      "already uses a combination, choose a different one.")
        hint.setWordWrap(True); hint.setObjectName("muted")
        v.addWidget(hint)
        reset = QPushButton("Reset to defaults"); reset.clicked.connect(self._reset_shortcuts)
        v.addWidget(reset); v.addStretch()
        tabs.addTab(sc, "Shortcuts")

        # --- General tab ---
        g = QWidget(); f4 = QFormLayout(g)
        self.theme = QComboBox(); self.theme.addItems(["dark", "light"]); self.theme.setCurrentText(cfg.theme)
        self.aot = QCheckBox("Keep window always on top"); self.aot.setChecked(cfg.always_on_top)
        f4.addRow("Theme", self.theme); f4.addRow(self.aot)
        cq = QPushButton("Clear screenshot queue"); cq.setObjectName("danger")
        cq.clicked.connect(self.clear_queue_requested)
        cc = QPushButton("Clear conversation"); cc.setObjectName("danger")
        cc.clicked.connect(self.clear_conversation_requested)
        f4.addRow(cq); f4.addRow(cc)
        tabs.addTab(g, "General")

        # --- Privacy tab ---
        pv = QTextBrowser(); pv.setHtml(PRIVACY_TEXT)
        tabs.addTab(pv, "Privacy")

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_save = bb.button(QDialogButtonBox.Save)
        if btn_save:
            btn_save.setObjectName("primary")
        bb.accepted.connect(self._accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.refresh_models()

    def _reset_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence
        from app.config import DEFAULT_SHORTCUTS
        for a, e in self.sc_edits.items():
            e.setKeySequence(QKeySequence(shortcut_to_qt(DEFAULT_SHORTCUTS[a])))

    def refresh_models(self) -> None:
        self.status.set("Checking…", "idle")
        client = self._client_factory()

        def work():
            client.version()
            return client.list_models()
        w = FuncWorker(work, self)
        w.result.connect(self._on_models)
        w.failed.connect(lambda e: (self.status.set("Not connected", "bad", str(e)),
                                    self.installed.setText(str(e))))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _on_models(self, models) -> None:
        names = [m.name for m in models]
        self.status.set(f"Connected · {len(names)} local models", "ok")
        for combo in (self.model, self.vision_model):
            cur = combo.currentText()
            combo.clear(); combo.addItems(names); combo.setCurrentText(cur)
        self.installed.setText("Installed (local only): " + (", ".join(names) or "none"))

    def _collect(self) -> Config:
        c = self.cfg
        c.model = self.model.currentText().strip()
        c.vision_model = self.vision_model.currentText().strip()
        c.context_length = self.ctx.value()
        c.max_response_tokens = self.max_tokens.value()
        c.temperature = round(self.temp.value(), 2)
        c.request_timeout = self.timeout.value()
        c.max_screenshots = self.max_shots.value()
        c.monitor = self.monitor.currentIndex()
        c.ocr_language = self.lang.text().strip() or "eng"
        c.tesseract_path = self.tess.text().strip()
        c.preprocess_grayscale = self.gray.isChecked()
        c.preprocess_threshold = self.thresh.isChecked()
        c.preprocess_upscale = self.upscale.isChecked()
        c.max_image_dimension = self.maxdim.value()
        c.vision_max_dimension = self.vdim.value()
        c.queue_limit = self.qlimit.value()
        c.theme = self.theme.currentText()
        c.always_on_top = self.aot.isChecked()
        c.shortcuts = {a: qt_to_shortcut(e.keySequence().toString()) for a, e in self.sc_edits.items()}
        return c

    def _accept(self) -> None:
        c = self._collect()
        errs = c.validate()
        if errs:
            QMessageBox.warning(self, "Invalid settings", "\n".join(errs))
            return
        self.accept()

    def result_config(self) -> Config:
        return self.cfg
