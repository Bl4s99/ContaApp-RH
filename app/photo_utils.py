from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from PIL import ImageTk as PILImageTk

from app.calendar_widget import PRESET_COLORS

STORED_MAX_DIMENSION = 500
STORED_JPEG_QUALITY = 85
MAX_SOURCE_FILE_BYTES = 20 * 1024 * 1024

SUPPORTED_FILE_TYPES = [
    ("Imágenes", "*.jpg *.jpeg *.png *.bmp *.gif *.webp"),
    ("Todos los archivos", "*.*"),
]


class PhotoProcessingError(Exception):
    pass


def process_uploaded_photo(
    source_path: Path, max_dimension: int = STORED_MAX_DIMENSION
) -> bytes:
    try:
        file_size = source_path.stat().st_size
    except OSError as exc:
        raise PhotoProcessingError(f"no se pudo leer el archivo: {exc}") from exc
    if file_size > MAX_SOURCE_FILE_BYTES:
        limit_mb = MAX_SOURCE_FILE_BYTES // (1024 * 1024)
        raise PhotoProcessingError(f"la imagen supera el tamaño máximo permitido ({limit_mb} MB)")

    try:
        with Image.open(source_path) as raw_image:
            image = ImageOps.exif_transpose(raw_image) or raw_image
            image = image.convert("RGB")
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=STORED_JPEG_QUALITY)
            return buffer.getvalue()
    except UnidentifiedImageError as exc:
        raise PhotoProcessingError("el archivo no es una imagen reconocible") from exc
    except OSError as exc:
        raise PhotoProcessingError(f"no se pudo procesar la imagen: {exc}") from exc


def photo_to_tk_image(photo_bytes: bytes, size: tuple[int, int]) -> PILImageTk.PhotoImage:
    with Image.open(BytesIO(photo_bytes)) as image:
        rendered = image.convert("RGB")
        rendered = ImageOps.fit(rendered, size, Image.Resampling.LANCZOS)
        return PILImageTk.PhotoImage(rendered)


def placeholder_tk_image(full_name: str, size: tuple[int, int]) -> PILImageTk.PhotoImage:
    initials = _initials(full_name)
    color = _avatar_color(full_name)

    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=int(min(size) * 0.45))
    left, top, right, bottom = draw.textbbox((0, 0), initials, font=font)
    text_width, text_height = right - left, bottom - top
    position = ((size[0] - text_width) / 2 - left, (size[1] - text_height) / 2 - top)
    draw.text(position, initials, fill="white", font=font)
    return PILImageTk.PhotoImage(image)


def _avatar_color(full_name: str) -> str:
    return PRESET_COLORS[sum(map(ord, full_name or "?")) % len(PRESET_COLORS)]


def _initials(full_name: str) -> str:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()
