from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

try:
    import jdy_selenium_rpa as rpa
except ModuleNotFoundError as exc:
    if exc.name == "selenium":
        raise unittest.SkipTest("需要先安装 requirements.txt 中的 Selenium") from exc
    raise


class VirtualTableTests(unittest.TestCase):
    def test_amount_pattern_accepts_supported_amounts(self) -> None:
        accepted = ("2,105,578.31", "-955,694.33", "(1,234.00)", "0")
        rejected = ("", "本期金额", "--", "1期")

        self.assertTrue(all(rpa.AMOUNT_RE.fullmatch(item) for item in accepted))
        self.assertTrue(all(not rpa.AMOUNT_RE.fullmatch(item) for item in rejected))

    def test_select_row_occurrences_deduplicates_and_orders_virtual_rows(self) -> None:
        collected = {
            "24": [(0, "24", 0), (3, "24", 700)],
            "1": [(5, "1", 700), (0, "1", 0)],
            "12": [(4, "12", 0), (2, "12", 350)],
        }

        selected = rpa.select_row_occurrences(collected, max_scroll=700)

        self.assertEqual([item[1] for item in selected], ["1", "12", "24"])
        self.assertEqual(selected[-1], (3, "24", 700))
        self.assertEqual(len(selected), 3)


if __name__ == "__main__":
    unittest.main()
