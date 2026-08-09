#!/usr/bin/env python3
"""fi-65FをTWAIN経由で診断・制御して画像を取り込むCLI。

Windows 32-bit / 64-bitを対象とし、Pythonプロセス、TWAIN DSM、Data Sourceの
bitnessを一致させて使用する。CLIの値を ``config.ini`` より優先して使用し、
WIA版 ``scanner_capture.py`` と同じ ``DSC_####.jpeg`` の連番保存契約を共有する。

TWAINではWIAより多くのCapabilityが公開される可能性があるため、診断時は
CAP_SUPPORTEDCAPSを起点に全Capabilityを読み出し、scanner_cameraで重要な
露出・光源・画質関連Capabilityを重点的に評価する。
"""

from __future__ import annotations

import argparse
import datetime as dt
import inspect
import json
import logging
import math
import os
import platform
import struct
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import twain
    from twain.lowlevel import constants as twc
except ImportError:  # pragma: no cover - 純粋関数をTWAIN未導入環境でもテスト可能にする
    twain = None
    twc = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

from scanner_capture import (
    config_value,
    read_config,
    remove_empty_reservation,
    reserve_output_path,
    resolve_probe_writes,
    save_pillow_jpeg_atomically,
)


@dataclass
class TwainCapabilityReport:
    """TWAIN Capability 1件の診断結果。"""

    capability_id: int
    name: str
    item_type: Optional[int]
    item_type_name: Optional[str]
    query_support: Any
    get_value: Any
    current_value: Any
    default_value: Any
    support: str
    write_probe: str
    detail: Optional[str]


@dataclass
class TwainTargetSupport:
    """scanner_cameraで重視するTWAIN設定のサポート状況。"""

    setting: str
    capability_id: Optional[int]
    capability_name: str
    exposed: bool
    current_value: Any
    allowed: Any
    support: str
    detail: Optional[str]


def runtime_bitness() -> int:
    """実行中Pythonプロセスのbitnessを返す。"""
    return struct.calcsize("P") * 8


def automatic_dsm_description() -> str:
    """pytwain 2.3.xが自動選択するDSMを診断表示用に説明する。"""
    if runtime_bitness() == 32:
        windir = os.environ.get("WINDIR", "%WINDIR%")
        return f"auto:{windir}\\twain_32.dll (TWAIN 1)"
    return "auto:twaindsm.dll"


def _const(name: str) -> Optional[int]:
    """TWAIN定数を安全に取得する。pytwain未導入時はNone。"""
    if twc is None:
        return None
    value = getattr(twc, name, None)
    return int(value) if isinstance(value, int) else None


def _capability_name_map() -> dict[int, str]:
    """pytwainが公開するCAP_/ICAP_定数から名前辞書を作る。"""
    if twc is None:
        return {}
    result: dict[int, str] = {}
    for name in dir(twc):
        if not name.startswith(("CAP_", "ICAP_")):
            continue
        value = getattr(twc, name, None)
        if not isinstance(value, int):
            continue
        current = result.get(int(value))
        if current is None or (
            name.startswith("ICAP_") and not current.startswith("ICAP_")
        ):
            result[int(value)] = name
    return result


def _item_type_name_map() -> dict[int, str]:
    if twc is None:
        return {}
    result: dict[int, str] = {}
    for name in dir(twc):
        if name.startswith("TWTY_"):
            value = getattr(twc, name, None)
            if isinstance(value, int):
                result[int(value)] = name
    return result


def build_target_capabilities() -> dict[str, Optional[int]]:
    """WIA版相当＋scanner camera向けTWAIN固有Capabilityを定義する。"""
    return {
        "mode": _const("ICAP_PIXELTYPE"),
        "dpi_x": _const("ICAP_XRESOLUTION"),
        "dpi_y": _const("ICAP_YRESOLUTION"),
        "brightness": _const("ICAP_BRIGHTNESS"),
        "contrast": _const("ICAP_CONTRAST"),
        "threshold": _const("ICAP_THRESHOLD"),
        "orientation": _const("ICAP_ORIENTATION"),
        "rotation": _const("ICAP_ROTATION"),
        "bit_depth": _const("ICAP_BITDEPTH"),
        "autobright": _const("ICAP_AUTOBRIGHT"),
        "exposure_time": _const("ICAP_EXPOSURETIME"),
        "gamma": _const("ICAP_GAMMA"),
        "highlight": _const("ICAP_HIGHLIGHT"),
        "shadow": _const("ICAP_SHADOW"),
        "lamp_state": _const("ICAP_LAMPSTATE"),
        "light_source": _const("ICAP_LIGHTSOURCE"),
        "light_path": _const("ICAP_LIGHTPATH"),
        "physical_width": _const("ICAP_PHYSICALWIDTH"),
        "physical_height": _const("ICAP_PHYSICALHEIGHT"),
        "native_dpi_x": _const("ICAP_XNATIVERESOLUTION"),
        "native_dpi_y": _const("ICAP_YNATIVERESOLUTION"),
        "units": _const("ICAP_UNITS"),
        "transfer_mechanism": _const("ICAP_XFERMECH"),
    }


SAFE_WRITE_PROBE_NAMES = {
    "mode",
    "dpi_x",
    "dpi_y",
    "brightness",
    "contrast",
    "threshold",
    "orientation",
    "rotation",
    "bit_depth",
    "autobright",
    "exposure_time",
    "gamma",
    "highlight",
    "shadow",
    "lamp_state",
    "light_source",
    "light_path",
    "units",
}


def build_parser() -> argparse.ArgumentParser:
    """WIA版と極力同じ引数名を持つTWAIN CLIパーサー。"""
    parser = argparse.ArgumentParser(
        description="Capture one image from a TWAIN source and save DSC_####.jpeg."
    )
    parser.add_argument("--config", default="config.ini", help="INI file path")
    parser.add_argument("--list-devices", action="store_true", help="List TWAIN sources")
    parser.add_argument("--diagnose", action="store_true", help="Inspect TWAIN capabilities")
    parser.add_argument(
        "--probe-writes",
        action="store_true",
        help="Explicitly enable no-change SET/read-back diagnostic probes",
    )
    parser.add_argument(
        "--no-probe-writes",
        action="store_true",
        help="Disable no-change SET/read-back diagnostic probes",
    )
    parser.add_argument("--device", help="Substring of TWAIN source name")
    parser.add_argument(
        "--dsm",
        help="Explicit TWAIN DSM DLL path/name; normally leave unset for pytwain auto-selection",
    )
    parser.add_argument("--dpi", type=float, help="Horizontal and vertical DPI")
    parser.add_argument("--brightness", type=float, help="TWAIN brightness value")
    parser.add_argument("--contrast", type=float, help="TWAIN contrast value")
    parser.add_argument(
        "--mode", choices=("color", "grayscale", "bw"), help="Requested pixel type"
    )
    parser.add_argument("--xpos", type=int, help="Scan region X position in pixels")
    parser.add_argument("--ypos", type=int, help="Scan region Y position in pixels")
    parser.add_argument("--width", type=int, help="Scan region width in pixels")
    parser.add_argument("--height", type=int, help="Scan region height in pixels")
    parser.add_argument("--jpeg-quality", type=int, help="JPEG quality 1-100")
    parser.add_argument("--output-dir", help="Output directory; default ./jpeg")
    parser.add_argument(
        "--diagnostic-dir", help="Diagnostic report directory; default ./diagnostics"
    )
    parser.add_argument("--show-ui", action="store_true", help="Show TWAIN source UI")
    parser.add_argument(
        "--non-strict",
        action="store_true",
        help="Warn instead of failing when a requested capability is unsupported",
    )
    parser.add_argument("--gamma", type=float, help="ICAP_GAMMA")
    parser.add_argument("--exposure-time", type=float, help="ICAP_EXPOSURETIME")
    parser.add_argument(
        "--autobright", choices=("on", "off"), help="ICAP_AUTOBRIGHT"
    )
    parser.add_argument(
        "--lamp-state", choices=("on", "off"), help="ICAP_LAMPSTATE"
    )
    parser.add_argument("--light-source", type=int, help="ICAP_LIGHTSOURCE raw value")
    parser.add_argument("--bit-depth", type=int, help="ICAP_BITDEPTH")
    parser.add_argument("--verbose", action="store_true")
    return parser


def runtime_dependencies_available() -> bool:
    """TWAIN取得に必要な依存関係が利用可能か確認する。"""
    return twain is not None and twc is not None and Image is not None


def jsonable(value: Any) -> Any:
    """TWAIN/ctypes由来の値をJSONへ直列化できる形にする。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, dict):
        return {str(key): jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    raw = getattr(value, "value", None)
    if isinstance(raw, (bool, int, float, str)):
        return raw
    try:
        return [jsonable(item) for item in value]
    except Exception:
        return repr(value)


def split_capability_result(result: Any) -> tuple[Optional[int], Any]:
    """pytwainのCapability戻り値を(item_type, payload)へ正規化する。"""
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], int)
    ):
        return int(result[0]), result[1]
    return None, result


def current_scalar(payload: Any) -> Any:
    """GETCURRENT/GET結果からSETに使える現在値を取り出す。"""
    if isinstance(payload, dict):
        for key in ("CurrentValue", "current", "Current"):
            if key in payload:
                return payload[key]
        return None
    if isinstance(payload, tuple) and len(payload) == 3:
        current_index, _, values = payload
        try:
            return values[int(current_index)]
        except Exception:
            return None
    if isinstance(payload, list):
        return payload[0] if len(payload) == 1 else None
    return payload


def _values_equivalent(requested: Any, readback: Any, item_type: Optional[int]) -> bool:
    """SET要求値とGETCURRENT値が同一設定とみなせるか判定する。

    TW_FIX32は16.16固定小数点への丸めがあり得るため、1 LSB程度の差は
    同値として扱う。それ以外の数値・列挙値・真偽値は原則として一致を要求する。
    """
    if requested is None or readback is None:
        return requested is readback

    fix32 = _const("TWTY_FIX32")
    if item_type == fix32:
        try:
            return math.isclose(
                float(requested),
                float(readback),
                rel_tol=0.0,
                abs_tol=(1.0 / 65536.0) + 1e-12,
            )
        except (TypeError, ValueError):
            return requested == readback

    if isinstance(requested, bool) or isinstance(readback, bool):
        return bool(requested) == bool(readback)

    return requested == readback


def _bool_value(text: Optional[str]) -> Optional[bool]:
    """TWAINのon/off文字列を厳密に真偽値へ変換する。"""
    if text is None:
        return None
    normalized = text.strip().lower()
    if normalized == "on":
        return True
    if normalized == "off":
        return False
    raise ValueError(f"Expected 'on' or 'off', got {text!r}")


def _positive_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result <= 0:
        return None
    return result


def create_source_manager(dsm_name: Optional[str]) -> Any:
    """実行中Pythonと同じbitnessのTWAIN Source Managerを開く。"""
    if twain is None:
        raise RuntimeError("pytwain is not installed")
    kwargs = {
        "parent_window": 0,
        "ProductName": "scanner_camera",
        "ProductFamily": "scanner camera",
        "Manufacturer": "scanner_camera",
    }
    if dsm_name:
        kwargs["dsm_name"] = dsm_name
    return twain.SourceManager(**kwargs)


def source_names(manager: Any) -> list[str]:
    """利用可能なTWAIN Data Source名を列挙する。"""
    return [str(name) for name in manager.source_list]


def select_source(manager: Any, name_substring: Optional[str]) -> Any:
    """名前の部分一致でTWAIN Sourceを一意に選択して開く。"""
    names = source_names(manager)
    if not names:
        bitness = runtime_bitness()
        raise RuntimeError(
            f"No {bitness}-bit TWAIN source was found. Confirm that the scanner "
            f"Data Source matches the {bitness}-bit Python process and that the "
            f"appropriate DSM is available ({automatic_dsm_description()})."
        )
    if name_substring:
        needle = name_substring.casefold()
        matches = [name for name in names if needle in name.casefold()]
        if not matches:
            raise RuntimeError(
                f"No TWAIN source matched {name_substring!r}. Available: {', '.join(names)}"
            )
        if len(matches) > 1:
            raise RuntimeError(f"TWAIN source name is ambiguous: {', '.join(matches)}")
        selected = matches[0]
    else:
        selected = names[0]
    logging.info("Connecting to TWAIN source: %s", selected)
    source = manager.open_source(selected)
    if source is None:
        raise RuntimeError(f"Could not open TWAIN source: {selected}")
    return source


def list_devices(dsm_name: Optional[str]) -> int:
    """TWAIN Source一覧を標準出力へ表示する。"""
    manager = create_source_manager(dsm_name)
    try:
        names = source_names(manager)
        if not names:
            print(
                f"No {runtime_bitness()}-bit TWAIN source was found. "
                f"DSM={dsm_name or automatic_dsm_description()}",
                file=sys.stderr,
            )
            return 1
        for index, name in enumerate(names, start=1):
            print(f"[{index}] {name}")
        return 0
    finally:
        try:
            manager.close()
        except Exception:
            logging.debug("TWAIN manager close failed", exc_info=True)


def query_support(source: Any, capability_id: int) -> Any:
    """MSG_QUERYSUPPORTを利用できるpytwainでは操作ビットマスクを取得する。"""
    if twc is None or not hasattr(source, "_get_capability"):
        return None
    msg = getattr(twc, "MSG_QUERYSUPPORT", None)
    if msg is None:
        return None
    try:
        result = source._get_capability(capability_id, msg)  # noqa: SLF001
    except Exception:
        return None
    _, payload = split_capability_result(result)
    return jsonable(current_scalar(payload))


def capability_get(
    source: Any, capability_id: int, method_name: str
) -> tuple[bool, Optional[int], Any, Optional[str]]:
    """Capability読み出しを例外込みで正規化する。"""
    method = getattr(source, method_name)
    try:
        result = method(capability_id)
    except Exception as exc:
        return False, None, None, f"{type(exc).__name__}: {exc}"
    item_type, payload = split_capability_result(result)
    return True, item_type, payload, None


def capability_report(
    source: Any,
    capability_id: int,
    name: str,
    probe_writes: bool,
    safe_to_probe: bool,
) -> TwainCapabilityReport:
    """1 CapabilityについてGET/CURRENT/DEFAULT/SET(no-change)を調べる。"""
    item_type_names = _item_type_name_map()
    get_ok, get_type, get_payload, get_error = capability_get(
        source, capability_id, "get_capability"
    )
    cur_ok, cur_type, cur_payload, cur_error = capability_get(
        source, capability_id, "get_capability_current"
    )
    def_ok, def_type, def_payload, def_error = capability_get(
        source, capability_id, "get_capability_default"
    )
    item_type = cur_type if cur_type is not None else get_type
    if item_type is None:
        item_type = def_type

    qsupport = query_support(source, capability_id)
    write_probe = "NOT_PROBED"
    probe_detail: Optional[str] = None
    if probe_writes and safe_to_probe and cur_ok:
        scalar = current_scalar(cur_payload)
        if scalar is None or item_type is None:
            write_probe = "PROBE_NOT_POSSIBLE"
            probe_detail = "current value or item type is not scalar/known"
        else:
            try:
                source.set_capability(capability_id, item_type, scalar)
                read_ok, _, read_payload, read_error = capability_get(
                    source, capability_id, "get_capability_current"
                )
                if read_ok:
                    readback = current_scalar(read_payload)
                    if _values_equivalent(scalar, readback, item_type):
                        write_probe = "WRITE_PROBE_OK"
                    else:
                        write_probe = "WRITE_PROBE_ADJUSTED"
                    probe_detail = f"readback={jsonable(readback)!r}"
                else:
                    write_probe = "WRITE_PROBE_READBACK_FAILED"
                    probe_detail = read_error
            except Exception as exc:
                write_probe = "WRITE_PROBE_FAILED"
                probe_detail = f"{type(exc).__name__}: {exc}"
    elif probe_writes and not safe_to_probe:
        write_probe = "NOT_PROBED_NON_TARGET"
    else:
        write_probe = "NOT_PROBED_DISABLED"

    if not get_ok and not cur_ok and not def_ok:
        support = "NOT_EXPOSED_BY_TWAIN"
    elif write_probe == "WRITE_PROBE_OK":
        support = "EXPOSED_AND_SETTABLE"
    elif write_probe in {"WRITE_PROBE_FAILED", "WRITE_PROBE_ADJUSTED"}:
        support = "EXPOSED_BUT_WRITE_REJECTED"
    elif cur_ok:
        support = "EXPOSED_READABLE"
    else:
        support = "EXPOSED_SUPPORT_UNCERTAIN"

    errors = [part for part in (get_error, cur_error, def_error, probe_detail) if part]
    return TwainCapabilityReport(
        capability_id=capability_id,
        name=name,
        item_type=item_type,
        item_type_name=item_type_names.get(item_type) if item_type is not None else None,
        query_support=qsupport,
        get_value=jsonable(get_payload) if get_ok else None,
        current_value=jsonable(cur_payload) if cur_ok else None,
        default_value=jsonable(def_payload) if def_ok else None,
        support=support,
        write_probe=write_probe,
        detail=" | ".join(errors) if errors else None,
    )


def extract_supported_capability_ids(source: Any) -> tuple[list[int], Optional[str]]:
    """CAP_SUPPORTEDCAPSからSourceが宣言するCapability IDを取得する。"""
    cap = _const("CAP_SUPPORTEDCAPS")
    if cap is None:
        return [], "CAP_SUPPORTEDCAPS constant is unavailable"
    try:
        result = source.get_capability(cap)
    except Exception as exc:
        return [], f"CAP_SUPPORTEDCAPS failed: {type(exc).__name__}: {exc}"
    _, payload = split_capability_result(result)
    values: Any = payload
    if isinstance(payload, tuple) and len(payload) == 3:
        values = payload[2]
    if isinstance(payload, dict):
        values = payload.get("values") or payload.get("Items") or []
    try:
        ids = sorted({int(value) for value in values})
    except Exception:
        return [], f"Could not parse CAP_SUPPORTEDCAPS payload: {payload!r}"
    return ids, None


def inspect_image_layout(source: Any, probe_writes: bool) -> dict[str, Any]:
    """DAT_IMAGELAYOUT相当を診断する。"""
    result: dict[str, Any] = {
        "exposed": False,
        "current": None,
        "default": None,
        "support": "NOT_EXPOSED_BY_TWAIN",
        "detail": None,
    }
    try:
        current = source.get_image_layout()
        result["exposed"] = True
        result["current"] = jsonable(current)
    except Exception as exc:
        result["detail"] = f"get_image_layout: {type(exc).__name__}: {exc}"
        return result
    try:
        result["default"] = jsonable(source.get_image_layout_default())
    except Exception as exc:
        result["detail"] = f"get_image_layout_default: {type(exc).__name__}: {exc}"
    if not probe_writes:
        result["support"] = "EXPOSED_WRITABLE_NOT_PROBED"
        return result
    try:
        frame, document_number, page_number, frame_number = current
        source.set_image_layout(frame, document_number, page_number, frame_number)
        result["support"] = "EXPOSED_AND_SETTABLE"
    except Exception as exc:
        result["support"] = "EXPOSED_BUT_WRITE_REJECTED"
        result["detail"] = f"set_image_layout: {type(exc).__name__}: {exc}"
    return result


def write_diagnostic_report(
    source: Any,
    source_name: str,
    output_dir: Path,
    probe_writes: bool,
    dsm_name: Optional[str],
) -> tuple[Path, Path]:
    """TWAIN Capability診断をJSON/TXTへ保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"twain_diagnostic_{stamp}.json"
    text_path = output_dir / f"twain_diagnostic_{stamp}.txt"

    name_map = _capability_name_map()
    targets = build_target_capabilities()
    target_ids = {cap_id for cap_id in targets.values() if cap_id is not None}
    supported_ids, supported_error = extract_supported_capability_ids(source)
    capability_ids = sorted(set(supported_ids) | target_ids)
    reports: list[TwainCapabilityReport] = []
    for cap_id in capability_ids:
        target_names = [key for key, value in targets.items() if value == cap_id]
        safe = any(name in SAFE_WRITE_PROBE_NAMES for name in target_names)
        reports.append(
            capability_report(
                source,
                cap_id,
                name_map.get(cap_id, f"CUSTOM_CAP_0x{cap_id:04X}"),
                probe_writes,
                safe,
            )
        )
    by_id = {report.capability_id: report for report in reports}

    target_support: list[TwainTargetSupport] = []
    for setting, cap_id in targets.items():
        if cap_id is None:
            target_support.append(
                TwainTargetSupport(
                    setting=setting,
                    capability_id=None,
                    capability_name="UNAVAILABLE_CONSTANT",
                    exposed=False,
                    current_value=None,
                    allowed=None,
                    support="NOT_DEFINED_BY_PYTWAIN",
                    detail=None,
                )
            )
            continue
        report = by_id.get(cap_id)
        if report is None or report.support == "NOT_EXPOSED_BY_TWAIN":
            target_support.append(
                TwainTargetSupport(
                    setting=setting,
                    capability_id=cap_id,
                    capability_name=name_map.get(cap_id, f"0x{cap_id:04X}"),
                    exposed=False,
                    current_value=None,
                    allowed=None,
                    support="NOT_EXPOSED_BY_TWAIN",
                    detail=report.detail if report else None,
                )
            )
            continue
        target_support.append(
            TwainTargetSupport(
                setting=setting,
                capability_id=cap_id,
                capability_name=report.name,
                exposed=True,
                current_value=report.current_value,
                allowed=report.get_value,
                support=report.support,
                detail=report.detail,
            )
        )

    layout = inspect_image_layout(source, probe_writes)
    try:
        identity = jsonable(source.identity)
    except Exception as exc:
        identity = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        pytwain_version = twain.version() if twain is not None else None
    except Exception:
        pytwain_version = None

    report_data = {
        "generated_at": dt.datetime.now().astimezone().isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "python_bitness": runtime_bitness(),
            "pytwain_version": pytwain_version,
            "dsm_name": dsm_name or automatic_dsm_description(),
            "probe_writes": probe_writes,
        },
        "source": {"name": source_name, "identity": identity},
        "supported_caps_error": supported_error,
        "supported_capability_ids": supported_ids,
        "target_support": [asdict(target) for target in target_support],
        "image_layout": layout,
        "all_twain_capabilities": [asdict(report) for report in reports],
    }
    json_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "fi-65F TWAIN diagnostic report",
        f"Generated: {report_data['generated_at']}",
        f"Source: {source_name}",
        f"Python: {report_data['environment']['python_version']} "
        f"({report_data['environment']['python_bitness']}-bit)",
        f"pytwain: {pytwain_version}",
        f"DSM: {report_data['environment']['dsm_name']}",
        f"Write probes: {'enabled' if probe_writes else 'disabled'}",
        "",
        "Target setting support",
        "----------------------",
    ]
    for target in target_support:
        cap_text = (
            f"{target.capability_name} ({target.capability_id})"
            if target.capability_id is not None
            else target.capability_name
        )
        lines.append(f"{target.setting:20s} {target.support:30s} {cap_text}")
        if target.current_value is not None:
            lines.append(f"  current: {target.current_value!r}")
        if target.allowed is not None:
            lines.append(f"  allowed: {target.allowed!r}")
        if target.detail:
            lines.append(f"  detail : {target.detail}")

    lines.extend(
        [
            "",
            "Image layout",
            "------------",
            f"support: {layout['support']}",
            f"current: {layout['current']!r}",
            f"default: {layout['default']!r}",
            "",
            "All capabilities reported/probed",
            "--------------------------------",
        ]
    )
    if supported_error:
        lines.append(f"CAP_SUPPORTEDCAPS warning: {supported_error}")
    for cap in reports:
        type_label = (
            cap.item_type_name if cap.item_type_name is not None else repr(cap.item_type)
        )
        lines.append(
            f"0x{cap.capability_id:04X} {cap.name} support={cap.support} "
            f"type={type_label} probe={cap.write_probe}"
        )
        lines.append(f"  query_support: {cap.query_support!r}")
        lines.append(f"  current      : {cap.current_value!r}")
        lines.append(f"  default      : {cap.default_value!r}")
        lines.append(f"  allowed      : {cap.get_value!r}")
        if cap.detail:
            lines.append(f"  detail       : {cap.detail}")

    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, text_path


def preferred_item_type(source: Any, capability_id: int, fallback_name: str) -> int:
    """Sourceが返す現在値の型を優先し、取得不能時だけ既知型へフォールバックする。"""
    ok, item_type, _, _ = capability_get(source, capability_id, "get_capability_current")
    if ok and item_type is not None:
        return item_type
    fallback = _const(fallback_name)
    if fallback is None:
        raise RuntimeError(f"TWAIN item type constant is unavailable: {fallback_name}")
    return fallback


def set_capability(
    source: Any,
    capability_name: str,
    requested: Any,
    strict: bool,
    fallback_type: str,
) -> Any:
    """Capabilityを設定し、確認できた実際のread-back値を返す。"""
    if requested is None:
        return None
    cap_id = _const(capability_name)
    if cap_id is None:
        message = f"{capability_name} is unavailable in pytwain constants."
        if strict:
            raise RuntimeError(message)
        logging.warning(message)
        return None

    ok, item_type, current_payload, error = capability_get(
        source, cap_id, "get_capability_current"
    )
    if not ok:
        message = f"{capability_name} is not exposed by this TWAIN source: {error}"
        if strict:
            raise RuntimeError(message + " Run --diagnose to inspect support.")
        logging.warning(message)
        return None

    original = current_scalar(current_payload)
    if item_type is None:
        item_type = preferred_item_type(source, cap_id, fallback_type)

    try:
        source.set_capability(cap_id, item_type, requested)
    except Exception as exc:
        message = (
            f"Could not set {capability_name} to {requested!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        if strict:
            raise RuntimeError(message) from exc
        logging.warning(message)
        return original

    read_ok, _, read_payload, read_error = capability_get(
        source, cap_id, "get_capability_current"
    )
    if not read_ok:
        message = (
            f"{capability_name} accepted requested={requested!r}, but GETCURRENT "
            f"failed: {read_error}"
        )
        if strict:
            raise RuntimeError(message)
        logging.warning(message)
        return None

    readback = current_scalar(read_payload)
    if not _values_equivalent(requested, readback, item_type):
        message = (
            f"{capability_name} requested={requested!r} but source "
            f"read back {jsonable(readback)!r}."
        )
        if strict:
            raise RuntimeError(message)
        logging.warning(message)
    else:
        logging.info(
            "%s requested=%r readback=%r",
            capability_name,
            requested,
            jsonable(readback),
        )
    return readback


def apply_scan_settings(
    source: Any,
    *,
    dpi: float,
    mode: str,
    brightness: Optional[float],
    contrast: Optional[float],
    gamma: Optional[float],
    exposure_time: Optional[float],
    autobright: Optional[bool],
    lamp_state: Optional[bool],
    light_source: Optional[int],
    bit_depth: Optional[int],
    xpos: Optional[int],
    ypos: Optional[int],
    width: Optional[int],
    height: Optional[int],
    strict: bool,
) -> tuple[Any, Any]:
    """TWAIN Capabilityを依存順序で適用し、実際のX/Y解像度を返す。"""
    if twc is None:
        raise RuntimeError("pytwain is unavailable")
    pixel_types = {
        "color": getattr(twc, "TWPT_RGB"),
        "grayscale": getattr(twc, "TWPT_GRAY"),
        "bw": getattr(twc, "TWPT_BW"),
    }
    set_capability(source, "ICAP_PIXELTYPE", pixel_types[mode], strict, "TWTY_UINT16")
    if bit_depth is not None:
        set_capability(source, "ICAP_BITDEPTH", bit_depth, strict, "TWTY_UINT16")

    inches = getattr(twc, "TWUN_INCHES")
    actual_units = set_capability(
        source, "ICAP_UNITS", inches, strict, "TWTY_UINT16"
    )
    actual_dpi_x = set_capability(
        source, "ICAP_XRESOLUTION", float(dpi), strict, "TWTY_FIX32"
    )
    actual_dpi_y = set_capability(
        source, "ICAP_YRESOLUTION", float(dpi), strict, "TWTY_FIX32"
    )
    set_capability(source, "ICAP_AUTOBRIGHT", autobright, strict, "TWTY_BOOL")
    set_capability(source, "ICAP_EXPOSURETIME", exposure_time, strict, "TWTY_FIX32")
    set_capability(source, "ICAP_BRIGHTNESS", brightness, strict, "TWTY_FIX32")
    set_capability(source, "ICAP_CONTRAST", contrast, strict, "TWTY_FIX32")
    set_capability(source, "ICAP_GAMMA", gamma, strict, "TWTY_FIX32")
    set_capability(source, "ICAP_LAMPSTATE", lamp_state, strict, "TWTY_BOOL")
    set_capability(source, "ICAP_LIGHTSOURCE", light_source, strict, "TWTY_UINT16")

    if any(value is not None for value in (xpos, ypos, width, height)):
        if actual_units != inches:
            message = (
                "Cannot safely apply pixel-based scan region because ICAP_UNITS "
                f"could not be confirmed as inches (readback={actual_units!r})."
            )
            if strict:
                raise RuntimeError(message)
            logging.warning(message)
            return actual_dpi_x, actual_dpi_y

        dpi_x = _positive_float(actual_dpi_x)
        dpi_y = _positive_float(actual_dpi_y)
        if dpi_x is None or dpi_y is None:
            message = (
                "Cannot safely apply pixel-based scan region because the actual "
                f"resolution is unknown (x={actual_dpi_x!r}, y={actual_dpi_y!r})."
            )
            if strict:
                raise RuntimeError(message)
            logging.warning(message)
            return actual_dpi_x, actual_dpi_y

        try:
            current = source.get_image_layout()
            frame = list(current[0])
            document_number, page_number, frame_number = current[1:]
        except Exception as exc:
            if strict:
                raise RuntimeError(f"Could not read TWAIN image layout: {exc}") from exc
            logging.warning("Could not read TWAIN image layout: %s", exc)
            return actual_dpi_x, actual_dpi_y

        left, top, right, bottom = [float(value) for value in frame]
        old_width = right - left
        old_height = bottom - top
        if xpos is not None:
            left = float(xpos) / dpi_x
            right = left + old_width
        if ypos is not None:
            top = float(ypos) / dpi_y
            bottom = top + old_height
        if width is not None:
            right = left + float(width) / dpi_x
        if height is not None:
            bottom = top + float(height) / dpi_y
        new_frame = (left, top, right, bottom)
        try:
            source.set_image_layout(
                new_frame, document_number, page_number, frame_number
            )
            logging.info(
                "TWAIN image layout applied: %r using readback dpi=(%s, %s)",
                new_frame,
                dpi_x,
                dpi_y,
            )
        except Exception as exc:
            if strict:
                raise RuntimeError(
                    f"Could not set TWAIN image layout to {new_frame!r}: {exc}"
                ) from exc
            logging.warning("Could not set TWAIN image layout: %s", exc)

    return actual_dpi_x, actual_dpi_y


def save_twain_image_as_jpeg(
    image_object: Any,
    output: Path,
    quality: int,
    mode: str,
    dpi: float,
    dpi_y: Optional[float] = None,
) -> None:
    """pytwain native imageをBMP経由でJPEGへ原子的に保存する。"""
    with tempfile.TemporaryDirectory(prefix="fi65f_twain_") as temp_dir:
        bmp_path = Path(temp_dir) / "capture.bmp"
        image_object.save(str(bmp_path))
        with Image.open(bmp_path) as source:
            source.load()
            if mode == "grayscale":
                converted = source.convert("L")
            elif mode == "bw":
                converted = source.convert("L").point(
                    lambda pixel: 255 if pixel >= 128 else 0, "1"
                )
            else:
                converted = source.convert("RGB")
            try:
                effective_y = float(dpi if dpi_y is None else dpi_y)
                save_pillow_jpeg_atomically(
                    converted,
                    output,
                    quality,
                    dpi=(float(dpi), effective_y),
                )
            finally:
                if converted is not source:
                    converted.close()


def acquire_one(
    source: Any,
    output: Path,
    quality: int,
    mode: str,
    dpi: float,
    show_ui: bool,
) -> None:
    """TWAIN native transferで1画像を取得し、実画像情報をJPEGへ反映する。"""
    captured = False
    transfer_dpi = [float(dpi), float(dpi)]

    def before(image_info: Any) -> None:
        if not isinstance(image_info, dict):
            return
        actual_x = _positive_float(image_info.get("XResolution"))
        actual_y = _positive_float(image_info.get("YResolution"))
        if actual_x is not None:
            transfer_dpi[0] = actual_x
        if actual_y is not None:
            transfer_dpi[1] = actual_y
        logging.info(
            "TWAIN DAT_IMAGEINFO resolution: x=%s y=%s",
            transfer_dpi[0],
            transfer_dpi[1],
        )

    def after(image_object: Any, more: int) -> None:
        nonlocal captured
        try:
            if not captured:
                save_twain_image_as_jpeg(
                    image_object,
                    output,
                    quality,
                    mode,
                    transfer_dpi[0],
                    transfer_dpi[1],
                )
                captured = True
        finally:
            close = getattr(image_object, "close", None)
            if callable(close):
                close()
        if more:
            exc_module = getattr(twain, "exceptions", None)
            cancel_all = getattr(exc_module, "CancelAll", None)
            if cancel_all is not None:
                raise cancel_all

    acquire = source.acquire_natively
    try:
        supports_before = "before" in inspect.signature(acquire).parameters
    except (TypeError, ValueError):
        supports_before = True

    if supports_before:
        acquire(after=after, before=before, show_ui=show_ui, modal=False)
    else:
        # Test doubles and older wrappers may not expose pytwain 2.3's before callback.
        acquire(after=after, show_ui=show_ui, modal=False)

    if not captured:
        raise RuntimeError("The TWAIN source completed without returning an image.")


def main() -> int:
    """診断、Source列挙、またはTWAIN画像取得を実行する。"""
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if os.name != "nt":
        logging.error("This utility supports Windows only.")
        return 2
    if not runtime_dependencies_available():
        logging.error(
            "pytwain and Pillow are required. Run: py -m pip install -r requirements.txt"
        )
        return 2

    config = read_config(Path(args.config))
    try:
        dsm_name = config_value(args, config, "dsm", "twain", "dsm_name", str, None)
        probe_writes = resolve_probe_writes(args, config)
        autobright_text = config_value(
            args, config, "autobright", "twain", "autobright", str, None
        )
        lamp_state_text = config_value(
            args, config, "lamp_state", "twain", "lamp_state", str, None
        )
        autobright = _bool_value(autobright_text)
        lamp_state = _bool_value(lamp_state_text)
    except (ValueError, Exception) as exc:
        # ConfigParser boolean errors and invalid on/off values are usage/config errors.
        logging.error("Configuration error: %s", exc)
        return 2

    if args.list_devices:
        try:
            return list_devices(dsm_name)
        except Exception as exc:
            logging.error("%s", exc)
            if args.verbose:
                logging.exception("Detailed failure")
            return 1

    try:
        device_name = config_value(
            args, config, "device", "scanner", "device", str, None
        )
        output_dir = Path(
            config_value(
                args, config, "output_dir", "output", "directory", str, "./jpeg"
            )
        )
        diagnostic_dir = Path(
            config_value(
                args,
                config,
                "diagnostic_dir",
                "diagnostics",
                "directory",
                str,
                "./diagnostics",
            )
        )
        dpi = config_value(args, config, "dpi", "scan", "dpi", float, 600.0)
        brightness = config_value(
            args, config, "brightness", "scan", "brightness", float, None
        )
        contrast = config_value(
            args, config, "contrast", "scan", "contrast", float, None
        )
        mode = config_value(args, config, "mode", "scan", "mode", str, "color").lower()
        xpos = config_value(args, config, "xpos", "region", "xpos", int, None)
        ypos = config_value(args, config, "ypos", "region", "ypos", int, None)
        width = config_value(args, config, "width", "region", "width", int, None)
        height = config_value(args, config, "height", "region", "height", int, None)
        jpeg_quality = config_value(
            args, config, "jpeg_quality", "output", "jpeg_quality", int, 95
        )
        gamma = config_value(args, config, "gamma", "twain", "gamma", float, None)
        exposure_time = config_value(
            args, config, "exposure_time", "twain", "exposure_time", float, None
        )
        light_source = config_value(
            args, config, "light_source", "twain", "light_source", int, None
        )
        bit_depth = config_value(
            args, config, "bit_depth", "twain", "bit_depth", int, None
        )
        config_show_ui = (
            config.getboolean("scanner", "show_ui")
            if config.has_option("scanner", "show_ui")
            else False
        )
        show_ui = args.show_ui or config_show_ui
        config_strict = (
            config.getboolean("scanner", "strict_settings")
            if config.has_option("scanner", "strict_settings")
            else True
        )
        strict = config_strict and not args.non_strict
    except Exception as exc:
        logging.error("Configuration error: %s", exc)
        return 2

    if mode not in {"color", "grayscale", "bw"}:
        logging.error("Configuration error: mode must be color, grayscale, or bw")
        return 2
    if dpi <= 0:
        logging.error("Configuration error: dpi must be positive")
        return 2

    manager = None
    source = None
    reserved_output: Optional[Path] = None
    try:
        manager = create_source_manager(dsm_name)
        source = select_source(manager, device_name)
        source_name = str(getattr(source, "name", device_name or "unknown"))
        if args.diagnose:
            json_path, text_path = write_diagnostic_report(
                source, source_name, diagnostic_dir, probe_writes, dsm_name
            )
            print(f"JSON: {json_path.resolve()}")
            print(f"TEXT: {text_path.resolve()}")
            return 0

        apply_scan_settings(
            source,
            dpi=float(dpi),
            mode=mode,
            brightness=brightness,
            contrast=contrast,
            gamma=gamma,
            exposure_time=exposure_time,
            autobright=autobright,
            lamp_state=lamp_state,
            light_source=light_source,
            bit_depth=bit_depth,
            xpos=xpos,
            ypos=ypos,
            width=width,
            height=height,
            strict=strict,
        )
        reserved_output = reserve_output_path(output_dir)
        logging.info("Starting TWAIN transfer...")
        acquire_one(
            source,
            reserved_output,
            jpeg_quality,
            mode,
            float(dpi),
            show_ui,
        )
        print(reserved_output.resolve())
        return 0
    except Exception as exc:
        remove_empty_reservation(reserved_output)
        logging.error("%s", exc)
        if args.verbose:
            logging.exception("Detailed failure")
        return 1
    finally:
        if source is not None:
            try:
                source.close()
            except Exception:
                logging.debug("TWAIN source close failed", exc_info=True)
        if manager is not None:
            try:
                manager.close()
            except Exception:
                logging.debug("TWAIN manager close failed", exc_info=True)


if __name__ == "__main__":
    raise SystemExit(main())