from types import SimpleNamespace

from tools import twain_dsm_probe as probe


def test_source_manager_preserves_parent_window_and_identity(monkeypatch):
    captured = {}

    def source_manager(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(probe, "twain", SimpleNamespace(SourceManager=source_manager))
    parent = object()

    probe._source_manager(parent, None)

    assert captured["parent_window"] is parent
    assert captured["ProductName"] == "scanner_camera"
    assert captured["ProductFamily"] == "scanner camera"
    assert captured["Manufacturer"] == "scanner_camera"
    assert "dsm_name" not in captured


def test_source_manager_passes_explicit_dsm(monkeypatch):
    captured = {}

    def source_manager(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(probe, "twain", SimpleNamespace(SourceManager=source_manager))

    probe._source_manager(1234, r"C:\\Windows\\twain_32.dll")

    assert captured["parent_window"] == 1234
    assert captured["dsm_name"] == r"C:\\Windows\\twain_32.dll"


def test_exception_text_keeps_exception_type_visible_for_blank_twain_error():
    exc = RuntimeError()
    assert probe._exception_text(exc) == "RuntimeError()"
