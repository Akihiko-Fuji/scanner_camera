from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import twain_capture as target


class ReadbackAdjustingSource:
    """MSG_SETは受理するが、GETCURRENTで別値を返すSource。"""

    def __init__(self, readback: float) -> None:
        self.readback = readback
        self.set_calls = []

    def get_capability_current(self, capability_id):
        assert capability_id == target.twc.ICAP_BRIGHTNESS
        return (target.twc.TWTY_FIX32, self.readback)

    def set_capability(self, capability_id, item_type, value):
        self.set_calls.append((capability_id, item_type, value))
        # Source側がSET要求値を無視・丸めた状況を模擬するためreadbackは変更しない。


class FakeTwainImage:
    def __init__(self, image: Image.Image) -> None:
        self.image = image

    def save(self, path: str) -> None:
        self.image.save(path, format="BMP")


def test_set_capability_strict_rejects_different_readback() -> None:
    source = ReadbackAdjustingSource(readback=0.0)

    with pytest.raises(RuntimeError, match="read back"):
        target.set_capability(
            source,
            "ICAP_BRIGHTNESS",
            requested=100.0,
            strict=True,
            fallback_type="TWTY_FIX32",
        )

    assert source.set_calls == [
        (target.twc.ICAP_BRIGHTNESS, target.twc.TWTY_FIX32, 100.0)
    ]


def test_set_capability_non_strict_warns_on_different_readback(caplog) -> None:
    source = ReadbackAdjustingSource(readback=0.0)

    target.set_capability(
        source,
        "ICAP_BRIGHTNESS",
        requested=100.0,
        strict=False,
        fallback_type="TWTY_FIX32",
    )

    assert "read back" in caplog.text


def test_fix32_one_lsb_rounding_is_accepted_in_strict_mode() -> None:
    requested = 1.0
    source = ReadbackAdjustingSource(readback=requested + (1.0 / 65536.0))

    target.set_capability(
        source,
        "ICAP_BRIGHTNESS",
        requested=requested,
        strict=True,
        fallback_type="TWTY_FIX32",
    )


def test_save_twain_image_as_jpeg_applies_bw_threshold(tmp_path: Path) -> None:
    source = Image.new("RGB", (2, 1))
    source.putdata([(64, 64, 64), (192, 192, 192)])
    output = tmp_path / "bw.jpeg"

    target.save_twain_image_as_jpeg(
        FakeTwainImage(source),
        output,
        quality=100,
        mode="bw",
        dpi=600.0,
    )

    with Image.open(output) as saved:
        saved.load()
        assert saved.mode == "L"
        values = [saved.getpixel((0, 0)), saved.getpixel((1, 0))]

    assert values[0] < 20
    assert values[1] > 235
