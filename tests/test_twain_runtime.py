from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import twain_capture as target


class FakeSource:
    """TWAIN Sourceの主要APIを再現するテストダブル。"""

    def __init__(self, capabilities=None, name="fi-65F") -> None:
        self.capabilities = dict(capabilities or {})
        self.name = name
        self.identity = {"ProductName": name, "ProtocolMajor": 2}
        self.layout = ((0.0, 0.0, 4.0, 6.0), 1, 1, 1)
        self.default_layout = ((0.0, 0.0, 4.0, 6.0), 1, 1, 1)
        self.set_calls = []
        self.closed = False

    def get_capability(self, cap):
        entry = self.capabilities.get(cap)
        if entry is None or entry.get("reject_get"):
            raise RuntimeError("unsupported")
        return entry.get("get", entry.get("current"))

    def get_capability_current(self, cap):
        entry = self.capabilities.get(cap)
        if entry is None or "current" not in entry or entry.get("reject_current"):
            raise RuntimeError("unsupported current")
        return entry["current"]

    def get_capability_default(self, cap):
        entry = self.capabilities.get(cap)
        if entry is None or "default" not in entry or entry.get("reject_default"):
            raise RuntimeError("unsupported default")
        return entry["default"]

    def set_capability(self, cap, item_type, value):
        entry = self.capabilities.get(cap)
        if entry is None or entry.get("reject_set"):
            raise RuntimeError("set rejected")
        self.set_calls.append((cap, item_type, value))
        entry["current"] = (item_type, value)

    def _get_capability(self, cap, message):
        del message
        entry = self.capabilities.get(cap)
        if entry is None or entry.get("reject_query"):
            raise RuntimeError("query rejected")
        return (target.twc.TWTY_UINT32, entry.get("query_support", 0x000F))

    def get_image_layout(self):
        return self.layout

    def get_image_layout_default(self):
        return self.default_layout

    def set_image_layout(self, frame, document_number=1, page_number=1, frame_number=1):
        self.layout = (tuple(frame), document_number, page_number, frame_number)

    def close(self):
        self.closed = True


class FakeManager:
    def __init__(self, names=None, source=None) -> None:
        self.source_list = list(names or ["fi-65F"])
        self.source = source or FakeSource()
        self.opened = None
        self.closed = False

    def open_source(self, name):
        self.opened = name
        return self.source

    def close(self):
        self.closed = True


class FakeTwainImage:
    def __init__(self, image: Image.Image) -> None:
        self.image = image
        self.closed = False

    def save(self, path: str) -> None:
        self.image.save(path, format="BMP")

    def close(self) -> None:
        self.closed = True


def one(value, item_type=None):
    return (item_type or target.twc.TWTY_FIX32, value)


def minimal_capture_caps():
    return {
        target.twc.ICAP_PIXELTYPE: {
            "current": (target.twc.TWTY_UINT16, target.twc.TWPT_RGB)
        },
        target.twc.ICAP_UNITS: {
            "current": (target.twc.TWTY_UINT16, target.twc.TWUN_INCHES)
        },
        target.twc.ICAP_XRESOLUTION: {"current": one(150.0)},
        target.twc.ICAP_YRESOLUTION: {"current": one(150.0)},
    }


def prepare_windows_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    # os.nameを変更するとpathlib.Pathの具象クラス選択も変わるため、先に固定する。
    monkeypatch.setattr(target, "Path", type(Path()))
    monkeypatch.setattr(target.os, "name", "nt")
    monkeypatch.setattr(target.struct, "calcsize", lambda _: 8)
    monkeypatch.setattr(target, "runtime_dependencies_available", lambda: True)


@pytest.mark.parametrize(
    ("text", "expected"),
    [(None, None), ("on", True), ("ON", True), ("off", False), ("OFF", False)],
)
def test_bool_value_normalizes_cli_values(text, expected):
    assert target._bool_value(text) is expected


def test_jsonable_handles_bytes_dict_ctypes_like_and_fallback_iterable():
    assert target.jsonable(b"abc") == "abc"
    assert target.jsonable({"x": (1, 2)}) == {"x": [1, 2]}
    assert target.jsonable(SimpleNamespace(value=7)) == 7
    assert target.jsonable(range(3)) == [0, 1, 2]


def test_capability_name_and_item_type_maps_include_core_constants():
    cap_names = target._capability_name_map()
    type_names = target._item_type_name_map()
    assert cap_names[target.twc.ICAP_BRIGHTNESS] == "ICAP_BRIGHTNESS"
    assert type_names[target.twc.TWTY_FIX32] == "TWTY_FIX32"


def test_build_parser_accepts_twain_specific_camera_controls():
    args = target.build_parser().parse_args(
        [
            "--device",
            "fi-65F",
            "--autobright",
            "off",
            "--exposure-time",
            "2.5",
            "--gamma",
            "1.2",
            "--lamp-state",
            "off",
            "--light-source",
            "3",
            "--bit-depth",
            "8",
        ]
    )
    assert args.device == "fi-65F"
    assert args.autobright == "off"
    assert args.exposure_time == pytest.approx(2.5)
    assert args.gamma == pytest.approx(1.2)
    assert args.lamp_state == "off"
    assert args.light_source == 3
    assert args.bit_depth == 8


def test_create_source_manager_passes_identity_and_optional_dsm(monkeypatch):
    calls = []
    manager = object()

    def factory(**kwargs):
        calls.append(kwargs)
        return manager

    monkeypatch.setattr(target, "twain", SimpleNamespace(SourceManager=factory))
    assert target.create_source_manager("C:/Windows/System32/TWAINDSM.dll") is manager
    assert calls[0]["parent_window"] == 0
    assert calls[0]["ProductName"] == "scanner_camera"
    assert calls[0]["dsm_name"].endswith("TWAINDSM.dll")


def test_create_source_manager_rejects_missing_pytwain(monkeypatch):
    monkeypatch.setattr(target, "twain", None)
    with pytest.raises(RuntimeError, match="pytwain is not installed"):
        target.create_source_manager(None)


def test_source_names_stringifies_manager_entries():
    manager = SimpleNamespace(source_list=["fi-65F", 123])
    assert target.source_names(manager) == ["fi-65F", "123"]


def test_select_source_uses_first_source_when_name_is_omitted():
    manager = FakeManager(["first", "second"])
    source = target.select_source(manager, None)
    assert source is manager.source
    assert manager.opened == "first"


def test_select_source_rejects_no_source_and_missing_match():
    empty = FakeManager([])
    empty.source_list = []
    with pytest.raises(RuntimeError, match="No 64-bit TWAIN source"):
        target.select_source(empty, None)

    manager = FakeManager(["A", "B"])
    with pytest.raises(RuntimeError, match="No TWAIN source matched"):
        target.select_source(manager, "fi-65F")


def test_select_source_rejects_open_failure():
    manager = FakeManager(["fi-65F"])
    manager.open_source = lambda name: None
    with pytest.raises(RuntimeError, match="Could not open TWAIN source"):
        target.select_source(manager, "fi-65F")


def test_list_devices_success_closes_manager(monkeypatch, capsys):
    manager = FakeManager(["fi-65F", "Virtual Scanner"])
    monkeypatch.setattr(target, "create_source_manager", lambda dsm: manager)
    assert target.list_devices(None) == 0
    assert manager.closed is True
    output = capsys.readouterr().out
    assert "[1] fi-65F" in output
    assert "[2] Virtual Scanner" in output


def test_query_support_returns_mask_or_none_on_driver_failure():
    cap = target.twc.ICAP_BRIGHTNESS
    source = FakeSource({cap: {"query_support": 0x000F}})
    assert target.query_support(source, cap) == 0x000F
    source.capabilities[cap]["reject_query"] = True
    assert target.query_support(source, cap) is None


def test_query_support_returns_none_without_private_api():
    assert target.query_support(object(), target.twc.ICAP_BRIGHTNESS) is None


def test_capability_get_normalizes_success_and_exception():
    cap = target.twc.ICAP_GAMMA
    source = FakeSource({cap: {"current": one(1.0)}})
    ok, item_type, payload, error = target.capability_get(
        source, cap, "get_capability_current"
    )
    assert ok is True
    assert item_type == target.twc.TWTY_FIX32
    assert payload == 1.0
    assert error is None

    ok, item_type, payload, error = target.capability_get(
        source, 0x7FFF, "get_capability_current"
    )
    assert ok is False
    assert item_type is None
    assert payload is None
    assert "RuntimeError" in error


def test_capability_report_marks_not_exposed_when_all_reads_fail():
    report = target.capability_report(
        FakeSource(), 0x7FFF, "CUSTOM", probe_writes=False, safe_to_probe=False
    )
    assert report.support == "NOT_EXPOSED_BY_TWAIN"
    assert report.write_probe == "NOT_PROBED_DISABLED"


def test_capability_report_marks_readable_when_probe_is_disabled():
    cap = target.twc.ICAP_GAMMA
    source = FakeSource(
        {cap: {"get": one(1.0), "current": one(1.0), "default": one(1.0)}}
    )
    report = target.capability_report(
        source, cap, "ICAP_GAMMA", probe_writes=False, safe_to_probe=True
    )
    assert report.support == "EXPOSED_READABLE"
    assert report.write_probe == "NOT_PROBED_DISABLED"
    assert source.set_calls == []


def test_capability_report_handles_non_scalar_current_value_without_writing():
    cap = target.twc.ICAP_GAMMA
    source = FakeSource(
        {
            cap: {
                "get": (target.twc.TWTY_FIX32, [0.8, 1.0]),
                "current": (target.twc.TWTY_FIX32, [0.8, 1.0]),
                "default": one(1.0),
            }
        }
    )
    report = target.capability_report(
        source, cap, "ICAP_GAMMA", probe_writes=True, safe_to_probe=True
    )
    assert report.write_probe == "PROBE_NOT_POSSIBLE"
    assert source.set_calls == []


def test_extract_supported_capability_ids_accepts_dict_container():
    cap = target.twc.CAP_SUPPORTEDCAPS
    source = FakeSource(
        {cap: {"get": (target.twc.TWTY_UINT16, {"Items": [9, 3, 9]})}}
    )
    ids, error = target.extract_supported_capability_ids(source)
    assert ids == [3, 9]
    assert error is None


def test_extract_supported_capability_ids_reports_source_and_parse_errors():
    ids, error = target.extract_supported_capability_ids(FakeSource())
    assert ids == []
    assert "CAP_SUPPORTEDCAPS failed" in error

    cap = target.twc.CAP_SUPPORTEDCAPS
    source = FakeSource({cap: {"get": (target.twc.TWTY_UINT16, object())}})
    ids, error = target.extract_supported_capability_ids(source)
    assert ids == []
    assert "Could not parse" in error


def test_inspect_image_layout_reports_get_failure():
    class BrokenLayoutSource:
        def get_image_layout(self):
            raise RuntimeError("layout unavailable")

    report = target.inspect_image_layout(BrokenLayoutSource(), probe_writes=True)
    assert report["exposed"] is False
    assert report["support"] == "NOT_EXPOSED_BY_TWAIN"
    assert "layout unavailable" in report["detail"]


def test_inspect_image_layout_marks_write_rejection():
    class ReadOnlyLayoutSource(FakeSource):
        def set_image_layout(self, *args, **kwargs):
            raise RuntimeError("read only")

    report = target.inspect_image_layout(ReadOnlyLayoutSource(), probe_writes=True)
    assert report["exposed"] is True
    assert report["support"] == "EXPOSED_BUT_WRITE_REJECTED"
    assert "read only" in report["detail"]


def test_inspect_image_layout_without_probe_is_non_destructive():
    source = FakeSource()
    report = target.inspect_image_layout(source, probe_writes=False)
    assert report["support"] == "EXPOSED_WRITABLE_NOT_PROBED"
    assert source.layout == ((0.0, 0.0, 4.0, 6.0), 1, 1, 1)


def test_preferred_item_type_uses_current_then_fallback(monkeypatch):
    cap = target.twc.ICAP_GAMMA
    source = FakeSource({cap: {"current": one(1.0)}})
    assert target.preferred_item_type(source, cap, "TWTY_UINT16") == target.twc.TWTY_FIX32

    source = FakeSource()
    assert target.preferred_item_type(source, cap, "TWTY_UINT16") == target.twc.TWTY_UINT16

    monkeypatch.setattr(target, "_const", lambda name: None)
    with pytest.raises(RuntimeError, match="item type constant"):
        target.preferred_item_type(source, cap, "NO_TYPE")


def test_set_capability_strict_and_non_strict_error_paths(monkeypatch, caplog):
    source = FakeSource()
    with pytest.raises(RuntimeError, match="not exposed"):
        target.set_capability(source, "ICAP_GAMMA", 1.0, True, "TWTY_FIX32")

    target.set_capability(source, "ICAP_GAMMA", 1.0, False, "TWTY_FIX32")
    assert "not exposed" in caplog.text

    original_const = target._const
    monkeypatch.setattr(
        target, "_const", lambda name: None if name == "ICAP_GAMMA" else original_const(name)
    )
    with pytest.raises(RuntimeError, match="unavailable in pytwain constants"):
        target.set_capability(source, "ICAP_GAMMA", 1.0, True, "TWTY_FIX32")


def test_set_capability_write_rejection_is_strict_or_warning(caplog):
    cap = target.twc.ICAP_GAMMA
    source = FakeSource(
        {cap: {"current": one(1.0), "default": one(1.0), "reject_set": True}}
    )
    with pytest.raises(RuntimeError, match="Could not set ICAP_GAMMA"):
        target.set_capability(source, "ICAP_GAMMA", 1.1, True, "TWTY_FIX32")

    target.set_capability(source, "ICAP_GAMMA", 1.1, False, "TWTY_FIX32")
    assert "Could not set ICAP_GAMMA" in caplog.text


def test_apply_scan_settings_applies_camera_specific_values():
    caps = minimal_capture_caps()
    caps.update(
        {
            target.twc.ICAP_BITDEPTH: {"current": (target.twc.TWTY_UINT16, 24)},
            target.twc.ICAP_AUTOBRIGHT: {"current": (target.twc.TWTY_BOOL, True)},
            target.twc.ICAP_EXPOSURETIME: {"current": one(1.0)},
            target.twc.ICAP_BRIGHTNESS: {"current": one(0.0)},
            target.twc.ICAP_CONTRAST: {"current": one(0.0)},
            target.twc.ICAP_GAMMA: {"current": one(1.0)},
            target.twc.ICAP_LAMPSTATE: {"current": (target.twc.TWTY_BOOL, True)},
            target.twc.ICAP_LIGHTSOURCE: {"current": (target.twc.TWTY_UINT16, 0)},
        }
    )
    source = FakeSource(caps)
    target.apply_scan_settings(
        source,
        dpi=600.0,
        mode="color",
        brightness=-128.0,
        contrast=0.0,
        gamma=1.1,
        exposure_time=2.0,
        autobright=False,
        lamp_state=False,
        light_source=1,
        bit_depth=24,
        xpos=None,
        ypos=None,
        width=None,
        height=None,
        strict=True,
    )
    calls = {cap: value for cap, _, value in source.set_calls}
    assert calls[target.twc.ICAP_PIXELTYPE] == target.twc.TWPT_RGB
    assert calls[target.twc.ICAP_XRESOLUTION] == pytest.approx(600.0)
    assert calls[target.twc.ICAP_AUTOBRIGHT] is False
    assert calls[target.twc.ICAP_EXPOSURETIME] == pytest.approx(2.0)
    assert calls[target.twc.ICAP_LAMPSTATE] is False
    assert calls[target.twc.ICAP_LIGHTSOURCE] == 1


def test_apply_scan_settings_non_strict_layout_read_failure(caplog):
    class BrokenLayoutSource(FakeSource):
        def get_image_layout(self):
            raise RuntimeError("layout read failed")

    source = BrokenLayoutSource(minimal_capture_caps())
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
        xpos=1,
        ypos=None,
        width=None,
        height=None,
        strict=False,
    )
    assert "layout read failed" in caplog.text


def test_apply_scan_settings_strict_layout_write_failure():
    class BrokenLayoutSource(FakeSource):
        def set_image_layout(self, *args, **kwargs):
            raise RuntimeError("layout write failed")

    source = BrokenLayoutSource(minimal_capture_caps())
    with pytest.raises(RuntimeError, match="Could not set TWAIN image layout"):
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
            xpos=0,
            ypos=0,
            width=600,
            height=600,
            strict=True,
        )


@pytest.mark.parametrize(
    ("mode", "expected_mode"),
    [("color", "RGB"), ("grayscale", "L"), ("bw", "L")],
)
def test_save_twain_image_as_jpeg_modes_and_quality_clamp(
    tmp_path: Path, mode: str, expected_mode: str
):
    source_image = Image.new("RGB", (10, 6), (20, 100, 220))
    image_object = FakeTwainImage(source_image)
    output = tmp_path / f"{mode}.jpeg"
    target.save_twain_image_as_jpeg(image_object, output, 500, mode, 600.0)
    with Image.open(output) as saved:
        saved.load()
        assert saved.mode == expected_mode
        assert saved.size == (10, 6)
        assert saved.info["dpi"][0] == pytest.approx(600, abs=1)


def test_acquire_one_raises_when_source_returns_no_image(tmp_path: Path):
    class EmptySource:
        def acquire_natively(self, after, show_ui, modal):
            del after, show_ui, modal

    with pytest.raises(RuntimeError, match="without returning an image"):
        target.acquire_one(
            EmptySource(), tmp_path / "missing.jpeg", 95, "color", 600.0, False
        )


def test_acquire_one_saves_only_first_callback_image(tmp_path: Path):
    first = FakeTwainImage(Image.new("RGB", (3, 3), "white"))
    second = FakeTwainImage(Image.new("RGB", (3, 3), "black"))

    class TwoImageSource:
        def acquire_natively(self, after, show_ui, modal):
            del show_ui, modal
            after(first, 0)
            after(second, 0)

    output = tmp_path / "DSC_0001.jpeg"
    target.acquire_one(TwoImageSource(), output, 95, "color", 600.0, False)
    assert output.exists()
    assert first.closed is True
    assert second.closed is True


def test_main_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(target.os, "name", "posix")
    monkeypatch.setattr(sys, "argv", ["twain_capture.py"])
    assert target.main() == 2


def test_main_rejects_32_bit_python(monkeypatch):
    monkeypatch.setattr(target.os, "name", "nt")
    monkeypatch.setattr(target.struct, "calcsize", lambda _: 4)
    monkeypatch.setattr(sys, "argv", ["twain_capture.py"])
    assert target.main() == 2


def test_main_rejects_missing_dependencies(monkeypatch):
    monkeypatch.setattr(target.os, "name", "nt")
    monkeypatch.setattr(target.struct, "calcsize", lambda _: 8)
    monkeypatch.setattr(target, "runtime_dependencies_available", lambda: False)
    monkeypatch.setattr(sys, "argv", ["twain_capture.py"])
    assert target.main() == 2


def test_main_list_devices_flow(monkeypatch):
    prepare_windows_runtime(monkeypatch)
    calls = []
    monkeypatch.setattr(target, "list_devices", lambda dsm: calls.append(dsm) or 0)
    monkeypatch.setattr(
        sys,
        "argv",
        ["twain_capture.py", "--list-devices", "--dsm", "custom-dsm.dll"],
    )
    assert target.main() == 0
    assert calls == ["custom-dsm.dll"]


def test_main_diagnostic_flow_closes_source_and_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    prepare_windows_runtime(monkeypatch)
    source = FakeSource(name="PaperStream fi-65F")
    manager = FakeManager([source.name], source)
    monkeypatch.setattr(target, "create_source_manager", lambda dsm: manager)
    monkeypatch.setattr(target, "select_source", lambda mgr, name: source)
    outputs = (tmp_path / "report.json", tmp_path / "report.txt")
    monkeypatch.setattr(target, "write_diagnostic_report", lambda *args: outputs)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "twain_capture.py",
            "--diagnose",
            "--device",
            "fi-65F",
            "--diagnostic-dir",
            str(tmp_path),
            "--no-probe-writes",
        ],
    )
    assert target.main() == 0
    assert source.closed is True
    assert manager.closed is True
    output = capsys.readouterr().out
    assert "report.json" in output
    assert "report.txt" in output


def test_main_capture_flow_passes_settings_and_uses_sequential_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    prepare_windows_runtime(monkeypatch)
    source = FakeSource()
    manager = FakeManager(["fi-65F"], source)
    monkeypatch.setattr(target, "create_source_manager", lambda dsm: manager)
    monkeypatch.setattr(target, "select_source", lambda mgr, name: source)
    settings = []
    captures = []

    def fake_apply(selected, **kwargs):
        settings.append((selected, kwargs))

    def fake_acquire(selected, output, quality, mode, dpi, show_ui):
        output.write_bytes(b"jpeg")
        captures.append((selected, output, quality, mode, dpi, show_ui))

    monkeypatch.setattr(target, "apply_scan_settings", fake_apply)
    monkeypatch.setattr(target, "acquire_one", fake_acquire)
    output_dir = tmp_path / "jpeg"
    output_dir.mkdir()
    (output_dir / "DSC_0007.jpeg").write_bytes(b"old")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "twain_capture.py",
            "--device",
            "fi-65F",
            "--output-dir",
            str(output_dir),
            "--dpi",
            "600",
            "--mode",
            "color",
            "--brightness",
            "-128",
            "--contrast",
            "0",
            "--autobright",
            "off",
            "--lamp-state",
            "off",
            "--exposure-time",
            "2.5",
            "--gamma",
            "1.1",
        ],
    )
    assert target.main() == 0
    assert (output_dir / "DSC_0008.jpeg").read_bytes() == b"jpeg"
    kwargs = settings[0][1]
    assert kwargs["dpi"] == pytest.approx(600.0)
    assert kwargs["brightness"] == pytest.approx(-128.0)
    assert kwargs["autobright"] is False
    assert kwargs["lamp_state"] is False
    assert kwargs["exposure_time"] == pytest.approx(2.5)
    assert captures[0][2:] == (95, "color", 600.0, False)
    assert source.closed is True
    assert manager.closed is True


def test_main_capture_failure_removes_empty_reservation_and_closes_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    prepare_windows_runtime(monkeypatch)
    source = FakeSource()
    manager = FakeManager(["fi-65F"], source)
    monkeypatch.setattr(target, "create_source_manager", lambda dsm: manager)
    monkeypatch.setattr(target, "select_source", lambda mgr, name: source)
    monkeypatch.setattr(target, "apply_scan_settings", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        target,
        "acquire_one",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("transfer failed")),
    )
    output_dir = tmp_path / "jpeg"
    monkeypatch.setattr(
        sys,
        "argv",
        ["twain_capture.py", "--output-dir", str(output_dir)],
    )
    assert target.main() == 1
    assert list(output_dir.glob("DSC_*.jpeg")) == []
    assert source.closed is True
    assert manager.closed is True


def test_diagnostic_report_contains_environment_targets_and_all_caps(tmp_path: Path):
    targets = target.build_target_capabilities()
    supported = [targets["brightness"], targets["gamma"]]
    source = FakeSource(
        {
            target.twc.CAP_SUPPORTEDCAPS: {
                "get": (target.twc.TWTY_UINT16, supported),
                "current": (target.twc.TWTY_UINT16, supported[0]),
                "default": (target.twc.TWTY_UINT16, supported[0]),
            },
            targets["brightness"]: {
                "get": one({"MinValue": -1000.0, "MaxValue": 1000.0, "CurrentValue": 0.0}),
                "current": one(0.0),
                "default": one(0.0),
            },
            targets["gamma"]: {
                "get": one({"MinValue": 0.1, "MaxValue": 4.0, "CurrentValue": 1.0}),
                "current": one(1.0),
                "default": one(1.0),
            },
        }
    )
    json_path, text_path = target.write_diagnostic_report(
        source, "fi-65F", tmp_path, probe_writes=False, dsm_name="TWAINDSM.dll"
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["environment"]["python_bitness"] in {32, 64}
    assert data["environment"]["dsm_name"] == "TWAINDSM.dll"
    assert data["source"]["name"] == "fi-65F"
    assert targets["brightness"] in data["supported_capability_ids"]
    by_setting = {item["setting"]: item for item in data["target_support"]}
    assert by_setting["brightness"]["exposed"] is True
    assert "All capabilities reported/probed" in text_path.read_text(encoding="utf-8")
