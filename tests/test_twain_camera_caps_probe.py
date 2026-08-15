from __future__ import annotations

import subprocess
from types import SimpleNamespace

from tools import twain_camera_caps_probe as target


class FakeSource:
    def __init__(self):
        self.set_calls = []

    def set_capability(self, cap_id, item_type, value):
        self.set_calls.append((cap_id, item_type, value))


def test_probe_target_never_requests_getdefault(monkeypatch):
    source = FakeSource()
    calls = []

    monkeypatch.setattr(target.tc, "_const", lambda name: 0x1234)
    monkeypatch.setattr(target.tc, "query_support", lambda source, cap: 0x000F)

    def capability_get(selected, cap_id, method_name):
        del selected, cap_id
        calls.append(method_name)
        if method_name == "get_capability_current":
            return True, 7, 1.0, None
        if method_name == "get_capability":
            return True, 7, [1.0, 2.0], None
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(target.tc, "capability_get", capability_get)
    monkeypatch.setattr(target.tc, "jsonable", lambda value: value)

    result = target.probe_target(source, "ICAP_EXPOSURETIME", False)

    assert calls == ["get_capability_current", "get_capability"]
    assert "get_capability_default" not in calls
    assert result["current"] == 1.0
    assert result["get"] == [1.0, 2.0]
    assert result["query_support"] == 0x000F
    assert result["status"] == "COMPLETE"
    assert source.set_calls == []


def test_probe_target_checkpoints_before_each_native_operation(monkeypatch):
    source = FakeSource()
    stages = []

    monkeypatch.setattr(target.tc, "_const", lambda name: 0x1234)
    monkeypatch.setattr(
        target.tc,
        "capability_get",
        lambda selected, cap_id, method_name: (True, 7, 1.0, None),
    )
    monkeypatch.setattr(target.tc, "query_support", lambda source, cap: 0x000F)
    monkeypatch.setattr(target.tc, "jsonable", lambda value: value)

    target.probe_target(
        source,
        "ICAP_EXPOSURETIME",
        False,
        checkpoint=lambda result: stages.append(result["stage"]),
    )

    assert "GETCURRENT" in stages
    assert "GET" in stages
    assert "QUERYSUPPORT" in stages
    assert stages[-1] == "COMPLETE"


def test_probe_target_write_probe_is_no_change_set_and_readback(monkeypatch):
    source = FakeSource()
    reads = iter([1.5, 1.5])

    monkeypatch.setattr(target.tc, "_const", lambda name: 0x2345)
    monkeypatch.setattr(target.tc, "query_support", lambda source, cap: 0x000F)

    def capability_get(selected, cap_id, method_name):
        del selected, cap_id
        if method_name == "get_capability_current":
            return True, 7, next(reads), None
        if method_name == "get_capability":
            return True, 7, [1.0, 1.5, 2.0], None
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(target.tc, "capability_get", capability_get)
    monkeypatch.setattr(target.tc, "current_scalar", lambda value: value)
    monkeypatch.setattr(target.tc, "jsonable", lambda value: value)
    monkeypatch.setattr(target.tc, "_values_equivalent", lambda a, b, item_type: a == b)

    result = target.probe_target(source, "ICAP_EXPOSURETIME", True)

    assert source.set_calls == [(0x2345, 7, 1.5)]
    assert result["write_probe"] == "OK"
    assert result["current"] == 1.5


def test_probe_target_reports_unavailable_constant(monkeypatch):
    monkeypatch.setattr(target.tc, "_const", lambda name: None)

    result = target.probe_target(SimpleNamespace(), "ICAP_LAMPSTATE", False)

    assert result["capability_id"] is None
    assert result["status"] == "COMPLETE"
    assert "unavailable" in result["detail"]


def _parent_args(**overrides):
    values = {
        "device": "PaperStream IP fi-65F",
        "dsm": None,
        "probe_writes": False,
        "timeout_seconds": 0.01,
        "verbose": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_subprocess_timeout_preserves_last_stage(tmp_path, monkeypatch):
    checkpoint = target._new_result("ICAP_LAMPSTATE")
    checkpoint["stage"] = "GETCURRENT"

    monkeypatch.setattr(
        target,
        "_read_checkpoint",
        lambda path, capability_name: dict(checkpoint),
    )
    monkeypatch.setattr(
        target.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="probe", timeout=0.01)
        ),
    )
    monkeypatch.setattr(target.time, "sleep", lambda seconds: None)

    result = target._run_target_subprocess(
        "ICAP_LAMPSTATE", _parent_args(), tmp_path
    )

    assert result["status"] == "TIMEOUT"
    assert result["stage"] == "GETCURRENT"
    assert "during GETCURRENT" in result["detail"]


def test_cleanup_timeout_keeps_completed_capability_result(tmp_path, monkeypatch):
    checkpoint = target._new_result("ICAP_AUTOBRIGHT")
    checkpoint.update({"status": "COMPLETE", "stage": "COMPLETE", "current": True})

    monkeypatch.setattr(
        target,
        "_read_checkpoint",
        lambda path, capability_name: dict(checkpoint),
    )
    monkeypatch.setattr(
        target.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="probe", timeout=0.01)
        ),
    )
    monkeypatch.setattr(target.time, "sleep", lambda seconds: None)

    result = target._run_target_subprocess(
        "ICAP_AUTOBRIGHT", _parent_args(), tmp_path
    )

    assert result["status"] == "COMPLETE_CLEANUP_TIMEOUT"
    assert result["current"] is True
    assert "cleanup" in result["detail"]


def test_write_reports_creates_incremental_json_and_text(tmp_path):
    args = _parent_args(timeout_seconds=8.0)
    result = target._new_result("ICAP_EXPOSURETIME")
    result.update({"status": "TIMEOUT", "stage": "QUERYSUPPORT"})

    json_path, text_path = target._write_reports(
        tmp_path, "20260815_120000", [result], args
    )

    assert json_path.exists()
    assert text_path.exists()
    text = text_path.read_text(encoding="utf-8")
    assert "ICAP_EXPOSURETIME" in text
    assert "TIMEOUT" in text
