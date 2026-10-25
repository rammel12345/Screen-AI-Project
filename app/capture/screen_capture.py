"""Screen capture (user-initiated only) using mss."""
from __future__ import annotations

import mss
from PIL import Image


class CaptureError(Exception):
    pass


def list_monitors() -> list[str]:
    """Index 0 = all monitors combined; 1..n = individual monitors."""
    with mss.mss() as sct:
        out = []
        for i, m in enumerate(sct.monitors):
            label = "All monitors" if i == 0 else f"Monitor {i}"
            out.append(f"{label} ({m['width']}x{m['height']})")
        return out


def capture_screen(monitor: int = 1) -> Image.Image:
    try:
        with mss.mss() as sct:
            if monitor < 0 or monitor >= len(sct.monitors):
                monitor = 1 if len(sct.monitors) > 1 else 0
            shot = sct.grab(sct.monitors[monitor])
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except Exception as e:  # mss raises ScreenShotError and others
        raise CaptureError(f"Screen capture failed: {e}") from e
