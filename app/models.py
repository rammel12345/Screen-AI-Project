"""Core data models."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from PIL import Image

_ids = itertools.count(1)


class OcrStatus(str, Enum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"


@dataclass
class Screenshot:
    image: Image.Image
    timestamp: datetime = field(default_factory=datetime.now)
    id: int = field(default_factory=lambda: next(_ids))
    ocr_status: OcrStatus = OcrStatus.PENDING
    text: str = ""
    error: str = ""
    selected: bool = True

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    @property
    def preview(self) -> str:
        t = " ".join(self.text.split())
        return t[:120] + ("…" if len(t) > 120 else "")


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str
    images: list[str] | None = None  # base64 PNGs (vision only)
