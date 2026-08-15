#!/usr/bin/env python3
"""TWAIN DSMのMSG_OPENDSM失敗をparent HWND有無で切り分ける実機診断。

既存の``twain_capture.py``は現時点で``parent_window=0``を渡している。
一方、pytwain 2.3.0の高水準``acquire()``はparent windowが無い場合にTk windowを
生成してからSourceManagerを開くため、fi-65F実機環境で有効なwindow handleの有無が
DSM open成否へ影響するかを、このスクリプトでproduction codeを変更せず確認する。

この診断はDSMを開いてSource名を列挙するだけで、Data Sourceを開かず、Capabilityの
SETや画像取得は行わない。
"""

from __future__ import annotations

import argparse
import logging
import platform
import struct
import sys
from typing import Any, Optional

try:
    import twain
except ImportError:  # pragma: no cover - 実機診断専用
    twain = None


def runtime_bitness() -> int:
    return struct.calcsize("P") * 8


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe TWAIN DSM open with a hidden Tk parent or HWND=0."
    )
    parser.add_argument(
        "--zero-parent",
        action="store_true",
        help="Use parent_window=0 to reproduce the legacy behavior",
    )
    parser.add_argument(
        "--dsm",
        help="Explicit DSM DLL path/name; normally leave unset for pytwain auto-selection",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def _exception_text(exc: BaseException) -> str:
    text = str(exc).strip()
    return text if text else repr(exc)


def _source_manager(parent_window: Any, dsm_name: Optional[str]) -> Any:
    if twain is None:
        raise RuntimeError("pytwain is not installed")
    kwargs = {
        "parent_window": parent_window,
        "ProductName": "scanner_camera",
        "ProductFamily": "scanner camera",
        "Manufacturer": "scanner_camera",
    }
    if dsm_name:
        kwargs["dsm_name"] = dsm_name
    return twain.SourceManager(**kwargs)


def _probe(parent_window: Any, label: str, dsm_name: Optional[str]) -> int:
    manager = None
    try:
        logging.info("Opening DSM with %s", label)
        manager = _source_manager(parent_window, dsm_name)
        logging.info("DSM opened successfully with %s", label)
        names = [str(name) for name in manager.source_list]
        if names:
            for index, name in enumerate(names, start=1):
                print("[{}] {}".format(index, name))
        else:
            print("DSM opened, but no TWAIN sources were enumerated.")
        return 0
    except Exception as exc:
        print(
            "DSM open/list failed: {}: {}".format(
                type(exc).__name__, _exception_text(exc)
            ),
            file=sys.stderr,
        )
        cause = getattr(exc, "__cause__", None)
        if cause is not None:
            print(
                "cause: {}: {}".format(type(cause).__name__, _exception_text(cause)),
                file=sys.stderr,
            )
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.exception("Detailed DSM probe failure")
        return 1
    finally:
        if manager is not None:
            try:
                manager.close()
            except Exception:
                logging.debug("TWAIN manager close failed", exc_info=True)


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    print("Python: {} ({}-bit)".format(platform.python_version(), runtime_bitness()))
    if twain is None:
        print("pytwain is not installed", file=sys.stderr)
        return 2
    try:
        version = twain.version()
    except Exception:
        version = "unknown"
    print("pytwain: {}".format(version))

    if args.zero_parent:
        print("Parent: HWND=0")
        return _probe(0, "HWND=0", args.dsm)

    try:
        import tkinter as tk
    except ImportError as exc:
        print("tkinter is unavailable: {}".format(exc), file=sys.stderr)
        return 2

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        hwnd = int(root.winfo_id())
        if hwnd == 0:
            print("Tk returned HWND=0", file=sys.stderr)
            return 2
        print("Parent: hidden Tk HWND=0x{:X}".format(hwnd))
        return _probe(root, "hidden Tk parent", args.dsm)
    except Exception as exc:
        print(
            "Could not create hidden Tk parent: {}: {}".format(
                type(exc).__name__, _exception_text(exc)
            ),
            file=sys.stderr,
        )
        if args.verbose:
            logging.exception("Detailed parent-window creation failure")
        return 2
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                logging.debug("Tk parent destroy failed", exc_info=True)


if __name__ == "__main__":
    raise SystemExit(main())
