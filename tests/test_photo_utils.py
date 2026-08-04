from __future__ import annotations

import io
import tkinter as tk
from pathlib import Path

import pytest
from PIL import Image

from app.photo_utils import (
    MAX_SOURCE_FILE_BYTES,
    PhotoProcessingError,
    STORED_MAX_DIMENSION,
    _avatar_color,
    _initials,
    photo_to_tk_image,
    placeholder_tk_image,
    process_uploaded_photo,
)

# tk_root fixture is session-scoped in tests/conftest.py, shared across all
# test modules that need a live Tk interpreter.


def make_source_image(
    tmp_path: Path, size: tuple[int, int] = (1200, 800), fmt: str = "PNG", name: str = "foto.png"
) -> Path:
    path = tmp_path / name
    Image.new("RGB", size, "blue").save(path, format=fmt)
    return path


class TestProcessUploadedPhoto:
    def test_produces_valid_jpeg_bytes(self, tmp_path: Path) -> None:
        source = make_source_image(tmp_path)
        result = process_uploaded_photo(source)
        assert isinstance(result, bytes)
        with Image.open(io.BytesIO(result)) as img:
            assert img.format == "JPEG"

    def test_downscales_to_max_dimension(self, tmp_path: Path) -> None:
        source = make_source_image(tmp_path, size=(3000, 2000))
        result = process_uploaded_photo(source)
        with Image.open(io.BytesIO(result)) as img:
            assert max(img.size) <= STORED_MAX_DIMENSION

    def test_preserves_aspect_ratio(self, tmp_path: Path) -> None:
        source = make_source_image(tmp_path, size=(4000, 2000))  # 2:1
        result = process_uploaded_photo(source)
        with Image.open(io.BytesIO(result)) as img:
            width, height = img.size
        assert abs(width / height - 2.0) < 0.02

    def test_small_image_is_not_upscaled(self, tmp_path: Path) -> None:
        source = make_source_image(tmp_path, size=(50, 50))
        result = process_uploaded_photo(source)
        with Image.open(io.BytesIO(result)) as img:
            assert img.size == (50, 50)

    def test_accepts_jpeg_source(self, tmp_path: Path) -> None:
        source = make_source_image(tmp_path, fmt="JPEG", name="foto.jpg")
        result = process_uploaded_photo(source)
        assert isinstance(result, bytes) and len(result) > 0

    def test_handles_rgba_source_without_error(self, tmp_path: Path) -> None:
        path = tmp_path / "foto.png"
        Image.new("RGBA", (200, 200), (0, 255, 0, 128)).save(path)
        result = process_uploaded_photo(path)
        with Image.open(io.BytesIO(result)) as img:
            assert img.mode == "RGB"

    def test_corrects_exif_orientation_from_phone_cameras(self, tmp_path: Path) -> None:
        path = tmp_path / "rotada.jpg"
        raw = Image.new("RGB", (200, 100), "red")  # landscape as stored on disk
        exif = raw.getexif()
        exif[0x0112] = 6  # camera says: rotate 90 CW to display correctly
        raw.save(path, format="JPEG", exif=exif)

        result = process_uploaded_photo(path)
        with Image.open(io.BytesIO(result)) as corrected:
            width, height = corrected.size
        assert height > width  # portrait after correction, not the raw landscape bytes

    def test_rejects_corrupt_file(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "no-es-imagen.png"
        bad_file.write_bytes(b"esto no es una imagen, son bytes cualquiera")
        with pytest.raises(PhotoProcessingError):
            process_uploaded_photo(bad_file)

    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(PhotoProcessingError):
            process_uploaded_photo(tmp_path / "no-existe.png")

    def test_rejects_oversized_file(self, tmp_path: Path) -> None:
        huge = tmp_path / "enorme.png"
        huge.write_bytes(b"0" * (MAX_SOURCE_FILE_BYTES + 1))
        with pytest.raises(PhotoProcessingError):
            process_uploaded_photo(huge)


class TestInitials:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Ana Lopez", "AL"),
            ("Ana Maria Lopez Garcia", "AG"),
            ("Cher", "C"),
            ("  Ana   Lopez  ", "AL"),
            ("", "?"),
        ],
    )
    def test_extracts_initials(self, name: str, expected: str) -> None:
        assert _initials(name) == expected


class TestTkImageHelpers:
    def test_photo_to_tk_image_returns_requested_size(
        self, tmp_path: Path, tk_root: tk.Tk
    ) -> None:
        source = make_source_image(tmp_path, size=(400, 200))
        photo_bytes = process_uploaded_photo(source)
        tk_image = photo_to_tk_image(photo_bytes, (80, 80))
        assert (tk_image.width(), tk_image.height()) == (80, 80)

    def test_placeholder_tk_image_returns_requested_size(self, tk_root: tk.Tk) -> None:
        tk_image = placeholder_tk_image("Ana Lopez", (64, 64))
        assert (tk_image.width(), tk_image.height()) == (64, 64)

    def test_placeholder_color_is_deterministic_for_the_same_name(self) -> None:
        # Same person must always get the same avatar color across app restarts,
        # not a new random one on every render.
        assert _avatar_color("Ana Lopez") == _avatar_color("Ana Lopez")

    def test_placeholder_color_varies_by_name(self) -> None:
        colors = {_avatar_color(name) for name in ["Ana Lopez", "Bruno Diaz", "Carla Ruiz"]}
        assert len(colors) > 1
