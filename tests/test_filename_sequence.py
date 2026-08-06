"""連番ファイル名の割り当て処理を検証するテスト。"""

import tempfile
import unittest
from pathlib import Path

from scanner_capture import (
    next_output_number,
    remove_empty_reservation,
    reserve_output_path,
)


class NextOutputNumberTests(unittest.TestCase):
    """既存の名前から次の連番を求める純粋関数を検証する。"""

    def test_returns_one_when_no_capture_exists(self) -> None:
        """対象となるファイルがなければ1を返す。"""
        self.assertEqual(next_output_number(["memo.txt", "DSC_123.jpeg"]), 1)

    def test_uses_highest_number_case_insensitively(self) -> None:
        """大文字小文字を区別せず、最大番号の次を返す。"""
        names = ["DSC_0002.jpeg", "dsc_0010.JPEG", "DSC_0007.jpeg"]
        self.assertEqual(next_output_number(names), 11)

    def test_raises_when_sequence_is_exhausted(self) -> None:
        """9999まで使用済みなら明示的なエラーにする。"""
        with self.assertRaisesRegex(RuntimeError, "DSC_9999"):
            next_output_number(["DSC_9999.jpeg"])


class OutputReservationTests(unittest.TestCase):
    """連番パスの予約と失敗時の後始末を検証する。"""

    def test_reserves_next_path_and_cleanup_removes_empty_file(self) -> None:
        """次のパスを空ファイルで予約し、後始末で削除する。"""
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "DSC_0003.jpeg").write_bytes(b"image")

            reserved = reserve_output_path(output_dir)

            self.assertEqual(reserved.name, "DSC_0004.jpeg")
            self.assertTrue(reserved.exists())
            remove_empty_reservation(reserved)
            self.assertFalse(reserved.exists())

    def test_cleanup_preserves_non_empty_file(self) -> None:
        """保存済みの画像は後始末の対象にしない。"""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "DSC_0001.jpeg"
            output.write_bytes(b"image")

            remove_empty_reservation(output)

            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
