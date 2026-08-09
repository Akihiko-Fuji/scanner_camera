from __future__ import annotations

import argparse
import configparser
import sys
from pathlib import Path

import pytest
from PIL import Image

import scanner_capture as wia
import twain_capture as twain


def _probe_args(probe=False, no_probe=False):
    return argparse.Namespace(probe_writes=probe, no_probe_writes=no_probe)


def test_diagnostic_write_probe_is_off_by_default_and_explicitly_opt_in():
    config = configparser.ConfigParser()
    assert wia.resolve_probe_writes(_probe_args(), config) is False
    assert wia.resolve_probe_writes(_probe_args(probe=True), config) is True

    config.read_dict({"diagnostics": {"probe_writes": "true"}})
    assert wia.resolve_probe_writes(_probe_args(), config) is True
    assert wia.resolve_probe_writes(_probe_args(no_probe=True), config) is False


def test_diagnostic_write_probe_rejects_conflicting_cli_switches():
    config = configparser.ConfigParser()
    with pytest.raises(ValueError, match="cannot be used together"):
        wia.resolve_probe_writes(_probe_args(probe=True, no_probe=True), config)


def test_twain_boolean_parser_rejects_typo():
    assert twain._bool_value("ON") is True
    assert twain._bool_value("off") is False
    assert twain._bool_value(None) is None
    with pytest.raises(ValueError, match="Expected 'on' or 'off'"):
        twain._bool_value("falsee")


def test_twain_auto_dsm_description_reflects_process_bitness(monkeypatch):
    monkeypatch.setattr(twain.struct, "calcsize", lambda _: 4)
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    assert twain.automatic_dsm_description() == (
        r"auto:C:\Windows\twain_32.dll (TWAIN 1)"
    )

    monkeypatch.setattr(twain.struct, "calcsize", lambda _: 8)
    assert twain.automatic_dsm_description() == "auto:twaindsm.dll"


def test_twain_strict_setting_fails_when_post_set_readback_fails():
    cap = twain.twc.ICAP_GAMMA

    class Source:
        def __init__(self):
            self.read_count = 0

        def get_capability_current(self, requested_cap):
            assert requested_cap == cap
            self.read_count += 1
            if self.read_count == 1:
                return (twain.twc.TWTY_FIX32, 1.0)
            raise RuntimeError("readback unavailable")

        def set_capability(self, requested_cap, item_type, value):
            assert requested_cap == cap
            assert item_type == twain.twc.TWTY_FIX32
            assert value == pytest.approx(1.1)

    with pytest.raises(RuntimeError, match="GETCURRENT failed"):
        twain.set_capability(Source(), "ICAP_GAMMA", 1.1, True, "TWTY_FIX32")


def test_twain_non_strict_uses_adjusted_dpi_for_pixel_region(caplog):
    caps = {
        twain.twc.ICAP_PIXELTYPE: (twain.twc.TWTY_UINT16, twain.twc.TWPT_RGB),
        twain.twc.ICAP_UNITS: (twain.twc.TWTY_UINT16, twain.twc.TWUN_INCHES),
        twain.twc.ICAP_XRESOLUTION: (twain.twc.TWTY_FIX32, 150.0),
        twain.twc.ICAP_YRESOLUTION: (twain.twc.TWTY_FIX32, 150.0),
    }

    class AdjustingSource:
        def __init__(self):
            self.current = dict(caps)
            self.layout = ((0.0, 0.0, 4.0, 6.0), 1, 1, 1)

        def get_capability_current(self, cap):
            return self.current[cap]

        def set_capability(self, cap, item_type, value):
            if cap in {twain.twc.ICAP_XRESOLUTION, twain.twc.ICAP_YRESOLUTION}:
                value = 300.0
            self.current[cap] = (item_type, value)

        def get_image_layout(self):
            return self.layout

        def set_image_layout(
            self, frame, document_number=1, page_number=1, frame_number=1
        ):
            self.layout = (tuple(frame), document_number, page_number, frame_number)

    source = AdjustingSource()
    actual_x, actual_y = twain.apply_scan_settings(
        source,
        dpi=600.0,
        mode="color",
        brightness=None,
        contrast=None,
        gamma=None,
        exposure_time=None,
        autobright=None,
        lamp_state=None,
        light_source=None,
        bit_depth=None,
        xpos=60,
        ypos=120,
        width=600,
        height=1200,
        strict=False,
    )

    assert actual_x == pytest.approx(300.0)
    assert actual_y == pytest.approx(300.0)
    assert source.layout[0] == pytest.approx((0.2, 0.4, 2.2, 4.4))
    assert "read back 300.0" in caplog.text


class _TwainImage:
    def __init__(self, image: Image.Image):
        self.image = image
        self.closed = False

    def save(self, path: str):
        self.image.save(path, format="BMP")

    def close(self):
        self.closed = True


def test_twain_transfer_uses_dat_imageinfo_resolution_for_jpeg(tmp_path: Path):
    image_object = _TwainImage(Image.new("RGB", (8, 6), "white"))

    class Source:
        def acquire_natively(self, after, before, show_ui, modal):
            assert show_ui is False
            assert modal is False
            before({"XResolution": 300.0, "YResolution": 200.0})
            after(image_object, 0)

    output = tmp_path / "DSC_0001.jpeg"
    output.touch()
    twain.acquire_one(Source(), output, 95, "color", 600.0, False)

    with Image.open(output) as saved:
        saved.load()
        assert saved.info["dpi"][0] == pytest.approx(300, abs=1)
        assert saved.info["dpi"][1] == pytest.approx(200, abs=1)
    assert image_object.closed is True


def test_atomic_jpeg_replaces_reservation_and_leaves_no_temp_file(tmp_path: Path):
    output = tmp_path / "DSC_0001.jpeg"
    output.touch()
    image = Image.new("RGB", (10, 10), "white")
    try:
        wia.save_pillow_jpeg_atomically(image, output, 95, dpi=(300.0, 300.0))
    finally:
        image.close()

    assert output.stat().st_size > 0
    with Image.open(output) as saved:
        saved.verify()
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_atomic_jpeg_failure_preserves_empty_reservation_and_cleans_temp(tmp_path: Path):
    output = tmp_path / "DSC_0001.jpeg"
    output.touch()

    class BrokenImage:
        def save(self, path, **kwargs):
            del kwargs
            Path(path).write_bytes(b"partial")
            raise RuntimeError("encoder failed")

    with pytest.raises(RuntimeError, match="encoder failed"):
        wia.save_pillow_jpeg_atomically(BrokenImage(), output, 95)

    assert output.exists()
    assert output.stat().st_size == 0
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_wia_main_releases_scoped_com_objects_before_couninitialize(monkeypatch):
    events = []

    class PythonCom:
        def CoInitialize(self):
            events.append("init")

        def CoUninitialize(self):
            events.append("uninit")

    # Freeze the concrete Path implementation before simulating Windows.
    monkeypatch.setattr(wia, "Path", type(Path()))
    monkeypatch.setattr(wia.os, "name", "nt")
    monkeypatch.setattr(wia, "runtime_dependencies_available", lambda: True)
    monkeypatch.setattr(wia, "pythoncom", PythonCom())
    monkeypatch.setattr(wia.gc, "collect", lambda: events.append("gc") or 0)
    monkeypatch.setattr(wia, "_run_wia_command", lambda args, config: events.append("run") or 0)
    monkeypatch.setattr(sys, "argv", ["scanner_capture.py"])

    assert wia.main() == 0
    assert events == ["init", "run", "gc", "uninit"]
