from __future__ import annotations

import json
from pathlib import Path

import pytest

import scanner_capture as target


def test_scanner_name_prefers_name_property(fake_info_cls) -> None:
    info = fake_info_cls("fi-65F", "id-65f")
    assert target.scanner_name(info) == "fi-65F"


def test_list_devices_prints_devices(monkeypatch, capsys, fake_info_cls) -> None:
    infos = [fake_info_cls("fi-65F", "id-1"), fake_info_cls("Other", "id-2")]
    monkeypatch.setattr(target, "scanner_infos", lambda: infos)

    result = target.list_devices()

    captured = capsys.readouterr()
    assert result == 0
    assert "[1] fi-65F" in captured.out
    assert "DeviceID: id-2" in captured.out


def test_list_devices_returns_one_when_empty(monkeypatch, capsys) -> None:
    monkeypatch.setattr(target, "scanner_infos", lambda: [])
    assert target.list_devices() == 1
    assert "No WIA scanner" in capsys.readouterr().err


def test_select_device_uses_case_insensitive_unique_match(
    monkeypatch, fake_info_cls, fake_device_cls
) -> None:
    device = fake_device_cls([])
    info = fake_info_cls("FUJITSU fi-65F", connected=device)
    monkeypatch.setattr(
        target,
        "scanner_infos",
        lambda: [fake_info_cls("Other"), info],
    )

    selected_info, selected_device = target.select_device("Fi-65f")

    assert selected_info is info
    assert selected_device is device
    assert info.connect_count == 1


def test_select_device_reports_no_match_and_ambiguity(monkeypatch, fake_info_cls) -> None:
    monkeypatch.setattr(
        target,
        "scanner_infos",
        lambda: [fake_info_cls("fi-65F A"), fake_info_cls("fi-65F B")],
    )

    with pytest.raises(RuntimeError, match="No scanner matched"):
        target.select_device("unknown")
    with pytest.raises(RuntimeError, match="ambiguous"):
        target.select_device("fi-65F")


def test_get_scan_item_returns_first_item(fake_device_cls) -> None:
    first = object()
    assert target.get_scan_item(fake_device_cls([first])) is first


def test_get_scan_item_rejects_empty_device(fake_device_cls) -> None:
    with pytest.raises(RuntimeError, match="no transferable"):
        target.get_scan_item(fake_device_cls([]))


def test_write_diagnostic_report_saves_json_and_text(
    tmp_path: Path, fake_property_cls, fake_item_cls, fake_info_cls
) -> None:
    brightness = fake_property_cls(
        target.WIA_IPS_BRIGHTNESS,
        0,
        name="Brightness",
        subtype=target.WIA_PROP_RANGE,
        minimum=-1000,
        maximum=1000,
        step=1,
        default=0,
    )
    vendor = fake_property_cls(
        9001,
        "vendor-value",
        name="Vendor Exposure Mode",
        subtype=target.WIA_PROP_LIST,
        values=[0, 1, 2],
        default=1,
    )
    item = fake_item_cls([vendor, brightness])
    info = fake_info_cls("fi-65F", "wia-id")

    json_path, text_path = target.write_diagnostic_report(
        info, item, tmp_path / "diagnostics", probe_writes=True
    )

    assert json_path.exists()
    assert text_path.exists()
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["device"] == {"name": "fi-65F", "device_id": "wia-id"}
    assert report["environment"]["probe_writes"] is True

    support = {entry["setting"]: entry for entry in report["target_support"]}
    assert support["brightness"]["support"] == "EXPOSED_AND_SETTABLE"
    assert support["contrast"]["support"] == "NOT_EXPOSED_BY_WIA"

    all_properties = {
        entry["property_id"]: entry for entry in report["all_wia_item_properties"]
    }
    assert all_properties[9001]["driver_name"] == "Vendor Exposure Mode"
    assert all_properties[9001]["allowed"]["values"] == [0, 1, 2]

    text = text_path.read_text(encoding="utf-8")
    assert "Target setting support" in text
    assert "EXPOSED_AND_SETTABLE" in text
    assert "Vendor Exposure Mode" in text


def test_write_diagnostic_report_can_disable_write_probes(
    tmp_path: Path, fake_property_cls, fake_item_cls, fake_info_cls
) -> None:
    prop = fake_property_cls(target.WIA_IPS_BRIGHTNESS, 0)

    json_path, _ = target.write_diagnostic_report(
        fake_info_cls("fi-65F"),
        fake_item_cls([prop]),
        tmp_path,
        probe_writes=False,
    )

    report = json.loads(json_path.read_text(encoding="utf-8"))
    brightness = next(
        entry for entry in report["target_support"] if entry["setting"] == "brightness"
    )
    assert brightness["support"] == "EXPOSED_WRITABLE_NOT_PROBED"
    assert prop.write_count == 0
