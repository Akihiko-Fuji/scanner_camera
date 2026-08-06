from __future__ import annotations

import argparse
import configparser
from pathlib import Path

import pytest

import scanner_capture as target


def make_args(**overrides):
    values = {
        "device": None,
        "dpi": None,
        "brightness": None,
        "contrast": None,
        "mode": None,
        "xpos": None,
        "ypos": None,
        "width": None,
        "height": None,
        "jpeg_quality": None,
        "output_dir": None,
        "diagnostic_dir": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_read_config_returns_empty_config_for_missing_file(tmp_path: Path) -> None:
    config = target.read_config(tmp_path / "missing.ini")
    assert config.sections() == []


def test_read_config_reads_utf8_ini(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text("[scanner]\ndevice = fi-65F 日本語\n", encoding="utf-8")

    config = target.read_config(path)

    assert config.get("scanner", "device") == "fi-65F 日本語"


def test_config_value_prefers_cli_over_ini() -> None:
    config = configparser.ConfigParser()
    config.read_dict({"scan": {"dpi": "300"}})

    result = target.config_value(
        make_args(dpi=600), config, "dpi", "scan", "dpi", int, 150
    )

    assert result == 600


def test_config_value_uses_ini_then_default() -> None:
    config = configparser.ConfigParser()
    config.read_dict({"scan": {"dpi": "300", "brightness": ""}})

    assert target.config_value(
        make_args(), config, "dpi", "scan", "dpi", int, 150
    ) == 300
    assert target.config_value(
        make_args(), config, "brightness", "scan", "brightness", int, 25
    ) == 25
    assert target.config_value(
        make_args(), config, "contrast", "scan", "contrast", int, 10
    ) == 10


def test_config_value_reads_boolean() -> None:
    config = configparser.ConfigParser()
    config.read_dict({"scanner": {"enabled": "yes"}})
    args = argparse.Namespace(enabled=None)

    assert target.config_value(
        args, config, "enabled", "scanner", "enabled", bool, False
    ) is True


def test_parser_accepts_capture_options() -> None:
    args = target.build_parser().parse_args(
        [
            "--device",
            "fi-65F",
            "--dpi",
            "600",
            "--mode",
            "grayscale",
            "--brightness",
            "250",
            "--output-dir",
            ".\\jpeg",
        ]
    )

    assert args.device == "fi-65F"
    assert args.dpi == 600
    assert args.mode == "grayscale"
    assert args.brightness == 250
    assert args.output_dir == ".\\jpeg"


@pytest.mark.parametrize(
    ("mode", "image_type"),
    [
        ("color", target.WIA_INTENT_IMAGE_TYPE_COLOR),
        ("grayscale", target.WIA_INTENT_IMAGE_TYPE_GRAYSCALE),
        ("bw", target.WIA_INTENT_IMAGE_TYPE_TEXT),
    ],
)
def test_mode_to_intent_adds_maximize_quality(mode: str, image_type: int) -> None:
    assert target.mode_to_intent(mode) == image_type | target.WIA_INTENT_MAXIMIZE_QUALITY


def test_mode_to_intent_rejects_unknown_mode() -> None:
    with pytest.raises(KeyError):
        target.mode_to_intent("raw")


def test_jsonable_handles_com_like_values() -> None:
    class IterableValue:
        def __iter__(self):
            return iter((1, b"\x0f"))

    class NonIterable:
        def __iter__(self):
            raise RuntimeError("not iterable")

        def __repr__(self):
            return "<non-iterable>"

    assert target.jsonable(None) is None
    assert target.jsonable(b"\x00\xff") == "00ff"
    assert target.jsonable((1, "x")) == [1, "x"]
    assert target.jsonable(IterableValue()) == [1, "0f"]
    assert target.jsonable(NonIterable()) == "<non-iterable>"


def test_runtime_dependencies_available_requires_all_components(monkeypatch) -> None:
    marker = object()
    monkeypatch.setattr(target, "pythoncom", marker)
    monkeypatch.setattr(target, "win32com", marker)
    monkeypatch.setattr(target, "Image", marker)
    assert target.runtime_dependencies_available() is True

    monkeypatch.setattr(target, "Image", None)
    assert target.runtime_dependencies_available() is False
