"""Application controller: wires UI, session, OCR, Ollama and global shortcuts."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QThreadPool, QTimer, Signal, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QFont
from PySide6.QtWidgets import (QApplication, QMessageBox, QMenu, QSystemTrayIcon, QProgressDialog)

from app.ai.ollama_client import (ModelMissing, ModelNotVision, OllamaClient, OllamaError,
                                  OllamaUnavailable)
from app.ai.prompts import MODE_LABELS, trim_history
from app.capture.image_processor import to_base64_png
from app.capture.screen_capture import CaptureError, capture_screen, list_monitors
from app.config import Config, load_config, save_config
from app.models import OcrStatus
from app.ocr.ocr_engine import OcrEngine
from app.services.session_manager import QueueFull, SessionManager
from app.shortcuts.shortcut_manager import ShortcutManager, pretty
from app.ui.floating_window import FloatingWindow
from app.ui.screenshot_queue import PreviewDialog
from app.ui.settings_dialog import SettingsDialog
from app.ui.widgets import ChatWorker, FuncWorker, OcrTask, theme_qss


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#6d5efc")); p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("white")); f = QFont("Segoe UI", 26, QFont.Bold); p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "AI")
    p.end()
    return QIcon(pm)


class PullWorker(QThread):
    progress = Signal(str, float)
    done = Signal()
    failed = Signal(object)

    def __init__(self, client: OllamaClient, model: str):
        super().__init__()
        self.client, self.model = client, model

    def run(self) -> None:
        try:
            for status, frac in self.client.pull_stream(self.model):
                self.progress.emit(status, -1.0 if frac is None else frac)
            self.done.emit()
        except Exception as e:
            self.failed.emit(e)


class HotkeyBridge(QObject):
    triggered = Signal(str)


class AppController(QObject):
    def __init__(self, app: QApplication, cfg: Config | None = None):
        super().__init__()
        self.app = app
        self.cfg = cfg or load_config()
        self.session = SessionManager(self.cfg.queue_limit, self.cfg.max_screenshots)
        self.client = OllamaClient(self.cfg.ollama_url, self.cfg.request_timeout)
        self.ocr = self._make_ocr()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)  # one OCR job at a time: keeps CPU/RAM modest
        self.win = FloatingWindow()
        self._chat: ChatWorker | None = None
        self._pull: PullWorker | None = None
        self._workers: list[QThread] = []
        self._tasks: dict[int, OcrTask] = {}
        self._turns: list[tuple[str, str]] = []   # (role, text) for display
        self._active_model = self.cfg.model
        self._last_answer = ""
        self._pending_stream = ""
        self._quitting = False
        self.models_cache: list[str] = []
        self.ollama_ok = False

        self.bridge = HotkeyBridge()
        self.bridge.triggered.connect(self._on_hotkey)
        self.shortcuts = ShortcutManager({
            a: (lambda a=a: self.bridge.triggered.emit(a)) for a in self.cfg.shortcuts})

        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(120)
        self._stream_timer.timeout.connect(self._flush_stream)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(20000)
        self._status_timer.timeout.connect(self.refresh_status)

        self._connect_ui()
        self._build_tray()
        self.apply_config(initial=True)

    # ------------------------------------------------------------ setup
    def _make_ocr(self) -> OcrEngine:
        c = self.cfg
        return OcrEngine(c.tesseract_path, c.ocr_language, c.preprocess_grayscale,
                         c.preprocess_threshold, c.preprocess_upscale, c.max_image_dimension)

    def _connect_ui(self) -> None:
        w = self.win
        w.capture_clicked.connect(self.capture)
        w.submit_clicked.connect(self.submit)
        w.cancel_clicked.connect(self.cancel)
        w.retry_clicked.connect(self.retry)
        w.followup_submitted.connect(self.followup)
        w.retry_ocr_clicked.connect(self.retry_ocr)
        w.text_edited.connect(self._text_edited)
        w.clear_text_clicked.connect(self._clear_text)
        w.mode_changed.connect(self._mode_changed)
        w.input_mode_changed.connect(self._input_mode_changed)
        w.pause_toggled.connect(self._pause_toggled)
        w.aot_toggled.connect(self._aot_toggled)
        w.settings_clicked.connect(self.open_settings)
        w.clear_conversation_clicked.connect(self.clear_conversation)
        w.exit_clicked.connect(self.quit)
        w.btn_copy.clicked.disconnect()
        w.btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self._last_answer))
        q = w.queue
        q.current_changed.connect(self._current_changed)
        q.remove_requested.connect(self._remove)
        q.preview_requested.connect(self._preview)
        q.move_requested.connect(self._move)
        q.clear_requested.connect(self.clear_queue)
        q.selection_changed.connect(self._update_buttons)

    def _build_tray(self) -> None:
        self.icon = make_icon()
        self.win.setWindowIcon(self.icon)
        self.app.setWindowIcon(self.icon)
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip("Local Screen AI")
        menu = QMenu()
        menu.addAction("Show / hide", self.toggle_window)
        menu.addAction("Capture screen", self.capture)
        menu.addAction("Clear all data", self.clear_all)
        menu.addSeparator()
        menu.addAction("Exit", self.quit)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.toggle_window() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def start(self) -> None:
        self.win.show()
        self.refresh_status()
        self._status_timer.start()
        if not self.ocr.is_available()[0]:
            self.win.show_error(self.ocr.is_available()[1] + "\nInstall: winget install UB-Mannheim.TesseractOCR")

    def apply_config(self, initial: bool = False) -> None:
        c = self.cfg
        self.client = OllamaClient(c.ollama_url, c.request_timeout)
        self.ocr = self._make_ocr()
        self.session.queue_limit = c.queue_limit
        self.session.max_screenshots = c.max_screenshots
        self.app.setStyleSheet(theme_qss(c.theme))
        self.win.apply_theme(c.theme)
        w = self.win
        w.blockSignals(True)
        w.set_always_on_top(c.always_on_top)
        w.mode.blockSignals(True); w.mode.setCurrentIndex(w.mode.findData(c.assistant_mode)); w.mode.blockSignals(False)
        w.input_mode.blockSignals(True); w.input_mode.setCurrentIndex(w.input_mode.findData(c.input_mode)); w.input_mode.blockSignals(False)
        w.blockSignals(False)
        w.load_text(-1, "")
        self._register_shortcuts()
        self._update_model_label()
        self._update_capture_status()
        self._update_buttons()
        if not initial:
            if self.win.isVisible():
                self.win.show()
            self.refresh_status()
            save_config(self.cfg)
        w.queue.refresh(self.session.queue)

    def _register_shortcuts(self) -> None:
        ok = self.shortcuts.register(self.cfg.shortcuts)
        s = self.cfg.shortcuts
        self.win.set_shortcuts(s)
        self.win.set_shortcut_hint(
            f"Shortcuts — capture: {pretty(s['capture'])} · submit: {pretty(s['submit'])} · "
            f"show/hide: {pretty(s['toggle'])} · clear queue: {pretty(s['clear'])}")
        if not ok:
            self.win.show_error(f"{self.shortcuts.last_error}\nYou can still use the on-screen buttons. "
                                f"Change shortcuts in Settings.")

    # ------------------------------------------------------------ helpers
    def _worker(self, fn, on_ok=None, on_err=None) -> FuncWorker:
        w = FuncWorker(fn, self)
        if on_ok:
            w.result.connect(on_ok)
        if on_err:
            w.failed.connect(on_err)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()
        return w

    def _update_model_label(self) -> None:
        c = self.cfg
        m = c.model if c.input_mode == "text" else c.vision_model
        self.win.model_label.setText(
            f"Model: {m}  ·  {MODE_LABELS[c.assistant_mode]}  ·  ctx {c.context_length} · max {c.max_response_tokens} tok")

    def _update_capture_status(self) -> None:
        if self.session.capture_paused:
            self.win.set_capture_status("⏸ Capture PAUSED — shortcuts will not capture.", warn=True)
        else:
            self.win.set_capture_status("● Capture is user-initiated only (shortcut or button). "
                                        "Nothing is captured automatically.")

    def _update_buttons(self) -> None:
        busy = self._chat is not None
        has_sel = bool(self.session.selected())
        self.win.update_composer(busy, has_sel)
        self.win.set_conversation_active(bool(self.session.history))
        self.win.btn_retry.setEnabled(not busy and bool(self.session.history))
        self.win.btn_capture.setEnabled(not self.session.capture_paused)

    def refresh_status(self) -> None:
        client, model = self.client, self.cfg.model

        def work():
            ver = client.version()
            names = [m.name for m in client.list_models()]
            return ver, names

        def ok(res):
            ver, names = res
            self.ollama_ok = True
            self.models_cache = names
            present = model in names or f"{model}:latest" in names
            if present:
                self.win.status.set(f"Ollama {ver} · local", "ok", "Connected to local Ollama")
            else:
                self.win.status.set(f"Ollama OK · model '{model}' missing", "warn",
                                    f"Install with: ollama pull {model}")

        def err(e):
            self.ollama_ok = False
            self.win.status.set("Ollama not available", "bad", str(e))

        self._worker(work, ok, err)

    # ------------------------------------------------------------ hotkeys
    def _on_hotkey(self, action: str) -> None:
        {"capture": self.capture, "submit": self.submit, "toggle": self.toggle_window,
         "clear": self.clear_queue}.get(action, lambda: None)()

    def toggle_window(self) -> None:
        if self.win.isVisible() and not self.win.isMinimized():
            self.win.hide_window()
        else:
            self.win.showNormal(); self.win.raise_(); self.win.activateWindow()

    # ------------------------------------------------------------ capture / OCR
    def capture(self) -> None:
        if self.session.capture_paused:
            self.win.set_capture_status("⏸ Capture is paused. Resume to capture.", warn=True)
            return
        if len(self.session.queue) >= self.session.queue_limit:
            self.win.set_capture_status(f"Queue full ({self.session.queue_limit}). Remove items first.", warn=True)
            self.tray.showMessage("Local Screen AI", "Queue is full.", QSystemTrayIcon.Warning, 2000)
            return
        self.win.set_capture_status("📸 Capturing…")
        visible = self.win.isVisible()
        if visible:
            self.win.setWindowOpacity(0.0)   # keep our own window out of the screenshot
        QTimer.singleShot(180 if visible else 0, lambda: self._do_capture(visible))

    def _do_capture(self, restore: bool) -> None:
        try:
            img = capture_screen(self.cfg.monitor)
        except CaptureError as e:
            self.win.setWindowOpacity(1.0)
            self.win.show_error(str(e))
            return
        finally:
            if restore:
                self.win.setWindowOpacity(1.0)
        try:
            shot = self.session.add(img)
        except QueueFull as e:
            self.win.show_error(str(e))
            return
        self.win.show_error("")
        self._refresh_queue()
        self.win.queue.select_id(shot.id)
        self.win.set_capture_status(f"✔ Captured screenshot #{len(self.session.queue)} at {shot.timestamp:%H:%M:%S}")
        self.tray.showMessage("Local Screen AI", f"Captured screenshot #{len(self.session.queue)}",
                              QSystemTrayIcon.Information, 1500)
        self._run_ocr(shot.id)

    def _run_ocr(self, sid: int) -> None:
        shot = self.session.get(sid)
        if not shot:
            return
        self.session.set_ocr(sid, OcrStatus.PROCESSING)
        task = OcrTask(sid, shot.image.copy(), self.ocr)
        task.signals.done.connect(self._ocr_done)
        self._tasks[sid] = task
        self.pool.start(task)
        self._refresh_queue()

    def _ocr_done(self, sid: int, res) -> None:
        self._tasks.pop(sid, None)
        shot = self.session.get(sid)
        if not shot:
            return  # removed while processing
        if res.ok:
            self.session.set_ocr(sid, OcrStatus.COMPLETED, res.text)
        else:
            self.session.set_ocr(sid, OcrStatus.FAILED, "", res.error)
        self._refresh_queue()
        if self.win.queue.current_id() == sid:
            self._show_text(sid)
        if res.ok and res.empty:
            self.win.set_capture_status("OCR finished but found no text. Edit manually, retry, or use Vision mode.", warn=True)

    def retry_ocr(self) -> None:
        sid = self.win.queue.current_id()
        if sid != -1 and self.session.get(sid):
            self._run_ocr(sid)

    def _text_edited(self, sid: int, text: str) -> None:
        self.session.set_text(sid, text)
        s = self.session.get(sid)
        if s and s.ocr_status in (OcrStatus.FAILED, OcrStatus.PENDING) and text.strip():
            s.ocr_status, s.error = OcrStatus.COMPLETED, ""
        self._refresh_queue(keep_focus_text=True)

    def _clear_text(self) -> None:
        sid = self.win.queue.current_id()
        if sid != -1:
            self.session.set_text(sid, "")
            self._show_text(sid)
            self._refresh_queue(keep_focus_text=True)

    def _current_changed(self, sid: int) -> None:
        self._show_text(sid)

    def _show_text(self, sid: int) -> None:
        s = self.session.get(sid)
        if not s:
            self.win.load_text(-1, "")
            return
        idx = self.session.queue.index(s) + 1
        msg = f" — {s.error}" if s.error else ""
        self.win.load_text(sid, s.text, f"Extracted text · #{idx} · {s.ocr_status.value}{msg}")

    def _refresh_queue(self, keep_focus_text: bool = False) -> None:
        if keep_focus_text:
            # avoid rebuilding the editor while the user is typing
            self.win.queue.blockSignals(True)
            self.win.queue.refresh(self.session.queue, keep=self.win.queue.current_id())
            self.win.queue.blockSignals(False)
        else:
            self.win.queue.refresh(self.session.queue, keep=self.win.queue.current_id())
        self._update_buttons()

    def _remove(self, sid: int) -> None:
        self.session.remove(sid)
        self._refresh_queue()

    def _move(self, sid: int, delta: int) -> None:
        self.session.move(sid, delta)
        self._refresh_queue()

    def _preview(self, sid: int) -> None:
        s = self.session.get(sid)
        if s:
            PreviewDialog(s, self.win).exec()

    # ------------------------------------------------------------ session controls
    def _confirm(self, title: str, text: str) -> bool:
        self.win.showNormal(); self.win.raise_()
        return QMessageBox.question(self.win, title, text,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def clear_queue(self) -> None:
        if not self.session.queue:
            self.win.set_capture_status("Queue is already empty.")
            return
        if self._confirm("Clear queue", "Remove all screenshots and extracted text from the queue?"):
            self.session.clear_queue()
            self.win.load_text(-1, "")
            self._refresh_queue()
            self.win.set_capture_status("Queue cleared.")

    def clear_conversation(self) -> None:
        if self._chat:
            self.cancel()
        self.session.clear_conversation()
        self._turns.clear()
        self._last_answer = ""
        self.win.set_response("")
        self.win.show_error("")
        self.win.set_conversation_active(False)
        self._update_buttons()

    def clear_all(self) -> None:
        if self._confirm("Clear all data", "Clear the screenshot queue AND the conversation?"):
            if self._chat:
                self.cancel()
            self.session.clear_all()
            self._turns.clear()
            self._last_answer = ""
            self.win.set_response("")
            self.win.load_text(-1, "")
            self.win.set_conversation_active(False)
            self._refresh_queue()

    def _mode_changed(self, mode: str) -> None:
        self.cfg.assistant_mode = mode
        self._update_model_label()

    def _input_mode_changed(self, mode: str) -> None:
        self.cfg.input_mode = mode
        self._update_model_label()
        if mode != "text":
            QMessageBox.information(
                self.win, "Vision mode",
                "Vision/Hybrid sends the selected screenshots to a local vision model "
                f"('{self.cfg.vision_model}').\n\nThis can be significantly slower on this laptop "
                "(CPU/integrated graphics) and uses more memory. Text mode is recommended for most tasks.\n"
                "Everything stays local.")

    def _pause_toggled(self, paused: bool) -> None:
        self.session.capture_paused = paused
        self._update_capture_status()
        self._update_buttons()

    def _aot_toggled(self, on: bool) -> None:
        self.cfg.always_on_top = on
        self.win.set_always_on_top(on)

    # ------------------------------------------------------------ AI
    def submit(self) -> None:
        if self._chat:
            self.win.set_capture_status("Already generating — wait or press Stop.", warn=True)
            return
        shots = self.session.selected()[: self.cfg.max_screenshots]
        if not shots:
            self.win.show_error("Select at least one screenshot in the queue (capture one first).")
            return
        if any(s.ocr_status == OcrStatus.PROCESSING for s in shots) and self.cfg.input_mode != "vision":
            self.win.show_error("OCR is still processing a selected screenshot. Please wait a moment.")
            return
        mode = self.cfg.input_mode
        if mode == "text" and not any(s.text.strip() for s in shots):
            self.win.show_error("No extracted text to send. Edit the text, retry OCR, or switch Input to Vision/Hybrid.")
            return
        if len(self.session.selected()) > self.cfg.max_screenshots:
            self.win.set_capture_status(f"Only the first {self.cfg.max_screenshots} selected screenshots are sent (limit in Settings).", warn=True)
        if mode != "text":
            if not self._confirm("Vision inference",
                                 f"Vision inference with '{self.cfg.vision_model}' may be much slower on this "
                                 "laptop. Continue? (All processing stays local.)"):
                return
        model = self.cfg.model if mode == "text" else self.cfg.vision_model
        prompt = self.win.prompt.text()
        self.win.prompt.clear()
        self.win.set_conversation_active(True)
        images = None
        if mode != "text":
            images = [to_base64_png(s.image, self.cfg.vision_max_dimension) for s in shots]
        history = self.session.start_conversation(self.cfg.assistant_mode, prompt, self.cfg.context_length,
                                                  images=images, include_text=(mode != "vision"))
        self._turns = [("user", prompt.strip() or "(default prompt)")]
        self._active_model = model
        self._preflight_then_run(model, need_vision=(mode != "text"), messages=history)

    def followup(self, question: str) -> None:
        if self._chat:
            return
        if not self.session.history:
            self.win.show_error("Submit the queue first, then ask follow-up questions.")
            return
        msgs = self.session.followup(question, self.cfg.context_length)
        self._turns.append(("user", question))
        self._preflight_then_run(self._active_model, need_vision=False, messages=msgs)

    def retry(self) -> None:
        if self._chat or not self.session.history:
            return
        self.session.drop_last_assistant()
        if self._turns and self._turns[-1][0] == "assistant":
            self._turns.pop()
        if not self.session.history or self.session.history[-1].role != "user":
            return
        msgs = trim_history(self.session.history, self.cfg.context_length)
        self._preflight_then_run(self._active_model, need_vision=False, messages=msgs)

    def _preflight_then_run(self, model: str, need_vision: bool, messages) -> None:
        self.win.show_error("")
        self.win.set_busy(True)
        self._render(pending="")
        client = self.client

        def work():
            client.version()
            if not client.has_model(model):
                raise ModelMissing(model)
            if need_vision and not client.supports_vision(model):
                raise ModelNotVision(f"Model '{model}' does not support image input. "
                                     "Choose a vision model (e.g. qwen2.5vl:3b) in Settings.")
            return True

        def err(e):
            self.win.set_busy(False)
            self._update_buttons()
            self._handle_error(e)

        self._worker(work, lambda _: self._start_chat(model, messages), err)

    def _start_chat(self, model: str, messages) -> None:
        c = self.cfg
        self._pending_stream = ""
        self._chat = ChatWorker(self.client, model, list(messages), c.context_length,
                                c.max_response_tokens, c.temperature, self)
        self._chat.token.connect(self._on_token)
        self._chat.finished_ok.connect(self._chat_ok)
        self._chat.failed.connect(self._chat_failed)
        self._chat.cancelled.connect(self._chat_cancelled)
        self._chat.finished.connect(self._chat_finished)
        self.win.set_busy(True)
        self._stream_timer.start()
        self._chat.start()

    def _on_token(self, t: str) -> None:
        self._pending_stream += t

    def _flush_stream(self) -> None:
        if self._chat:
            self._render(pending=self._pending_stream)

    def _render(self, pending: str | None = None) -> None:
        blocks = []
        for role, text in self._turns:
            blocks.append(f"**You:** {text}" if role == "user" else text)
        if pending is not None:
            blocks.append(pending if pending else "*Thinking…*")
        self.win.set_response("\n\n---\n\n".join(blocks))

    def _chat_ok(self, text: str) -> None:
        text = text.strip() or "*(The model returned an empty response.)*"
        self.session.add_assistant(text)
        self._turns.append(("assistant", text))
        self._last_answer = text

    def _chat_cancelled(self, partial: str) -> None:
        if partial.strip():
            text = partial.strip() + "\n\n*(stopped)*"
            self.session.add_assistant(text)
            self._turns.append(("assistant", text))
            self._last_answer = text

    def _chat_failed(self, e) -> None:
        self._handle_error(e)

    def _chat_finished(self) -> None:
        self._stream_timer.stop()
        self._chat = None
        self.win.set_busy(False)
        self._render()
        self._update_buttons()

    def cancel(self) -> None:
        if self._chat:
            self._chat.cancel()
        if self._pull:
            self._pull.client.cancel()

    def _handle_error(self, e) -> None:
        if isinstance(e, ModelMissing):
            self.win.show_error(str(e))
            self._offer_pull(e.model)
        elif isinstance(e, OllamaUnavailable):
            self.win.show_error(str(e))
            self.win.status.set("Ollama not available", "bad", str(e))
        elif isinstance(e, OllamaError):
            self.win.show_error(str(e))
        else:
            self.win.show_error(f"Unexpected error: {e}")

    # ------------------------------------------------------------ model download (explicit consent)
    def _offer_pull(self, model: str) -> None:
        box = QMessageBox(self.win)
        box.setWindowTitle("Model not installed")
        box.setText(f"The model '{model}' is not installed.")
        box.setInformativeText(
            f"Install it manually with:\n\n    ollama pull {model}\n\n"
            "or let the app download it now (requires internet and disk space; "
            "small models are ~1–2 GB).")
        dl = box.addButton("Download now", QMessageBox.AcceptRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is dl:
            self._download(model)

    def _download(self, model: str) -> None:
        dlg = QProgressDialog(f"Downloading {model}…", "Cancel", 0, 100, self.win)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        w = PullWorker(self.client, model)
        self._pull = w
        w.progress.connect(lambda s, f: (dlg.setLabelText(f"{model}: {s}"),
                                         dlg.setValue(int(f * 100)) if f >= 0 else None))
        w.done.connect(lambda: (dlg.close(), self.win.set_capture_status(f"Downloaded {model}."), self.refresh_status()))
        w.failed.connect(lambda e: (dlg.close(), self._handle_error(e)))
        w.finished.connect(lambda: setattr(self, "_pull", None))
        dlg.canceled.connect(lambda: w.client.cancel())
        w.start()

    # ------------------------------------------------------------ settings
    def open_settings(self) -> None:
        mons = []
        try:
            mons = list_monitors()
        except Exception:
            mons = ["All monitors", "Monitor 1"]
        ok, info = self.ocr.is_available()
        ocr_status = f"Tesseract found: {info}" if ok else info
        dlg = SettingsDialog(self.cfg, lambda: OllamaClient(self.cfg.ollama_url, 5), mons, ocr_status, self.win)
        dlg.clear_queue_requested.connect(self.clear_queue)
        dlg.clear_conversation_requested.connect(self.clear_conversation)
        if dlg.exec():
            new = dlg.result_config()
            new.assistant_mode, new.input_mode = self.cfg.assistant_mode, self.cfg.input_mode
            self.cfg = new
            self.apply_config()

    # ------------------------------------------------------------ shutdown
    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.shortcuts.unregister()
        self._status_timer.stop()
        if self._chat:
            self._chat.cancel()
            self._chat.wait(3000)
        if self._pull:
            self._pull.client.cancel()
            self._pull.wait(2000)
        for w in list(self._workers):
            w.wait(1500)
        self.pool.clear()
        self.pool.waitForDone(3000)
        try:
            save_config(self.cfg)
        except OSError:
            pass
        self.session.clear_all()
        self.tray.hide()
        self.app.quit()
