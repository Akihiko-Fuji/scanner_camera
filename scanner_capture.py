#!/usr/bin/env python3
"""fi-65FからWIA経由で画像を取り込むコマンドラインツール。

Windows 32-bit / 64-bitを対象とし、CLIの値を ``config.ini`` より優先して使用する。
診断モードではWIAプロパティの公開状況と書き込み可否を調査し、通常
モードでは画像を ``DSC_####.jpeg`` という連番で保存する。

WIAのbrightness/contrastはドライバーのプロパティであり、物理的な
露光時間、積分時間、アナログゲインを直接制御する保証はない。
"""

from __future__ import annotations

import argparse
import configparser
import datetime as dt
import json
import logging
import os
import platform
import re
import struct
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import pythoncom
    import win32com.client
except ImportError:  # pragma: no cover - Windows以外で純粋関数をテスト可能にする
    pythoncom = None
    win32com = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - 実行時に分かりやすいエラーを表示する
    Image = None


# WIA constants used by the capture path.
WIA_DEVICE_TYPE_SCANNER = 1

WIA_IPS_CUR_INTENT = 6146
WIA_IPS_XRES = 6147
WIA_IPS_YRES = 6148
WIA_IPS_XPOS = 6149
WIA_IPS_YPOS = 6150
WIA_IPS_XEXTENT = 6151
WIA_IPS_YEXTENT = 6152
WIA_IPS_PHOTOMETRIC_INTERP = 6153
WIA_IPS_BRIGHTNESS = 6154
WIA_IPS_CONTRAST = 6155
WIA_IPS_ORIENTATION = 6156
WIA_IPS_ROTATION = 6157
WIA_IPS_MIRROR = 6158
WIA_IPS_THRESHOLD = 6159
WIA_IPS_INVERT = 6160
WIA_IPS_WARM_UP_TIME = 6161

WIA_INTENT_IMAGE_TYPE_COLOR = 1
WIA_INTENT_IMAGE_TYPE_GRAYSCALE = 2
WIA_INTENT_IMAGE_TYPE_TEXT = 4
WIA_INTENT_MAXIMIZE_QUALITY = 0x00020000

WIA_PROP_NONE = 0
WIA_PROP_RANGE = 1
WIA_PROP_LIST = 2
WIA_PROP_FLAG = 3

WIA_FORMAT_BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"

PROPERTY_NAMES = {
    WIA_IPS_CUR_INTENT: "WIA_IPS_CUR_INTENT",
    WIA_IPS_XRES: "WIA_IPS_XRES",
    WIA_IPS_YRES: "WIA_IPS_YRES",
    WIA_IPS_XPOS: "WIA_IPS_XPOS",
    WIA_IPS_YPOS: "WIA_IPS_YPOS",
    WIA_IPS_XEXTENT: "WIA_IPS_XEXTENT",
    WIA_IPS_YEXTENT: "WIA_IPS_YEXTENT",
    WIA_IPS_PHOTOMETRIC_INTERP: "WIA_IPS_PHOTOMETRIC_INTERP",
    WIA_IPS_BRIGHTNESS: "WIA_IPS_BRIGHTNESS",
    WIA_IPS_CONTRAST: "WIA_IPS_CONTRAST",
    WIA_IPS_ORIENTATION: "WIA_IPS_ORIENTATION",
    WIA_IPS_ROTATION: "WIA_IPS_ROTATION",
    WIA_IPS_MIRROR: "WIA_IPS_MIRROR",
    WIA_IPS_THRESHOLD: "WIA_IPS_THRESHOLD",
    WIA_IPS_INVERT: "WIA_IPS_INVERT",
    WIA_IPS_WARM_UP_TIME: "WIA_IPS_WARM_UP_TIME",
}

TARGET_SETTINGS = {
    "mode": WIA_IPS_CUR_INTENT,
    "dpi_x": WIA_IPS_XRES,
    "dpi_y": WIA_IPS_YRES,
    "x_position": WIA_IPS_XPOS,
    "y_position": WIA_IPS_YPOS,
    "scan_width": WIA_IPS_XEXTENT,
    "scan_height": WIA_IPS_YEXTENT,
    "brightness": WIA_IPS_BRIGHTNESS,
    "contrast": WIA_IPS_CONTRAST,
    "orientation": WIA_IPS_ORIENTATION,
    "rotation": WIA_IPS_ROTATION,
    "mirror": WIA_IPS_MIRROR,
    "threshold": WIA_IPS_THRESHOLD,
    "invert": WIA_IPS_INVERT,
    "warm_up_time": WIA_IPS_WARM_UP_TIME,
}

DSC_PATTERN = re.compile(r"^DSC_(\d{4})\.jpeg$", re.IGNORECASE)


@dataclass
class PropertyReport:
    """WIAプロパティ1件の診断結果を保持する。"""

    property_id: int
    name: str
    driver_name: str
    current_value: Any
    value_type: Any
    subtype: int
    subtype_name: str
    read_only: Optional[bool]
    allowed: Any
    write_probe: str
    write_probe_detail: Optional[str]


@dataclass
class TargetSupport:
    """設定対象プロパティのサポート状況を保持する。"""

    setting: str
    property_id: int
    property_name: str
    exposed: bool
    read_only: Optional[bool]
    current_value: Any
    allowed: Any
    support: str
    detail: Optional[str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture one image from a WIA scanner and save DSC_####.jpeg."
    )
    parser.add_argument("--config", default="config.ini", help="INI file path")
    parser.add_argument("--list-devices", action="store_true", help="List WIA scanners")
    parser.add_argument("--diagnose", action="store_true", help="Inspect WIA properties and save a support report")
    parser.add_argument("--no-probe-writes", action="store_true", help="Do not test writable properties by writing their current value")
    parser.add_argument("--device", help="Substring of WIA scanner device name")
    parser.add_argument("--dpi", type=int, help="Horizontal and vertical DPI")
    parser.add_argument("--brightness", type=int, help="WIA brightness value")
    parser.add_argument("--contrast", type=int, help="WIA contrast value")
    parser.add_argument("--mode", choices=("color", "grayscale", "bw"), help="Requested image type")
    parser.add_argument("--xpos", type=int, help="Scan region X position")
    parser.add_argument("--ypos", type=int, help="Scan region Y position")
    parser.add_argument("--width", type=int, help="Scan region width")
    parser.add_argument("--height", type=int, help="Scan region height")
    parser.add_argument("--jpeg-quality", type=int, help="JPEG quality 1-100")
    parser.add_argument("--output-dir", help="Output directory; default ./jpeg")
    parser.add_argument("--diagnostic-dir", help="Diagnostic report directory; default ./diagnostics")
    parser.add_argument("--show-ui", action="store_true", help="Show the WIA acquisition UI")
    parser.add_argument("--non-strict", action="store_true", help="Warn instead of failing when a requested property is unsupported")
    parser.add_argument("--verbose", action="store_true")
    return parser


def read_config(path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    if path.exists():
        config.read(path, encoding="utf-8")
    return config


def config_value(args: argparse.Namespace, config: configparser.ConfigParser, arg_name: str, section: str, key: str, cast: Any = str, default: Any = None) -> Any:
    cli_value = getattr(args, arg_name)
    if cli_value is not None:
        return cli_value
    if not config.has_option(section, key):
        return default
    raw = config.get(section, key).strip()
    if raw == "":
        return default
    if cast is bool:
        return config.getboolean(section, key)
    return cast(raw)


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    try:
        return [jsonable(item) for item in value]
    except Exception:
        return repr(value)


def property_value(properties: Any, key: Any) -> Any:
    try:
        return properties.Item(key).Value
    except Exception:
        return None


def scanner_name(info: Any) -> str:
    for key in ("Name", 7):
        value = property_value(info.Properties, key)
        if value:
            return str(value)
    return str(info.DeviceID)


def scanner_infos() -> list[Any]:
    manager = win32com.client.Dispatch("WIA.DeviceManager")
    return [info for info in manager.DeviceInfos if int(info.Type) == WIA_DEVICE_TYPE_SCANNER]


def list_devices() -> int:
    infos = scanner_infos()
    if not infos:
        print("No WIA scanner was found.", file=sys.stderr)
        return 1
    for index, info in enumerate(infos, start=1):
        print(f"[{index}] {scanner_name(info)}")
        print(f"    DeviceID: {info.DeviceID}")
    return 0


def select_device(name_substring: Optional[str]) -> tuple[Any, Any]:
    infos = scanner_infos()
    if not infos:
        raise RuntimeError("No WIA scanner was found.")
    if name_substring:
        needle = name_substring.casefold()
        matches = [info for info in infos if needle in scanner_name(info).casefold()]
        if not matches:
            available = ", ".join(scanner_name(info) for info in infos)
            raise RuntimeError(f"No scanner matched {name_substring!r}. Available: {available}")
        if len(matches) > 1:
            names = ", ".join(scanner_name(info) for info in matches)
            raise RuntimeError(f"Device name is ambiguous: {names}")
        info = matches[0]
    else:
        info = infos[0]
    logging.info("Connecting to WIA scanner: %s", scanner_name(info))
    return info, info.Connect()


def get_scan_item(device: Any) -> Any:
    if device.Items.Count < 1:
        raise RuntimeError("The scanner exposes no transferable WIA item.")
    return device.Items.Item(1)


def find_property(item: Any, property_id: int) -> Optional[Any]:
    try:
        return item.Properties.Item(property_id)
    except Exception:
        pass
    for prop in item.Properties:
        try:
            if int(prop.PropertyID) == property_id:
                return prop
        except Exception:
            continue
    return None


def safe_get(obj: Any, attribute: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attribute)
    except Exception:
        return default


def property_subtype_name(subtype: int) -> str:
    return {WIA_PROP_NONE: "NONE", WIA_PROP_RANGE: "RANGE", WIA_PROP_LIST: "LIST", WIA_PROP_FLAG: "FLAG"}.get(subtype, f"UNKNOWN_{subtype}")


def property_constraints(prop: Any) -> Any:
    subtype = int(safe_get(prop, "SubType", WIA_PROP_NONE))
    if subtype == WIA_PROP_RANGE:
        return {"kind": "range", "default": jsonable(safe_get(prop, "SubTypeDefault")), "min": jsonable(safe_get(prop, "SubTypeMin")), "max": jsonable(safe_get(prop, "SubTypeMax")), "step": jsonable(safe_get(prop, "SubTypeStep"))}
    if subtype in (WIA_PROP_LIST, WIA_PROP_FLAG):
        values = safe_get(prop, "SubTypeValues", [])
        return {"kind": "list" if subtype == WIA_PROP_LIST else "flag", "default": jsonable(safe_get(prop, "SubTypeDefault")), "values": jsonable(values)}
    return {"kind": "driver-defined"}


def is_read_only(prop: Any) -> Optional[bool]:
    value = safe_get(prop, "IsReadOnly", None)
    return None if value is None else bool(value)


def read_property(prop: Any) -> Any:
    try:
        return prop.Value
    except Exception as exc:
        return f"<read error: {exc}>"


def probe_property_write(prop: Any, enabled: bool) -> tuple[str, Optional[str]]:
    read_only = is_read_only(prop)
    if read_only is True:
        return "READ_ONLY", None
    if not enabled:
        return "NOT_PROBED", "write probing disabled"
    try:
        original = prop.Value
    except Exception as exc:
        return "PROBE_NOT_POSSIBLE", f"could not read current value: {exc}"
    try:
        prop.Value = original
        readback = prop.Value
        return "WRITE_PROBE_OK", f"readback={readback!r}"
    except Exception as exc:
        return "WRITE_PROBE_FAILED", str(exc)


def inspect_property(prop: Any, probe_writes: bool) -> PropertyReport:
    property_id = int(safe_get(prop, "PropertyID", -1))
    driver_name = str(safe_get(prop, "Name", "Unknown"))
    subtype = int(safe_get(prop, "SubType", WIA_PROP_NONE))
    probe, detail = probe_property_write(prop, probe_writes)
    return PropertyReport(property_id=property_id, name=PROPERTY_NAMES.get(property_id, driver_name), driver_name=driver_name, current_value=jsonable(read_property(prop)), value_type=jsonable(safe_get(prop, "Type")), subtype=subtype, subtype_name=property_subtype_name(subtype), read_only=is_read_only(prop), allowed=property_constraints(prop), write_probe=probe, write_probe_detail=detail)


def support_from_property(setting: str, property_id: int, prop_report: Optional[PropertyReport]) -> TargetSupport:
    if prop_report is None:
        return TargetSupport(setting=setting, property_id=property_id, property_name=PROPERTY_NAMES.get(property_id, str(property_id)), exposed=False, read_only=None, current_value=None, allowed=None, support="NOT_EXPOSED_BY_WIA", detail="The selected WIA item does not publish this property.")
    if prop_report.read_only is True:
        support = "EXPOSED_READ_ONLY"
    elif prop_report.write_probe == "WRITE_PROBE_OK":
        support = "EXPOSED_AND_SETTABLE"
    elif prop_report.write_probe == "NOT_PROBED":
        support = "EXPOSED_WRITABLE_NOT_PROBED"
    elif prop_report.write_probe == "WRITE_PROBE_FAILED":
        support = "EXPOSED_BUT_WRITE_REJECTED"
    else:
        support = "EXPOSED_SUPPORT_UNCERTAIN"
    return TargetSupport(setting=setting, property_id=property_id, property_name=prop_report.name, exposed=True, read_only=prop_report.read_only, current_value=prop_report.current_value, allowed=prop_report.allowed, support=support, detail=prop_report.write_probe_detail)


def write_diagnostic_report(info: Any, item: Any, output_dir: Path, probe_writes: bool) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"wia_diagnostic_{stamp}.json"
    text_path = output_dir / f"wia_diagnostic_{stamp}.txt"
    property_reports = [inspect_property(prop, probe_writes) for prop in item.Properties]
    property_reports.sort(key=lambda report: report.property_id)
    by_id = {report.property_id: report for report in property_reports}
    targets = [support_from_property(setting, property_id, by_id.get(property_id)) for setting, property_id in TARGET_SETTINGS.items()]
    report = {"generated_at": dt.datetime.now().astimezone().isoformat(), "environment": {"platform": platform.platform(), "python_version": platform.python_version(), "python_bitness": struct.calcsize("P") * 8, "probe_writes": probe_writes}, "device": {"name": scanner_name(info), "device_id": str(info.DeviceID)}, "target_support": [asdict(target) for target in targets], "all_wia_item_properties": [asdict(prop) for prop in property_reports]}
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["fi-65F WIA diagnostic report", f"Generated: {report['generated_at']}", f"Device: {report['device']['name']}", f"DeviceID: {report['device']['device_id']}", f"Python: {report['environment']['python_version']} ({report['environment']['python_bitness']}-bit)", f"Write probes: {'enabled' if probe_writes else 'disabled'}", "", "Target setting support", "----------------------"]
    for target in targets:
        lines.append(f"{target.setting:14s} {target.support:30s} {target.property_name} ({target.property_id})")
        if target.current_value is not None:
            lines.append(f"  current: {target.current_value!r}")
        if target.allowed is not None:
            lines.append(f"  allowed: {target.allowed!r}")
        if target.detail:
            lines.append(f"  detail : {target.detail}")
    lines.extend(["", "All properties exposed by the selected WIA item", "-----------------------------------------------"])
    for prop in property_reports:
        lines.append(f"{prop.property_id:5d} {prop.name} read_only={prop.read_only!r} probe={prop.write_probe}")
        lines.append(f"  driver_name: {prop.driver_name}")
        lines.append(f"  current    : {prop.current_value!r}")
        lines.append(f"  allowed    : {prop.allowed!r}")
        if prop.write_probe_detail:
            lines.append(f"  detail     : {prop.write_probe_detail}")
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, text_path


def normalize_property_value(prop: Any, requested: int) -> int:
    subtype = int(safe_get(prop, "SubType", WIA_PROP_NONE))
    if subtype == WIA_PROP_RANGE:
        minimum = int(prop.SubTypeMin)
        maximum = int(prop.SubTypeMax)
        step = int(prop.SubTypeStep) or 1
        clamped = max(minimum, min(maximum, int(requested)))
        return minimum + round((clamped - minimum) / step) * step
    if subtype in (WIA_PROP_LIST, WIA_PROP_FLAG):
        values = [int(value) for value in prop.SubTypeValues]
        if int(requested) in values:
            return int(requested)
        if values:
            return min(values, key=lambda candidate: abs(candidate - int(requested)))
    return int(requested)


def set_property(item: Any, property_id: int, requested: Optional[int], strict: bool) -> None:
    if requested is None:
        return
    label = PROPERTY_NAMES.get(property_id, str(property_id))
    prop = find_property(item, property_id)
    if prop is None:
        message = f"{label} is not exposed by the selected WIA item."
        if strict:
            raise RuntimeError(message + " Run --diagnose to inspect support.")
        logging.warning(message)
        return
    if is_read_only(prop) is True:
        message = f"{label} is exposed but read-only."
        if strict:
            raise RuntimeError(message + " Run --diagnose to inspect support.")
        logging.warning(message)
        return
    actual = normalize_property_value(prop, int(requested))
    try:
        prop.Value = actual
        readback = prop.Value
    except Exception as exc:
        raise RuntimeError(f"Could not set {label} to {actual}; allowed={property_constraints(prop)!r}") from exc
    logging.info("%s requested=%s applied=%s readback=%r", label, requested, actual, readback)


def mode_to_intent(mode: str) -> int:
    image_type = {"color": WIA_INTENT_IMAGE_TYPE_COLOR, "grayscale": WIA_INTENT_IMAGE_TYPE_GRAYSCALE, "bw": WIA_INTENT_IMAGE_TYPE_TEXT}[mode]
    return image_type | WIA_INTENT_MAXIMIZE_QUALITY


def next_output_number(names: list[str]) -> int:
    numbers = [int(match.group(1)) for name in names if (match := DSC_PATTERN.match(name)) is not None]
    next_number = max(numbers, default=0) + 1
    if next_number > 9999:
        raise RuntimeError("DSC_9999.jpeg already exists; no filename remains.")
    return next_number


def reserve_output_path(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    file_names = [entry.name for entry in output_dir.iterdir() if entry.is_file()]
    first_number = next_output_number(file_names)
    for number in range(first_number, 10000):
        candidate = output_dir / f"DSC_{number:04d}.jpeg"
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("DSC_9999.jpeg already exists; no filename remains.")


def remove_empty_reservation(output: Optional[Path]) -> None:
    if output is None:
        return
    try:
        if output.exists() and output.stat().st_size == 0:
            output.unlink()
    except OSError:
        logging.warning("Could not remove empty reserved file: %s", output)


def runtime_dependencies_available() -> bool:
    return pythoncom is not None and win32com is not None and Image is not None


def save_transfer_as_jpeg(image_file: Any, output: Path, quality: int, mode: str) -> None:
    with tempfile.TemporaryDirectory(prefix="fi65f_") as temp_dir:
        bmp_path = Path(temp_dir) / "capture.bmp"
        image_file.SaveFile(str(bmp_path))
        with Image.open(bmp_path) as image:
            image.load()
            if mode == "grayscale":
                converted = image.convert("L")
            elif mode == "bw":
                converted = image.convert("L").point(lambda pixel: 255 if pixel >= 128 else 0, "1")
            else:
                converted = image.convert("RGB")
            converted.save(output, format="JPEG", quality=max(1, min(100, quality)), subsampling=0, optimize=True)


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")
    if os.name != "nt":
        logging.error("This utility supports Windows only.")
        return 2
    if not runtime_dependencies_available():
        logging.error("pywin32 and Pillow are required. Run: py -m pip install -r requirements.txt")
        return 2
    config = read_config(Path(args.config))
    if args.list_devices:
        return list_devices()
    device_name = config_value(args, config, "device", "scanner", "device", str, None)
    output_dir = Path(config_value(args, config, "output_dir", "output", "directory", str, "./jpeg"))
    diagnostic_dir = Path(config_value(args, config, "diagnostic_dir", "diagnostics", "directory", str, "./diagnostics"))
    dpi = config_value(args, config, "dpi", "scan", "dpi", int, 600)
    brightness = config_value(args, config, "brightness", "scan", "brightness", int, None)
    contrast = config_value(args, config, "contrast", "scan", "contrast", int, None)
    mode = config_value(args, config, "mode", "scan", "mode", str, "color").lower()
    xpos = config_value(args, config, "xpos", "region", "xpos", int, None)
    ypos = config_value(args, config, "ypos", "region", "ypos", int, None)
    width = config_value(args, config, "width", "region", "width", int, None)
    height = config_value(args, config, "height", "region", "height", int, None)
    jpeg_quality = config_value(args, config, "jpeg_quality", "output", "jpeg_quality", int, 95)
    config_show_ui = config.getboolean("scanner", "show_ui") if config.has_option("scanner", "show_ui") else False
    show_ui = args.show_ui or config_show_ui
    config_strict = config.getboolean("scanner", "strict_settings") if config.has_option("scanner", "strict_settings") else True
    strict = config_strict and not args.non_strict
    config_probe = config.getboolean("diagnostics", "probe_writes") if config.has_option("diagnostics", "probe_writes") else True
    probe_writes = config_probe and not args.no_probe_writes
    if mode not in {"color", "grayscale", "bw"}:
        raise SystemExit("mode must be color, grayscale, or bw")
    pythoncom.CoInitialize()
    reserved_output: Optional[Path] = None
    try:
        info, device = select_device(device_name)
        item = get_scan_item(device)
        if args.diagnose:
            json_path, text_path = write_diagnostic_report(info, item, diagnostic_dir, probe_writes)
            print(f"JSON: {json_path.resolve()}")
            print(f"TEXT: {text_path.resolve()}")
            return 0
        set_property(item, WIA_IPS_CUR_INTENT, mode_to_intent(mode), strict)
        set_property(item, WIA_IPS_XRES, dpi, strict)
        set_property(item, WIA_IPS_YRES, dpi, strict)
        set_property(item, WIA_IPS_BRIGHTNESS, brightness, strict)
        set_property(item, WIA_IPS_CONTRAST, contrast, strict)
        set_property(item, WIA_IPS_XPOS, xpos, strict)
        set_property(item, WIA_IPS_YPOS, ypos, strict)
        set_property(item, WIA_IPS_XEXTENT, width, strict)
        set_property(item, WIA_IPS_YEXTENT, height, strict)
        reserved_output = reserve_output_path(output_dir)
        dialog = win32com.client.Dispatch("WIA.CommonDialog")
        logging.info("Starting transfer...")
        image_file = dialog.ShowTransfer(item, WIA_FORMAT_BMP, bool(show_ui))
        if image_file is None:
            raise RuntimeError("The WIA driver returned no image.")
        save_transfer_as_jpeg(image_file, reserved_output, jpeg_quality, mode)
        print(reserved_output.resolve())
        return 0
    except Exception as exc:
        remove_empty_reservation(reserved_output)
        logging.error("%s", exc)
        if args.verbose:
            logging.exception("Detailed failure")
        return 1
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
