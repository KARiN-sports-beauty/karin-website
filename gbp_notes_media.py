"""KARiN.NOTES のGBP投稿だけが使う画像変換。

元画像は変更しない。Googleへ渡す sourceUrl 用に、
baseline JPEG を別URLで配信する。
"""

from __future__ import annotations

import os
from io import BytesIO
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from PIL import Image, ImageOps

MEDIA_PATH = "/gbp-notes-media"
MIN_EDGE = 250
MAX_EDGE = 1600
MIN_BYTES = 10 * 1024
MAX_BYTES = 5 * 1024 * 1024
ALLOWED_DIRS = frozenset({"notes", "blogs"})
ALLOWED_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})

_ROOT = os.path.dirname(os.path.abspath(__file__))
IMAGES_ROOT = os.path.join(_ROOT, "static", "images")
_CACHE = {}


def _base_url():
    return (os.getenv("SITE_BASE_URL") or os.getenv("PUBLIC_SITE_URL") or "https://karin-sb.jp").strip().rstrip("/")


def safe_relpath(rel):
    text = unquote(rel or "").replace("\\", "/").strip()
    text = text.lstrip("/")
    if text.startswith("static/images/"):
        text = text[len("static/images/") :]
    if not text or ".." in text.split("/"):
        return None
    parts = [part for part in text.split("/") if part]
    if not parts or any(part.startswith(".") for part in parts):
        return None
    if len(parts) >= 2 and parts[0] not in ALLOWED_DIRS:
        return None
    if os.path.splitext(parts[-1])[1].lower() not in ALLOWED_EXTS:
        return None
    return "/".join(parts)


def local_path(rel):
    safe = safe_relpath(rel)
    if not safe:
        return None
    root = os.path.realpath(IMAGES_ROOT)
    path = os.path.realpath(os.path.join(root, *safe.split("/")))
    if path != root and not path.startswith(root + os.sep):
        return None
    if not os.path.isfile(path):
        return None
    return path


def site_image_relpath(image_url):
    text = (image_url or "").strip()
    if not text.startswith("https://"):
        return None
    parts = urlsplit(text)
    path = unquote(parts.path or "")
    if not path.startswith("/static/images/"):
        return None
    return safe_relpath(path[len("/static/images/") :])


def notes_source_url(image_url):
    """Googleへ渡す画像URL。失敗時は (None, エラー)。"""
    text = (image_url or "").strip()
    rel = site_image_relpath(text)
    if not rel:
        if text.startswith("https://"):
            parts = urlsplit(text)
            path = quote(unquote(parts.path), safe="/-_.~")
            return urlunsplit((parts.scheme, parts.netloc, path, parts.query, "")), None
        return None, "画像を添える場合は、公開された https のURLにしてください"
    path = local_path(rel)
    if path:
        data, err = jpeg_bytes_from_path(path)
        if err:
            return None, err
        if not data:
            return None, "画像をGBP用のJPEGにできません"
    encoded = quote(rel, safe="/-_.~")
    return f"{_base_url()}{MEDIA_PATH}/{encoded}", None


def jpeg_bytes(rel):
    path = local_path(rel)
    if not path:
        return None, "not found"
    return jpeg_bytes_from_path(path)


def jpeg_bytes_from_path(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None, "画像が見つかりません"
    key = (path, stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(key)
    if cached:
        return cached, None
    try:
        data = _convert_jpeg(path)
    except Exception:
        return None, "画像をGBP用のJPEGにできません"
    if not data:
        return None, "画像をGBP用のJPEGにできません"
    if len(_CACHE) >= 8:
        _CACHE.clear()
    _CACHE[key] = data
    return data, None


def _convert_jpeg(path):
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        else:
            image = image.copy()
    width, height = image.size
    if min(width, height) < MIN_EDGE:
        return None
    if max(width, height) > MAX_EDGE:
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        if min(image.size) < MIN_EDGE:
            return None
    data = _save_jpeg(image, 85)
    quality = 80
    while data and len(data) > MAX_BYTES and quality >= 50:
        data = _save_jpeg(image, quality)
        quality -= 10
    if not data or len(data) < MIN_BYTES or len(data) > MAX_BYTES:
        return None
    if data[:2] != b"\xff\xd8":
        return None
    return data


def _save_jpeg(image, quality):
    buf = BytesIO()
    image.save(
        buf,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=False,
        subsampling=2,
    )
    return buf.getvalue()
