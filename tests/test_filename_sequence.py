from __future__ import annotations

from pathlib import Path

import pytest

import scanner_capture as target


def test_next_output_number_starts_at_one() -> None:
    assert target.next_output_number([]) == 1


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["DSC_0001.jpeg"], 2),
        (["DSC_0001.jpeg", "DSC_0009.jpeg", "DSC_0003.jpeg"], 10),
        (["dsc_0042.JPEG"], 43),
        (["notes.txt", "DSC_12.jpeg", "DSC_0002.jpg"], 1),
        (["DSC_0002.jpeg", "DSC_0004.jpeg"], 5),
    ],
)
def test_next_output_number_uses_highest_valid_sequence(
    names: list[str], expected: int
) -> None:
    assert target.next_output_number(names) == expected


def test_next_output_number_rejects_exhausted_sequence() -> None:
    with pytest.raises(RuntimeError, match="DSC_9999"):
        target.next_output_number(["DSC_9999.jpeg"])


def test_reserve_output_path_creates_directory_and_empty_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "jpeg"

    result = target.reserve_output_path(output_dir)

    assert result == output_dir / "DSC_0001.jpeg"
    assert result.exists()
    assert result.stat().st_size == 0


def test_reserve_output_path_uses_next_number(tmp_path: Path) -> None:
    output_dir = tmp_path / "jpeg"
    output_dir.mkdir()
    (output_dir / "DSC_0001.jpeg").write_bytes(b"one")
    (output_dir / "DSC_0007.jpeg").write_bytes(b"seven")
    (output_dir / "unrelated.jpeg").write_bytes(b"ignored")

    result = target.reserve_output_path(output_dir)

    assert result.name == "DSC_0008.jpeg"


def test_reserve_output_path_retries_after_concurrent_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "jpeg"
    original_open = target.os.open
    attempted: list[str] = []

    def racing_open(path, flags, *args, **kwargs):
        attempted.append(Path(path).name)
        if Path(path).name == "DSC_0001.jpeg":
            raise FileExistsError(path)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(target.os, "open", racing_open)

    result = target.reserve_output_path(output_dir)

    assert attempted[:2] == ["DSC_0001.jpeg", "DSC_0002.jpeg"]
    assert result.name == "DSC_0002.jpeg"


def test_remove_empty_reservation_deletes_only_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jpeg"
    nonempty = tmp_path / "nonempty.jpeg"
    empty.touch()
    nonempty.write_bytes(b"image")

    target.remove_empty_reservation(empty)
    target.remove_empty_reservation(nonempty)
    target.remove_empty_reservation(None)

    assert not empty.exists()
    assert nonempty.read_bytes() == b"image"


def test_remove_empty_reservation_logs_unlink_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    reserved = tmp_path / "reserved.jpeg"
    reserved.touch()

    def fail_unlink(self):
        raise OSError("locked")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    target.remove_empty_reservation(reserved)

    assert "Could not remove empty reserved file" in caplog.text
