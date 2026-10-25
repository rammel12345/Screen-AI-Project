"""Local Screen AI — entry point."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    from PySide6.QtCore import QLockFile, QDir
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(argv)
    app.setApplicationName("Local Screen AI")
    app.setQuitOnLastWindowClosed(False)  # lives in tray when the window is hidden

    is_selftest = "--selftest" in argv
    lock = QLockFile(QDir.temp().filePath("local_screen_ai_test.lock" if is_selftest else "local_screen_ai.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        if not is_selftest:
            QMessageBox.information(None, "Local Screen AI", "The application is already running (check the system tray).")
        return 0

    from app.ui.main_window import AppController
    ctl = AppController(app)
    ctl.start()
    if "--selftest" in argv:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, ctl.quit)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
