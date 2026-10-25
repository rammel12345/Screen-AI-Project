"""Session state: screenshot queue and conversation. In memory only."""
from __future__ import annotations

from PIL import Image

from app.models import ChatMessage, OcrStatus, Screenshot
from app.ai.prompts import build_initial_messages, build_followup, trim_history


class QueueFull(Exception):
    pass


class SessionManager:
    def __init__(self, queue_limit: int = 10, max_screenshots: int = 5):
        self.queue_limit = queue_limit
        self.max_screenshots = max_screenshots
        self.queue: list[Screenshot] = []
        self.history: list[ChatMessage] = []
        self.capture_paused = False

    # ---- queue ----
    def add(self, image: Image.Image) -> Screenshot:
        if len(self.queue) >= self.queue_limit:
            raise QueueFull(f"Queue is full ({self.queue_limit}). Remove items or raise the limit.")
        s = Screenshot(image=image)
        self.queue.append(s)
        return s

    def get(self, sid: int) -> Screenshot | None:
        return next((s for s in self.queue if s.id == sid), None)

    def remove(self, sid: int) -> bool:
        s = self.get(sid)
        if s:
            self.queue.remove(s)
            s.image.close()
            return True
        return False

    def move(self, sid: int, delta: int) -> bool:
        s = self.get(sid)
        if not s:
            return False
        i = self.queue.index(s)
        j = i + delta
        if not 0 <= j < len(self.queue):
            return False
        self.queue[i], self.queue[j] = self.queue[j], self.queue[i]
        return True

    def set_text(self, sid: int, text: str) -> None:
        s = self.get(sid)
        if s:
            s.text = text

    def set_ocr(self, sid: int, status: OcrStatus, text: str | None = None, error: str = "") -> None:
        s = self.get(sid)
        if s:
            s.ocr_status = status
            s.error = error
            if text is not None:
                s.text = text

    def selected(self) -> list[Screenshot]:
        return [s for s in self.queue if s.selected]

    def clear_queue(self) -> None:
        for s in self.queue:
            s.image.close()
        self.queue.clear()

    # ---- conversation ----
    def start_conversation(self, mode: str, prompt: str, context_length: int,
                           images: list[str] | None = None, include_text: bool = True) -> list[ChatMessage]:
        shots = self.selected()[: self.max_screenshots]
        self.history = build_initial_messages(mode, prompt, shots, context_length,
                                              images=images, include_text=include_text)
        return list(self.history)

    def followup(self, question: str, context_length: int) -> list[ChatMessage]:
        if not self.history:
            raise ValueError("No active conversation.")
        self.history = build_followup(self.history, question)
        return trim_history(self.history, context_length)

    def add_assistant(self, text: str) -> None:
        self.history.append(ChatMessage("assistant", text))

    def drop_last_assistant(self) -> None:
        if self.history and self.history[-1].role == "assistant":
            self.history.pop()

    def clear_conversation(self) -> None:
        self.history.clear()

    def clear_all(self) -> None:
        self.clear_queue()
        self.clear_conversation()
