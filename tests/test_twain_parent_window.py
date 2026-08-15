from __future__ import annotations

import pytest

import twain_capture as target


class FakeParent:
    def __init__(self):
        self.destroyed = False

    def winfo_id(self):
        return 0x1234

    def destroy(self):
        self.destroyed = True


class FakeManager:
    def __init__(self):
        self.source_list = []
        self.closed = False

    def close(self):
        self.closed = True


def test_create_source_manager_keeps_hidden_parent_until_close_helper(monkeypatch):
    parent = FakeParent()
    manager = FakeManager()
    captured = {}

    monkeypatch.setattr(target, "_create_hidden_parent_window", lambda: parent)

    def source_manager(**kwargs):
        captured.update(kwargs)
        return manager

    monkeypatch.setattr(target.twain, "SourceManager", source_manager)

    returned = target.create_source_manager(None)

    assert returned is manager
    assert captured["parent_window"] is parent
    assert captured["ProductName"] == "scanner_camera"
    assert parent.destroyed is False
    assert target._TWAIN_PARENT_WINDOWS[id(manager)] is parent

    target.close_source_manager(manager)

    assert manager.closed is True
    assert parent.destroyed is True
    assert id(manager) not in target._TWAIN_PARENT_WINDOWS


def test_create_source_manager_forwards_explicit_dsm(monkeypatch):
    parent = FakeParent()
    manager = FakeManager()
    captured = {}

    monkeypatch.setattr(target, "_create_hidden_parent_window", lambda: parent)

    def source_manager(**kwargs):
        captured.update(kwargs)
        return manager

    monkeypatch.setattr(target.twain, "SourceManager", source_manager)

    returned = target.create_source_manager(r"C:\TWAIN\TWAINDSM.dll")
    try:
        assert returned is manager
        assert captured["dsm_name"] == r"C:\TWAIN\TWAINDSM.dll"
    finally:
        target.close_source_manager(manager)


def test_create_source_manager_destroys_parent_if_dsm_open_fails(monkeypatch):
    parent = FakeParent()
    monkeypatch.setattr(target, "_create_hidden_parent_window", lambda: parent)

    def source_manager(**kwargs):
        del kwargs
        raise RuntimeError("DSM open failed")

    monkeypatch.setattr(target.twain, "SourceManager", source_manager)

    with pytest.raises(RuntimeError, match="DSM open failed"):
        target.create_source_manager(None)

    assert parent.destroyed is True


def test_close_source_manager_destroys_parent_even_if_manager_close_fails():
    parent = FakeParent()

    class BrokenManager:
        def close(self):
            raise RuntimeError("close failed")

    manager = BrokenManager()
    target._TWAIN_PARENT_WINDOWS[id(manager)] = parent

    with pytest.raises(RuntimeError, match="close failed"):
        target.close_source_manager(manager)

    assert parent.destroyed is True
    assert id(manager) not in target._TWAIN_PARENT_WINDOWS


def test_close_source_manager_without_registered_parent_still_closes_manager():
    manager = FakeManager()
    target.close_source_manager(manager)
    assert manager.closed is True


def test_exception_text_uses_repr_for_empty_twain_error():
    class EmptyError(Exception):
        def __str__(self):
            return ""

    text = target._exception_text(EmptyError())
    assert text.startswith("EmptyError(")
