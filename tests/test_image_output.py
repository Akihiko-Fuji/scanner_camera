from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import scanner_capture as target


@pytest.mark.parametrize(
    ("mode", "expected_mode"),
    [("color", "RGB"), ("grayscale", "L"), ("bw", "L")],
)
def test_save_transfer_as_jpeg_creates_expected_image_mode(
    tmp_path: Path, fake_image_file_cls, mode: str, expected_mode: str
) -> None:
    source = Image.new("RGB", (8, 6), (120, 180, 220))
    output = tmp_path / f"{mode}.jpeg"

    target.save_transfer_as_jpeg(
        fake_image_file_cls(source), output, quality=95, mode=mode
    )

    assert output.exists()
    with Image.open(output) as saved:
        assert saved.format == "JPEG"
        assert saved.size == (8, 6)
        assert saved.mode == expected_mode


@pytest.mark.parametrize("quality", [-100, 0, 1, 100, 101, 500])
def test_save_transfer_as_jpeg_clamps_quality(
    tmp_path: Path, fake_image_file_cls, quality: int
) -> None:
    source = Image.new("RGB", (4, 4), "white")
    output = tmp_path / f"quality_{quality}.jpeg"

    target.save_transfer_as_jpeg(
        fake_image_file_cls(source), output, quality=quality, mode="color"
    )

    with Image.open(output) as saved:
        saved.load()
        assert saved.format == "JPEG"


def test_save_transfer_as_jpeg_applies_bw_threshold(
    tmp_path: Path, fake_image_file_cls
) -> None:
    source = Image.new("L", (2, 1))
    source.putdata([64, 192])
    output = tmp_path / "bw.jpeg"

    target.save_transfer_as_jpeg(
        fake_image_file_cls(source), output, quality=100, mode="bw"
    )

    with Image.open(output) as saved:
        grayscale = saved.convert("L")
        values = [grayscale.getpixel((0, 0)), grayscale.getpixel((1, 0))]
    assert values[0] < 20
    assert values[1] > 235
