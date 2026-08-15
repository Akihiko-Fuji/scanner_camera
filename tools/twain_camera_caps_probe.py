#!/usr/bin/env python3
"""Probe scanner-camera-relevant TWAIN capabilities with process isolation.

Some PaperStream IP DAT_CAPABILITY calls can block indefinitely inside the
native driver. Python exceptions and thread timeouts cannot reliably interrupt
such calls, so each target capability is probed in a separate child process.
The parent enforces a timeout, terminates a blocked child, and preserves the
last checkpoint written by that child.

The probe is intentionally limited to the four camera controls currently
needed by scanner_camera and never calls MSG_GETDEFAULT.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

# Direct execution as ``py tools\\twain_camera_caps_probe.py`` sets sys.path[0]
# to ``tools``. Add the repository root explicitly before importing the sibling
# module so the documented command works outside pytest/package imports too.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import twain_capture as tc  # noqa: E402


TARGETS = (
    "ICAP_EXPOSURETIME",
    "ICAP_AUTOBRIGHT",
    "ICAP_LAMPSTATE",
    "ICAP_LIGHTSOURCE",
)
DEFAULT_TIMEOUT_SECONDS = 8.0


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
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Maximum wall time for one capability child process (default: 8 seconds)",
    )
    parser.add_argument(
        "--diagnostic-dir",
        default="./diagnostics",
        help="Directory for incremental JSON/TXT reports",
    )
    parser.add_argument("--verbose", action="store_true")

    # Internal worker arguments. They are deliberately hidden from normal help.
    parser.add_argument("--worker-capability", choices=TARGETS, help=argparse.SUPPRESS)
    parser.add_argument("--worker-result", help=argparse.SUPPRESS)
    return parser


def _format_error(error: Optional[str]) -> str:
    return error or "unknown error"


def _new_result(capability_name: str) -> dict[str, Any]:
    cap_id = tc._const(capability_name)
    return {
        "name": capability_name,
        "capability_id": cap_id,
        "status": "RUNNING",
        "stage": "START",
        "query_support": None,
        "get": None,
        "current": None,
        "item_type": None,
        "write_probe": "NOT_REQUESTED",
        "detail": None,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(temp), str(path))


def probe_target(
    source: Any,
    capability_name: str,
    probe_writes: bool,
    checkpoint: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Probe one target without GETDEFAULT.

    GETCURRENT is attempted first because it is the most useful acquisition
    setting evidence. GET follows for allowed/range information, and
    QUERYSUPPORT is deliberately last because field testing showed that it can
    also block inside PaperStream IP.
    """
    result = _new_result(capability_name)
    cap_id = result["capability_id"]

    def save(stage: str) -> None:
        result["stage"] = stage
        if checkpoint is not None:
            checkpoint(dict(result))

    if cap_id is None:
        result["status"] = "COMPLETE"
        result["stage"] = "COMPLETE"
        result["detail"] = "constant is unavailable in pytwain"
        if checkpoint is not None:
            checkpoint(dict(result))
        return result

    logging.info("Probing %s (0x%04X) without GETDEFAULT", capability_name, cap_id)
    errors = []

    save("GETCURRENT")
    cur_ok, cur_type, cur_payload, cur_error = tc.capability_get(
        source, cap_id, "get_capability_current"
    )
    result["current"] = tc.jsonable(cur_payload) if cur_ok else None
    result["item_type"] = cur_type
    if not cur_ok:
        errors.append(f"GETCURRENT: {_format_error(cur_error)}")
    save("GETCURRENT_DONE")

    save("GET")
    get_ok, get_type, get_payload, get_error = tc.capability_get(
        source, cap_id, "get_capability"
    )
    result["get"] = tc.jsonable(get_payload) if get_ok else None
    if result["item_type"] is None:
        result["item_type"] = get_type
    if not get_ok:
        errors.append(f"GET: {_format_error(get_error)}")
    save("GET_DONE")

    if probe_writes:
        scalar = tc.current_scalar(cur_payload) if cur_ok else None
        item_type = result["item_type"]
        if not cur_ok or scalar is None or item_type is None:
            result["write_probe"] = "NOT_POSSIBLE"
        else:
            save("SET_NO_CHANGE")
            try:
                source.set_capability(cap_id, item_type, scalar)
                save("SET_NO_CHANGE_DONE")
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
                save("SET_READBACK_DONE")
            except Exception as exc:
                result["write_probe"] = "FAILED"
                errors.append(f"SET: {type(exc).__name__}: {tc._exception_text(exc)}")
                save("SET_FAILED")

    save("QUERYSUPPORT")
    result["query_support"] = tc.query_support(source, cap_id)
    save("QUERYSUPPORT_DONE")

    result["status"] = "COMPLETE"
    result["stage"] = "COMPLETE"
    result["detail"] = " | ".join(errors) if errors else None
    if checkpoint is not None:
        checkpoint(dict(result))
    return result


def print_result(result: dict[str, Any]) -> None:
    cap_id = result.get("capability_id")
    id_text = "unavailable" if cap_id is None else f"0x{cap_id:04X} ({cap_id})"
    print(f"\n{result['name']}  {id_text}")
    print(f"  status       : {result.get('status')}")
    print(f"  last_stage   : {result.get('stage')}")
    print(f"  query_support: {result.get('query_support')!r}")
    print(f"  item_type    : {result.get('item_type')!r}")
    print(f"  current      : {result.get('current')!r}")
    print(f"  allowed(GET) : {result.get('get')!r}")
    print(f"  write_probe  : {result.get('write_probe')}")
    if result.get("detail"):
        print(f"  detail       : {result['detail']}")


def _worker_main(args: argparse.Namespace) -> int:
    """Run one capability in a disposable process and checkpoint progress."""
    if not args.worker_result:
        print("--worker-result is required in worker mode", file=sys.stderr)
        return 2

    result_path = Path(args.worker_result)
    state = _new_result(args.worker_capability)
    manager = None
    source = None

    def checkpoint(payload: dict[str, Any]) -> None:
        _atomic_write_json(result_path, payload)

    try:
        state["stage"] = "OPEN_DSM"
        checkpoint(state)
        manager = tc.create_source_manager(args.dsm)
        state["stage"] = "OPEN_SOURCE"
        checkpoint(state)
        source = tc.select_source(manager, args.device)
        state = probe_target(source, args.worker_capability, args.probe_writes, checkpoint)
        checkpoint(state)
        return 0
    except Exception as exc:
        state["status"] = "ERROR"
        state["detail"] = f"{type(exc).__name__}: {tc._exception_text(exc)}"
        checkpoint(state)
        return 1
    finally:
        # Cleanup itself is allowed to block in a broken native driver. The
        # parent timeout covers the entire child lifetime and will terminate the
        # process if CLOSEDS/CLOSEDSM does not return.
        if source is not None:
            try:
                source.close()
            except Exception:
                pass
        if manager is not None:
            try:
                tc.close_source_manager(manager)
            except Exception:
                pass


def _read_checkpoint(path: Path, capability_name: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    result = _new_result(capability_name)
    result["status"] = "NO_CHECKPOINT"
    result["detail"] = "worker produced no readable checkpoint"
    return result


def _run_target_subprocess(
    capability_name: str,
    args: argparse.Namespace,
    work_dir: Path,
) -> dict[str, Any]:
    checkpoint_path = work_dir / f".{capability_name.lower()}_{os.getpid()}.json"
    try:
        checkpoint_path.unlink()
    except FileNotFoundError:
        pass

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-capability",
        capability_name,
        "--worker-result",
        str(checkpoint_path.resolve()),
        "--device",
        args.device,
    ]
    if args.dsm:
        command.extend(["--dsm", args.dsm])
    if args.probe_writes:
        command.append("--probe-writes")
    if args.verbose:
        command.append("--verbose")

    logging.info(
        "Starting isolated probe for %s (timeout %.1fs)",
        capability_name,
        args.timeout_seconds,
    )
    timed_out = False
    completed = None
    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=args.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        timed_out = True

    result = _read_checkpoint(checkpoint_path, capability_name)
    last_stage = result.get("stage", "UNKNOWN")

    if timed_out:
        if result.get("status") == "COMPLETE":
            result["status"] = "COMPLETE_CLEANUP_TIMEOUT"
            suffix = (
                f"child exceeded {args.timeout_seconds:.1f}s after completing capability; "
                "native cleanup was terminated"
            )
        else:
            result["status"] = "TIMEOUT"
            suffix = (
                f"child exceeded {args.timeout_seconds:.1f}s during {last_stage}; "
                "process was terminated"
            )
        result["detail"] = " | ".join(
            part for part in (result.get("detail"), suffix) if part
        )
        # Give Windows a short interval to release the terminated driver's
        # process-owned handles before opening the next isolated session.
        time.sleep(0.25)
    elif completed is not None and completed.returncode != 0 and result.get("status") == "RUNNING":
        result["status"] = "ERROR"
        stderr = (completed.stderr or "").strip()
        result["detail"] = stderr or f"worker exited with code {completed.returncode}"

    if args.verbose and completed is not None:
        if completed.stdout:
            logging.debug("worker stdout for %s:\n%s", capability_name, completed.stdout.rstrip())
        if completed.stderr:
            logging.debug("worker stderr for %s:\n%s", capability_name, completed.stderr.rstrip())

    try:
        checkpoint_path.unlink()
    except FileNotFoundError:
        pass
    return result


def _write_reports(
    output_dir: Path,
    stamp: str,
    results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"twain_camera_caps_{stamp}.json"
    text_path = output_dir / f"twain_camera_caps_{stamp}.txt"

    try:
        pytwain_version = tc.twain.version() if tc.twain is not None else None
    except Exception:
        pytwain_version = None

    payload = {
        "generated_at": dt.datetime.now().astimezone().isoformat(),
        "device": args.device,
        "python_version": sys.version.split()[0],
        "python_bitness": tc.runtime_bitness(),
        "pytwain_version": pytwain_version,
        "dsm": args.dsm or tc.automatic_dsm_description(),
        "timeout_seconds": args.timeout_seconds,
        "probe_writes": args.probe_writes,
        "targets": results,
    }
    _atomic_write_json(json_path, payload)

    lines = [
        "fi-65F targeted TWAIN camera capability probe",
        f"Generated: {payload['generated_at']}",
        f"Device: {args.device}",
        f"Python: {payload['python_version']} ({payload['python_bitness']}-bit)",
        f"pytwain: {pytwain_version}",
        f"DSM: {payload['dsm']}",
        f"Per-capability timeout: {args.timeout_seconds:.1f}s",
        f"Write probes: {'enabled' if args.probe_writes else 'disabled'}",
        "",
    ]
    for result in results:
        cap_id = result.get("capability_id")
        id_text = "unavailable" if cap_id is None else f"0x{cap_id:04X} ({cap_id})"
        lines.extend(
            [
                f"{result['name']} {id_text}",
                f"  status       : {result.get('status')}",
                f"  last_stage   : {result.get('stage')}",
                f"  query_support: {result.get('query_support')!r}",
                f"  item_type    : {result.get('item_type')!r}",
                f"  current      : {result.get('current')!r}",
                f"  allowed(GET) : {result.get('get')!r}",
                f"  write_probe  : {result.get('write_probe')}",
                f"  detail       : {result.get('detail')}",
                "",
            ]
        )
    text_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, text_path


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

    if args.worker_capability:
        # Keep normal worker logs quiet; the parent records structured state.
        if not args.verbose:
            logging.getLogger().setLevel(logging.WARNING)
        return _worker_main(args)

    if args.timeout_seconds <= 0:
        print("--timeout-seconds must be positive", file=sys.stderr)
        return 2

    output_dir = Path(args.diagnostic_dir)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    results: list[dict[str, Any]] = []
    json_path, text_path = _write_reports(output_dir, stamp, results, args)
    print(f"JSON: {json_path.resolve()}")
    print(f"TEXT: {text_path.resolve()}")

    try:
        for capability_name in TARGETS:
            result = _run_target_subprocess(capability_name, args, output_dir)
            results.append(result)
            _write_reports(output_dir, stamp, results, args)
            print_result(result)
    except KeyboardInterrupt:
        _write_reports(output_dir, stamp, results, args)
        print("\nInterrupted. Partial diagnostic files were preserved.", file=sys.stderr)
        return 130

    incomplete = any(
        result.get("status") not in {"COMPLETE", "COMPLETE_CLEANUP_TIMEOUT"}
        for result in results
    )
    return 1 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
