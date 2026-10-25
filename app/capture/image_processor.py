"""Image preprocessing. The original image is never modified."""
from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps


def fit_max_dimension(img: Image.Image, max_dim: int) -> Image.Image:
    """Downscale (never upscale) preserving aspect ratio so the longest side <= max_dim."""
    w, h = img.size
    longest = max(w, h)
    if longest <= max_dim:
        return img.copy()
    scale = max_dim / longest
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def preprocess_for_ocr(
    img: Image.Image,
    grayscale: bool = True,
    threshold: bool = False,
    upscale: bool = True,
    max_dim: int = 2560,
) -> Image.Image:
    """Return a new image prepared for OCR; aspect ratio is preserved."""
    out = img.convert("RGB")
    w, h = out.size
    # Small screenshots (e.g. crops) benefit from upscaling; keep within max_dim.
    if upscale and max(w, h) < 1200:
        factor = min(2.0, max_dim / max(w, h))
        if factor > 1:
            out = out.resize((round(w * factor), round(h * factor)), Image.LANCZOS)
    out = fit_max_dimension(out, max_dim)
    if grayscale or threshold:
        out = ImageOps.grayscale(out)
        out = ImageOps.autocontrast(out)
        # Dark themes (light text on dark bg): invert so Tesseract sees dark-on-light.
        if _mean(out) < 110:
            out = ImageOps.invert(out)
    if threshold:
        t = _otsu(out)
        out = out.point(lambda p: 255 if p > t else 0, mode="L")
    return out


def _mean(gray: Image.Image) -> float:
    hist = gray.histogram()
    total = sum(hist) or 1
    return sum(i * c for i, c in enumerate(hist)) / total


def _otsu(gray: Image.Image) -> int:
    hist = gray.histogram()
    total = sum(hist)
    sum_all = sum(i * c for i, c in enumerate(hist))
    sum_b = w_b = 0
    best, thr = 0.0, 127
    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * hist[i]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            best, thr = var, i
    return thr


def to_base64_png(img: Image.Image, max_dim: int = 1280) -> str:
    """Encode for Ollama vision input, downscaled to limit memory/latency."""
    small = fit_max_dimension(img.convert("RGB"), max_dim)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
