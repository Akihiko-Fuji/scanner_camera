from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scanner_capture as target


class FakePythonCom:
    def __init__(self) -> None:
        self.initialize_calls = 0
        self.uninitialize_calls = 0

    def CoInitialize(self) -> None:
        self.initialize_calls += 1

    def CoUninitialize(self) -> None:
        self.uninitialize_calls += 1


class FakeDialog:
    def __init__(self, image_file) -> None:
        self.image_file = image_file
        self.calls = []

    def ShowTransfer(self, item, image_format, show_ui):
        self.calls.append((item, image_format, show_ui))
        return self.image_file


def prepare_windows_runtime(monkeypatch):
    fake_pythoncom = FakePythonCom()
    # pathlib.Path selects its concrete class from os.name at construction time.
    # Freeze the host concrete class before simulating Windows on non-Windows CI.
    monkeypatch.setattr(target, "Path", type(Path()))
    monkeypatch.setattr(target.os, "name", "nt")
    monkeypatch.setattr(target.struct, "calcsize", lambda _: 8)
    monkeypatch.setattr(target, "runtime_dependencies_available", lambda: True)
    monkeypatch.setattr(target, "pythoncom", fake_pythoncom)
    return fake_pythoncom


def test_main_rejects_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(target.os, "name", "posix")
    monkeypatch.setattr(sys, "argv", ["scanner_capture.py"])
    assert target.main() == 2


def test_main_rejects_32_bit_python(monkeypatch) -> None:
    monkeypatch.setattr(target.os, "name", "nt")
    monkeypatch.setattr(target.struct, "calcsize", lambda _: 4)
    monkeypatch.setattr(sys, "argv", ["scanner_capture.py"])
    assert target.main() == 2


def test_main_rejects_missing_runtime_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(target.os, "name", "nt")
    monkeypatch.setattr(target.struct, "calcsize", lambda _: 8)
    monkeypatch.setattr(target, "runtime_dependencies_available", lambda: False)
    monkeypatch.setattr(sys, "argv", ["scanner_capture.py"])
    assert target.main() == 2


def test_main_diagnostic_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fake_pythoncom = prepare_windows_runtime(monkeypatch)
    info, device, item = object(), object(), object()
    monkeypatch.setattr(target, "select_device", lambda name: (info, device))
    monkeypatch.setattr(target, "get_scan_item", lambda selected: item)
    outputs = (tmp_path / "report.json", tmp_path / "report.txt")
    monkeypatch.setattr(target, "write_diagnostic_report", lambda *args: outputs)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scanner_capture.py",
            "--diagnose",
            "--device",
            "fi-65F",
            "--diagnostic-dir",
            str(tmp_path),
        ],
    )

    result = target.main()

    assert result == 0
    assert fake_pythoncom.initialize_calls == 1
    assert fake_pythoncom.uninitialize_calls == 1
    output = capsys.readouterr().out
    assert "report.json" in output
    assert "report.txt" in output


def test_main_capture_flow_reserves_and_saves_sequential_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pythoncom = prepare_windows_runtime(monkeypatch)
    info, device, item = object(), object(), object()
    image_file = object()
    dialog = FakeDialog(image_file)
    set_calls = []
    save_calls = []

    monkeypatch.setattr(target, "select_device", lambda name: (info, device))
    monkeypatch.setattr(target, "get_scan_item", lambda selected: item)
    monkeypatch.setattr(
        target,
        "set_property",
        lambda selected, property_id, requested, strict: set_calls.append(
            (property_id, requested, strict)
        ),
    )
    monkeypatch.setattr(
        target,
        "save_transfer_as_jpeg",
        lambda transferred, output, quality, mode: (
            output.write_bytes(b"jpeg"),
            save_calls.append((transferred, output, quality, mode)),
        ),
    )
    monkeypatch.setattr(
        target,
        "win32com",
        SimpleNamespace(client=SimpleNamespace(Dispatch=lambda name: dialog)),
    )
    output_dir = tmp_path / "jpeg"
    output_dir.mkdir()
    (output_dir / "DSC_0003.jpeg").write_bytes(b"old")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scanner_capture.py",
            "--device",
            "fi-65F",
            "--output-dir",
            str(output_dir),
            "--dpi",
            "600",
            "--mode",
            "color",
            "--brightness",
            "100",
            "--contrast",
            "0",
        ],
    )

    result = target.main()

    assert result == 0
    assert (output_dir / "DSC_0004.jpeg").read_bytes() == b"jpeg"
    assert save_calls[0][0] is image_file
    assert save_calls[0][2:] == (95, "color")
    assert set_calls[0][0] == target.WIA_IPS_CUR_INTENT
    assert fake_pythoncom.uninitialize_calls == 1
    assert dialog.calls == [(item, target.WIA_FORMAT_BMP, False)]


def test_main_removes_empty_reservation_on_transfer_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepare_windows_runtime(monkeypatch)
    item = object()
    dialog = FakeDialog(None)
    monkeypatch.setattr(target, "select_device", lambda name: (object(), object()))
    monkeypatch.setattr(target, "get_scan_item", lambda selected: item)
    monkeypatch.setattr(target, "set_property", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        target,
        "win32com",
        SimpleNamespace(client=SimpleNamespace(Dispatch=lambda name: dialog)),
    )
    output_dir = tmp_path / "jpeg"
    monkeypatch.setattr(
        sys,
        "argv",
        ["scanner_capture.py", "--output-dir", str(output_dir)],
    )

    result = target.main()

    assert result == 1
    assert list(output_dir.glob("DSC_*.jpeg")) == []
