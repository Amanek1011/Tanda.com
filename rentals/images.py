"""Работа с фото: уменьшаем снимки с телефона и переводим в JPEG."""
import base64
import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class BadImage(ValueError):
    pass


def _open(uploaded):
    if uploaded.size and uploaded.size > MAX_UPLOAD_BYTES:
        raise BadImage("Фото больше 10 МБ. Загрузите снимок поменьше.")
    try:
        uploaded.seek(0)
        img = Image.open(uploaded)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise BadImage("Это не похоже на фото. Загрузите изображение JPG или PNG.")
    img = ImageOps.exif_transpose(img)  # фото с телефона часто повёрнуто
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def to_jpeg_bytes(uploaded, max_side, quality=85):
    img = _open(uploaded)
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def shrink(uploaded, max_side=1600, quality=85):
    """Возвращает уменьшенную копию как файл для ImageField."""
    return ContentFile(to_jpeg_bytes(uploaded, max_side, quality), name="photo.jpg")


def as_claude_image(uploaded):
    """Блок изображения для Anthropic API (base64 JPEG, до 1568 px по длинной стороне)."""
    data = to_jpeg_bytes(uploaded, 1568, 85)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }
