from __future__ import annotations

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
        if method_name == "get_capability":
            return True, 7, [1.0, 2.0], None
        if method_name == "get_capability_current":
            return True, 7, 1.0, None
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(target.tc, "capability_get", capability_get)
    monkeypatch.setattr(target.tc, "jsonable", lambda value: value)

    result = target.probe_target(source, "ICAP_EXPOSURETIME", False)

    assert calls == ["get_capability", "get_capability_current"]
    assert "get_capability_default" not in calls
    assert result["current"] == 1.0
    assert result["get"] == [1.0, 2.0]
    assert source.set_calls == []


def test_probe_target_write_probe_is_no_change_set_and_readback(monkeypatch):
    source = FakeSource()
    reads = iter([1.5, 1.5])

    monkeypatch.setattr(target.tc, "_const", lambda name: 0x2345)
    monkeypatch.setattr(target.tc, "query_support", lambda source, cap: 0x000F)

    def capability_get(selected, cap_id, method_name):
        del selected, cap_id
        if method_name == "get_capability":
            return True, 7, [1.0, 1.5, 2.0], None
        if method_name == "get_capability_current":
            return True, 7, next(reads), None
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
    assert "unavailable" in result["detail"]
