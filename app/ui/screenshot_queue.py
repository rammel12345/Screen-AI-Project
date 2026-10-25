"""Screenshot queue panel (sidebar)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMenu, QProgressBar, QScrollArea, QVBoxLayout, QWidget)

from app.models import OcrStatus, Screenshot
from app.ui.widgets import G, icon_button, pil_to_pixmap

STATUS_COLORS = {OcrStatus.PENDING: "#71717a", OcrStatus.PROCESSING: "#fbbf24",
                 OcrStatus.COMPLETED: "#34d399", OcrStatus.FAILED: "#f87171"}


class QueueItemWidget(QWidget):
    toggled = Signal(int, bool)
    remove_clicked = Signal(int)
    preview_clicked = Signal(int)
    move_clicked = Signal(int, int)

    def __init__(self, shot: Screenshot, index: int):
        super().__init__()
        self.sid = shot.id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setSpacing(8)
        self.check = QCheckBox()
        self.check.setToolTip("Include in submission")
        self.check.toggled.connect(lambda v: self.toggled.emit(self.sid, v))
        lay.addWidget(self.check, 0, Qt.AlignTop)
        self.thumb = QLabel()
        self.thumb.setPixmap(pil_to_pixmap(shot.image, (76, 48)))
        self.thumb.setFixedSize(76, 48)
        self.thumb.setStyleSheet("border-radius:4px;")
        lay.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.head = QLabel()
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.text = QLabel()
        self.text.setObjectName("muted")
        self.text.setMinimumWidth(10)
        col.addWidget(self.head)
        col.addWidget(self.status)
        col.addWidget(self.text)
        self.busy = QProgressBar(); self.busy.setRange(0, 0); self.busy.setTextVisible(False)
        col.addWidget(self.busy)
        lay.addLayout(col, 1)
        grid = QGridLayout()
        grid.setSpacing(0)
        grid.setContentsMargins(0, 0, 0, 0)
        up = icon_button(G["up"], "Move up", small=True); up.clicked.connect(lambda: self.move_clicked.emit(self.sid, -1))
        dn = icon_button(G["down"], "Move down", small=True); dn.clicked.connect(lambda: self.move_clicked.emit(self.sid, 1))
        pv = icon_button(G["eye"], "Preview screenshot", small=True); pv.clicked.connect(lambda: self.preview_clicked.emit(self.sid))
        rm = icon_button(G["close"], "Remove from queue", small=True, danger=True); rm.clicked.connect(lambda: self.remove_clicked.emit(self.sid))
        grid.addWidget(up, 0, 0); grid.addWidget(pv, 0, 1)
        grid.addWidget(dn, 1, 0); grid.addWidget(rm, 1, 1)
        lay.addLayout(grid)
        self.update_from(shot, index)

    def update_from(self, shot: Screenshot, index: int) -> None:
        w, h = shot.size
        self.head.setText(f"<b>#{index}</b>&nbsp;&nbsp;<span style='color:#a1a1aa'>{shot.timestamp:%H:%M:%S} · {w}×{h}</span>")
        c = STATUS_COLORS[shot.ocr_status]
        extra = f" — {shot.error}" if shot.error and shot.ocr_status == OcrStatus.FAILED else ""
        self.status.setText(f"<span style='color:{c}'>●</span>&nbsp;OCR {shot.ocr_status.value}{extra}")
        self.status.setToolTip(shot.error)
        self.busy.setVisible(shot.ocr_status == OcrStatus.PROCESSING)
        if shot.ocr_status == OcrStatus.COMPLETED and not shot.text.strip():
            self.text.setText("(no text recognized)")
        else:
            self.text.setText((shot.preview or "")[:60])
        self.check.blockSignals(True)
        self.check.setChecked(shot.selected)
        self.check.blockSignals(False)


class ScreenshotQueuePanel(QWidget):
    current_changed = Signal(int)          # screenshot id (or -1)
    selection_changed = Signal()
    remove_requested = Signal(int)
    preview_requested = Signal(int)
    move_requested = Signal(int, int)
    clear_requested = Signal()

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(14, 12, 8, 0)
        cap = QLabel("QUEUE"); cap.setObjectName("caption")
        self.count = QLabel("0"); self.count.setObjectName("count")
        self.selected_lbl = QLabel(""); self.selected_lbl.setObjectName("muted")
        top.addWidget(cap); top.addWidget(self.count); top.addWidget(self.selected_lbl)
        top.addStretch()
        self.btn_more = icon_button(G["more"], "Queue actions")
        self.btn_more.clicked.connect(self._menu)
        top.addWidget(self.btn_more)
        lay.addLayout(top)

        self.list = QListWidget()
        self.list.setSpacing(0)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.currentItemChanged.connect(self._on_current)
        lay.addWidget(self.list, 1)

        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setAlignment(Qt.AlignCenter)
        ic = QLabel(G["picture"]); ic.setObjectName("glyph")
        ic.setStyleSheet("font-size:30px; color:#71717a;"); ic.setAlignment(Qt.AlignCenter)
        t = QLabel("Nothing captured yet"); t.setObjectName("emptyTitle"); t.setAlignment(Qt.AlignCenter)
        s = QLabel("Use the Capture button or your capture shortcut.\nNothing is captured automatically.")
        s.setObjectName("muted"); s.setAlignment(Qt.AlignCenter); s.setWordWrap(True)
        for w in (ic, t, s):
            el.addWidget(w)
        lay.addWidget(self.empty, 1)
        self._shots: list[Screenshot] = []

    def _menu(self) -> None:
        m = QMenu(self)
        m.addAction("Select all", lambda: self._set_all(True))
        m.addAction("Select none", lambda: self._set_all(False))
        m.addSeparator()
        a = m.addAction("Clear all…", self.clear_requested.emit)
        a.setEnabled(bool(self._shots))
        m.exec(self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft()))

    def _on_current(self, cur, _prev) -> None:
        self.current_changed.emit(cur.data(Qt.UserRole) if cur else -1)

    def _set_all(self, v: bool) -> None:
        for s in self._shots:
            s.selected = v
        self.refresh(self._shots, keep=self.current_id())
        self.selection_changed.emit()

    def current_id(self) -> int:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else -1

    def _update_counts(self) -> None:
        n_sel = sum(1 for s in self._shots if s.selected)
        self.count.setText(str(len(self._shots)))
        self.selected_lbl.setText(f"{n_sel} selected" if self._shots else "")

    def refresh(self, shots: list[Screenshot], keep: int | None = None) -> None:
        self._shots = shots
        keep = self.current_id() if keep is None else keep
        self.list.blockSignals(True)
        self.list.clear()
        for i, s in enumerate(shots, 1):
            it = QListWidgetItem()
            it.setData(Qt.UserRole, s.id)
            w = QueueItemWidget(s, i)
            w.toggled.connect(self._on_toggle)
            w.remove_clicked.connect(self.remove_requested)
            w.preview_clicked.connect(self.preview_requested)
            w.move_clicked.connect(self.move_requested)
            it.setSizeHint(QSize(280, 74))
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            if s.id == keep:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        self._update_counts()
        self.empty.setVisible(not shots)
        self.list.setVisible(bool(shots))
        if not shots or self.current_id() == -1:
            self.current_changed.emit(self.current_id())

    def _on_toggle(self, sid: int, v: bool) -> None:
        for s in self._shots:
            if s.id == sid:
                s.selected = v
        self._update_counts()
        self.selection_changed.emit()

    def select_id(self, sid: int) -> None:
        for r in range(self.list.count()):
            if self.list.item(r).data(Qt.UserRole) == sid:
                self.list.setCurrentRow(r)
                return


class PreviewDialog(QDialog):
    def __init__(self, shot: Screenshot, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Screenshot preview — {shot.timestamp:%H:%M:%S} ({shot.size[0]}×{shot.size[1]})")
        lay = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setPixmap(pil_to_pixmap(shot.image, (1100, 700)))
        scroll.setWidget(lbl)
        lay.addWidget(scroll)
        self.resize(1000, 650)
