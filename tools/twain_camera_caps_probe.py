#!/usr/bin/env python3
"""Probe scanner-camera-relevant TWAIN capabilities without exhaustive diagnostics.

PaperStream IP can block indefinitely on some DAT_CAPABILITY operations such as
MSG_GETDEFAULT. This tool intentionally probes only the four camera controls we
currently need and never calls GETDEFAULT.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, Optional

import twain_capture as tc


TARGETS = (
    "ICAP_EXPOSURETIME",
    "ICAP_AUTOBRIGHT",
    "ICAP_LAMPSTATE",
    "ICAP_LIGHTSOURCE",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe ICAP_EXPOSURETIME, ICAP_AUTOBRIGHT, ICAP_LAMPSTATE and "
            "ICAP_LIGHTSOURCE without GETDEFAULT or exhaustive capability scans."
        )
    )
    parser.add_argument(
        "--device",
        default="PaperStream IP fi-65F",
        help="TWAIN source name or unique substring",
    )
    parser.add_argument(
        "--dsm",
        help="Explicit TWAIN DSM DLL; normally leave unset for pytwain auto-selection",
    )
    parser.add_argument(
        "--probe-writes",
        action="store_true",
        help="Perform no-change SET followed by GETCURRENT on each readable target",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def _format_error(error: Optional[str]) -> str:
    return error or "unknown error"


def probe_target(source: Any, capability_name: str, probe_writes: bool) -> dict[str, Any]:
    cap_id = tc._const(capability_name)
    result: dict[str, Any] = {
        "name": capability_name,
        "capability_id": cap_id,
        "query_support": None,
        "get": None,
        "current": None,
        "item_type": None,
        "write_probe": "NOT_REQUESTED",
        "detail": None,
    }
    if cap_id is None:
        result["detail"] = "constant is unavailable in pytwain"
        return result

    logging.info("Probing %s (0x%04X) without GETDEFAULT", capability_name, cap_id)
    result["query_support"] = tc.query_support(source, cap_id)

    get_ok, get_type, get_payload, get_error = tc.capability_get(
        source, cap_id, "get_capability"
    )
    cur_ok, cur_type, cur_payload, cur_error = tc.capability_get(
        source, cap_id, "get_capability_current"
    )

    result["get"] = tc.jsonable(get_payload) if get_ok else None
    result["current"] = tc.jsonable(cur_payload) if cur_ok else None
    result["item_type"] = cur_type if cur_type is not None else get_type

    errors = []
    if not get_ok:
        errors.append(f"GET: {_format_error(get_error)}")
    if not cur_ok:
        errors.append(f"GETCURRENT: {_format_error(cur_error)}")

    if probe_writes:
        scalar = tc.current_scalar(cur_payload) if cur_ok else None
        item_type = result["item_type"]
        if not cur_ok or scalar is None or item_type is None:
            result["write_probe"] = "NOT_POSSIBLE"
        else:
            try:
                source.set_capability(cap_id, item_type, scalar)
                read_ok, _, read_payload, read_error = tc.capability_get(
                    source, cap_id, "get_capability_current"
                )
                if not read_ok:
                    result["write_probe"] = "READBACK_FAILED"
                    errors.append(f"SET readback: {_format_error(read_error)}")
                else:
                    readback = tc.current_scalar(read_payload)
                    result["write_probe"] = (
                        "OK"
                        if tc._values_equivalent(scalar, readback, item_type)
                        else "ADJUSTED"
                    )
                    result["current"] = tc.jsonable(read_payload)
            except Exception as exc:
                result["write_probe"] = "FAILED"
                errors.append(f"SET: {type(exc).__name__}: {tc._exception_text(exc)}")

    result["detail"] = " | ".join(errors) if errors else None
    return result


def print_result(result: dict[str, Any]) -> None:
    cap_id = result["capability_id"]
    id_text = "unavailable" if cap_id is None else f"0x{cap_id:04X} ({cap_id})"
    print(f"\n{result['name']}  {id_text}")
    print(f"  query_support: {result['query_support']!r}")
    print(f"  item_type    : {result['item_type']!r}")
    print(f"  current      : {result['current']!r}")
    print(f"  allowed(GET) : {result['get']!r}")
    print(f"  write_probe  : {result['write_probe']}")
    if result["detail"]:
        print(f"  detail       : {result['detail']}")


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if os.name != "nt":
        print("This utility supports Windows only.", file=sys.stderr)
        return 2
    if not tc.runtime_dependencies_available():
        print("pytwain and Pillow are required.", file=sys.stderr)
        return 2

    manager = None
    source = None
    try:
        manager = tc.create_source_manager(args.dsm)
        source = tc.select_source(manager, args.device)
        for capability_name in TARGETS:
            result = probe_target(source, capability_name, args.probe_writes)
            print_result(result)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted while the TWAIN driver was processing a capability.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(
            f"{type(exc).__name__}: {tc._exception_text(exc)}",
            file=sys.stderr,
        )
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
                tc.close_source_manager(manager)
            except Exception:
                logging.debug("TWAIN manager close failed", exc_info=True)


if __name__ == "__main__":
    raise SystemExit(main())
