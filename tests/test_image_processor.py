from PIL import Image, ImageDraw
from app.capture.image_processor import preprocess_for_ocr, fit_max_dimension, to_base64_png


def test_aspect_ratio_preserved_on_downscale():
    img = Image.new("RGB", (4000, 2000), "white")
    out = fit_max_dimension(img, 2000)
    assert out.size == (2000, 1000)
    assert img.size == (4000, 2000)  # original untouched


def test_no_upscale_in_fit():
    img = Image.new("RGB", (800, 600))
    assert fit_max_dimension(img, 2000).size == (800, 600)


def test_preprocess_grayscale_and_original_unchanged():
    img = Image.new("RGB", (1600, 900), (200, 50, 50))
    out = preprocess_for_ocr(img, grayscale=True, max_dim=1600)
    assert out.mode == "L" and out.size == (1600, 900)
    assert img.mode == "RGB"


def test_small_image_upscaled_keeps_ratio():
    img = Image.new("RGB", (300, 100), "white")
    out = preprocess_for_ocr(img, upscale=True, max_dim=2560)
    assert out.size == (600, 200)


def test_max_dim_respected():
    out = preprocess_for_ocr(Image.new("RGB", (5000, 1000), "white"), max_dim=1000)
    assert max(out.size) == 1000 and out.size[0] / out.size[1] == 5


def test_dark_theme_inverted():
    img = Image.new("RGB", (1300, 300), (20, 20, 20))
    ImageDraw.Draw(img).rectangle([10, 10, 600, 100], fill=(240, 240, 240))
    out = preprocess_for_ocr(img, grayscale=True, upscale=False)
    assert out.getpixel((1200, 250)) > 200  # background became light


def test_threshold_binary():
    img = Image.new("RGB", (1300, 300), "white")
    ImageDraw.Draw(img).rectangle([10, 10, 600, 100], fill="black")
    out = preprocess_for_ocr(img, threshold=True, upscale=False)
    assert set(out.getdata()) <= {0, 255}


def test_base64():
    s = to_base64_png(Image.new("RGB", (50, 50)))
    assert isinstance(s, str) and len(s) > 10
