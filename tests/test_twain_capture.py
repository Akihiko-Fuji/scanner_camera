from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import twain_capture as target


class FakeSource:
    """TWAIN Data Sourceの必要部分だけを再現するテストダブル。"""

    def __init__(self, capabilities=None):
        self.capabilities = dict(capabilities or {})
        self.set_calls = []
        self.layout = ((0.0, 0.0, 4.0, 6.0), 1, 1, 1)
        self.default_layout = ((0.0, 0.0, 4.0, 6.0), 1, 1, 1)
        self.identity = {"ProductName": "fi-65F", "ProtocolMajor": 2}
        self.name = "fi-65F"

    def get_capability(self, cap):
        entry = self.capabilities.get(cap)
        if entry is None:
            raise RuntimeError("unsupported")
        return entry.get("get", entry.get("current"))

    def get_capability_current(self, cap):
        entry = self.capabilities.get(cap)
        if entry is None or "current" not in entry:
            raise RuntimeError("unsupported")
        return entry["current"]

    def get_capability_default(self, cap):
        entry = self.capabilities.get(cap)
        if entry is None or "default" not in entry:
            raise RuntimeError("unsupported")
        return entry["default"]

    def set_capability(self, cap, item_type, value):
        entry = self.capabilities.get(cap)
        if entry is None:
            raise RuntimeError("unsupported")
        if entry.get("reject_set"):
            raise RuntimeError("set rejected")
        self.set_calls.append((cap, item_type, value))
        entry["current"] = (item_type, value)

    def _get_capability(self, cap, message):
        del message
        entry = self.capabilities.get(cap)
        if entry is None:
            raise RuntimeError("unsupported")
        return (target.twc.TWTY_UINT32, entry.get("query_support", 0x000F))

    def get_image_layout(self):
        return self.layout

    def get_image_layout_default(self):
        return self.default_layout

    def set_image_layout(self, frame, document_number=1, page_number=1, frame_number=1):
        self.layout = (tuple(frame), document_number, page_number, frame_number)


class FakeManager:
    def __init__(self, names, source=None):
        self.source_list = names
        self.source = source or FakeSource()
        self.opened = None
        self.closed = False

    def open_source(self, name):
        self.opened = name
        return self.source

    def close(self):
        self.closed = True


class FakeTwainImage:
    def __init__(self, image: Image.Image):
        self.image = image
        self.closed = False

    def save(self, path: str):
        self.image.save(path, format="BMP")

    def close(self):
        self.closed = True


def one_value(value, item_type=None):
    return (item_type or target.twc.TWTY_FIX32, value)


def test_split_capability_result_accepts_pytwain_and_legacy_range():
    assert target.split_capability_result((7, 600.0)) == (7, 600.0)
    legacy = {"MinValue": 75, "MaxValue": 600, "CurrentValue": 150}
    assert target.split_capability_result(legacy) == (None, legacy)


def test_current_scalar_handles_range_enumeration_and_single_value():
    assert target.current_scalar({"CurrentValue": 150}) == 150
    assert target.current_scalar((1, 0, [100, 200, 300])) == 200
    assert target.current_scalar([42]) == 42
    assert target.current_scalar(12.5) == 12.5
    assert target.current_scalar([1, 2]) is None


def test_target_capabilities_include_camera_relevant_twain_controls():
    caps = target.build_target_capabilities()
    assert caps["brightness"] == target.twc.ICAP_BRIGHTNESS
    assert caps["exposure_time"] == target.twc.ICAP_EXPOSURETIME
    assert caps["gamma"] == target.twc.ICAP_GAMMA
    assert caps["lamp_state"] == target.twc.ICAP_LAMPSTATE
    assert caps["light_source"] == target.twc.ICAP_LIGHTSOURCE


def test_extract_supported_capability_ids_uses_cap_supportedcaps():
    source = FakeSource(
        {
            target.twc.CAP_SUPPORTEDCAPS: {
                "get": (
                    target.twc.TWTY_UINT16,
                    [target.twc.ICAP_BRIGHTNESS, target.twc.ICAP_GAMMA],
                )
            }
        }
    )
    ids, error = target.extract_supported_capability_ids(source)
    assert error is None
    assert ids == sorted([target.twc.ICAP_BRIGHTNESS, target.twc.ICAP_GAMMA])


def test_capability_report_performs_no_change_write_probe():
    cap = target.twc.ICAP_BRIGHTNESS
    source = FakeSource(
        {
            cap: {
                "get": (
                    target.twc.TWTY_FIX32,
                    {
                        "MinValue": -1000.0,
                        "MaxValue": 1000.0,
                        "CurrentValue": -128.0,
                    },
                ),
                "current": one_value(-128.0),
                "default": one_value(0.0),
            }
        }
    )
    report = target.capability_report(
        source, cap, "ICAP_BRIGHTNESS", probe_writes=True, safe_to_probe=True
    )
    assert report.support == "EXPOSED_AND_SETTABLE"
    assert report.write_probe == "WRITE_PROBE_OK"
    assert source.set_calls == [(cap, target.twc.TWTY_FIX32, -128.0)]


def test_capability_report_marks_rejected_write():
    cap = target.twc.ICAP_LAMPSTATE
    source = FakeSource(
        {
            cap: {
                "get": (target.twc.TWTY_BOOL, [False, True]),
                "current": (target.twc.TWTY_BOOL, True),
                "default": (target.twc.TWTY_BOOL, True),
                "reject_set": True,
            }
        }
    )
    report = target.capability_report(
        source, cap, "ICAP_LAMPSTATE", probe_writes=True, safe_to_probe=True
    )
    assert report.support == "EXPOSED_BUT_WRITE_REJECTED"
    assert "set rejected" in (report.detail or "")


def test_capability_report_does_not_write_non_target_capability():
    cap = target.twc.CAP_SUPPORTEDCAPS
    source = FakeSource(
        {
            cap: {
                "get": (target.twc.TWTY_UINT16, [cap]),
                "current": (target.twc.TWTY_UINT16, cap),
                "default": (target.twc.TWTY_UINT16, cap),
            }
        }
    )
    report = target.capability_report(
        source, cap, "CAP_SUPPORTEDCAPS", probe_writes=True, safe_to_probe=False
    )
    assert report.write_probe == "NOT_PROBED_NON_TARGET"
    assert source.set_calls == []


def test_select_source_uses_case_insensitive_substring():
    manager = FakeManager(["PaperStream fi-65F", "Virtual Scanner"])
    source = target.select_source(manager, "FI-65f")
    assert source is manager.source
    assert manager.opened == "PaperStream fi-65F"


def test_select_source_rejects_ambiguous_name():
    manager = FakeManager(["fi-65F TWAIN", "fi-65F test"])
    with pytest.raises(RuntimeError, match="ambiguous"):
        target.select_source(manager, "fi-65F")


def test_set_capability_uses_source_current_item_type():
    cap = target.twc.ICAP_BRIGHTNESS
    source = FakeSource(
        {cap: {"current": (target.twc.TWTY_FIX32, 0.0), "default": one_value(0.0)}}
    )
    target.set_capability(source, "ICAP_BRIGHTNESS", -250.5, True, "TWTY_FIX32")
    assert source.set_calls[-1] == (cap, target.twc.TWTY_FIX32, -250.5)


def test_set_capability_non_strict_ignores_unsupported(caplog):
    source = FakeSource()
    target.set_capability(source, "ICAP_GAMMA", 1.0, False, "TWTY_FIX32")
    assert "not exposed" in caplog.text


def test_apply_scan_settings_maps_pixel_region_to_inches():
    caps = {
        target.twc.ICAP_PIXELTYPE: {"current": (target.twc.TWTY_UINT16, target.twc.TWPT_RGB)},
        target.twc.ICAP_UNITS: {"current": (target.twc.TWTY_UINT16, target.twc.TWUN_INCHES)},
        target.twc.ICAP_XRESOLUTION: {"current": one_value(150.0)},
        target.twc.ICAP_YRESOLUTION: {"current": one_value(150.0)},
    }
    source = FakeSource(caps)
    target.apply_scan_settings(
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
        strict=True,
    )
    frame = source.layout[0]
    assert frame == pytest.approx((0.1, 0.2, 1.1, 2.2))


def test_inspect_image_layout_probes_current_layout_without_changing_it():
    source = FakeSource()
    report = target.inspect_image_layout(source, probe_writes=True)
    assert report["support"] == "EXPOSED_AND_SETTABLE"
    assert source.layout == ((0.0, 0.0, 4.0, 6.0), 1, 1, 1)


def test_save_twain_image_as_jpeg_preserves_expected_mode_and_dpi(tmp_path: Path):
    source_image = Image.new("RGB", (12, 8), (100, 150, 200))
    twain_image = FakeTwainImage(source_image)
    output = tmp_path / "out.jpeg"
    target.save_twain_image_as_jpeg(twain_image, output, 93, "color", 600.0)
    with Image.open(output) as saved:
        saved.load()
        assert saved.format == "JPEG"
        assert saved.mode == "RGB"
        assert saved.size == (12, 8)
        assert saved.info["dpi"][0] == pytest.approx(600, abs=1)


def test_acquire_one_saves_first_image_and_closes_twain_object(tmp_path: Path):
    image_object = FakeTwainImage(Image.new("RGB", (4, 4), "white"))

    class AcquiringSource:
        def acquire_natively(self, after, show_ui, modal):
            assert show_ui is False
            assert modal is False
            after(image_object, 0)

    output = tmp_path / "DSC_0001.jpeg"
    target.acquire_one(AcquiringSource(), output, 90, "color", 300.0, False)
    assert output.exists()
    assert image_object.closed is True


def test_write_diagnostic_report_includes_lamp_and_exposure_targets(tmp_path: Path):
    caps = target.build_target_capabilities()
    supported = [caps["lamp_state"], caps["exposure_time"]]
    source_caps = {
        target.twc.CAP_SUPPORTEDCAPS: {
            "get": (target.twc.TWTY_UINT16, supported),
            "current": (target.twc.TWTY_UINT16, supported[0]),
            "default": (target.twc.TWTY_UINT16, supported[0]),
        },
        caps["lamp_state"]: {
            "get": (target.twc.TWTY_BOOL, [False, True]),
            "current": (target.twc.TWTY_BOOL, True),
            "default": (target.twc.TWTY_BOOL, True),
        },
        caps["exposure_time"]: {
            "get": (target.twc.TWTY_FIX32, {"MinValue": 0.0, "MaxValue": 10.0, "CurrentValue": 1.0}),
            "current": (target.twc.TWTY_FIX32, 1.0),
            "default": (target.twc.TWTY_FIX32, 1.0),
        },
    }
    source = FakeSource(source_caps)
    json_path, text_path = target.write_diagnostic_report(
        source, "fi-65F", tmp_path, probe_writes=False, dsm_name=None
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    by_setting = {item["setting"]: item for item in data["target_support"]}
    assert by_setting["lamp_state"]["exposed"] is True
    assert by_setting["exposure_time"]["exposed"] is True
    assert "lamp_state" in text_path.read_text(encoding="utf-8")
