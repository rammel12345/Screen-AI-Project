"""Local OCR via Tesseract. No confidence score is fabricated."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from PIL import Image

from app.capture.image_processor import preprocess_for_ocr
from app.ocr.text_preprocessor import clean_ocr_text, is_effectively_empty

DEFAULT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]


class OcrError(Exception):
    pass


@dataclass
class OcrResult:
    text: str
    empty: bool
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def find_tesseract(configured: str = "") -> str | None:
    if configured and os.path.isfile(configured):
        return configured
    found = shutil.which("tesseract")
    if found:
        return found
    for p in DEFAULT_PATHS:
        if os.path.isfile(p):
            return p
    return None


def run_tesseract(img: Image.Image, lang: str, psm: int = 6) -> str:
    import pytesseract
    # preserve_interword_spaces keeps code indentation more faithfully
    cfg = f"--oem 3 --psm {psm} -c preserve_interword_spaces=1"
    return pytesseract.image_to_string(img, lang=lang, config=cfg)


class OcrEngine:
    def __init__(self, tesseract_path: str = "", language: str = "eng",
                 grayscale: bool = True, threshold: bool = False,
                 upscale: bool = True, max_dim: int = 2560):
        self.tesseract_path = tesseract_path
        self.language = language
        self.grayscale = grayscale
        self.threshold = threshold
        self.upscale = upscale
        self.max_dim = max_dim

    def is_available(self) -> tuple[bool, str]:
        path = find_tesseract(self.tesseract_path)
        if not path:
            return False, ("Tesseract not found. Install it (see README) or set its path in Settings.")
        return True, path

    def extract(self, img: Image.Image) -> OcrResult:
        ok, info = self.is_available()
        if not ok:
            return OcrResult("", True, info)
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = info
            prepared = preprocess_for_ocr(img, self.grayscale, self.threshold,
                                          self.upscale, self.max_dim)
            raw = run_tesseract(prepared, self.language)
        except Exception as e:
            return OcrResult("", True, f"OCR failed: {e}")
        text = clean_ocr_text(raw)
        return OcrResult(text, is_effectively_empty(text))
