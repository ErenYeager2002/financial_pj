from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

try:
    import jdy_selenium_rpa as rpa
    from selenium.webdriver.common.by import By
except ModuleNotFoundError as exc:
    if exc.name == "selenium":
        raise unittest.SkipTest("需要先安装 requirements.txt 中的 Selenium") from exc
    raise


class SelectorTests(unittest.TestCase):
    def test_exact_login_and_workbench_selectors_are_first(self) -> None:
        self.assertEqual(rpa.USERNAME_LOCATORS[0], (By.CSS_SELECTOR, "#login_username"))
        self.assertEqual(rpa.PASSWORD_LOCATORS[0], (By.CSS_SELECTOR, "#login_pwd"))
        self.assertEqual(
            rpa.MY_WORKBENCH_LOCATORS[0],
            (By.CSS_SELECTOR, ".workstation.btn-green"),
        )

    def test_current_period_column_never_falls_back_to_month_amount(self) -> None:
        source = inspect.getsource(rpa)
        self.assertIn("本期金额", source)
        self.assertNotIn("本月金额", source)
        self.assertIn("我知道了", source)

    def test_write_action_labels_are_absent_from_automation_source(self) -> None:
        source = inspect.getsource(rpa)
        forbidden = (
            "全部重算",
            "批量调整",
            "批量调整选中行",
            "自动指定",
            "重新指定",
            "不指定",
        )
        self.assertTrue(all(label not in source for label in forbidden))

    def test_xpath_literal_handles_both_quote_types(self) -> None:
        literal = rpa.xpath_literal("甲'乙\"丙")
        self.assertTrue(literal.startswith("concat("))
        self.assertIn('"\'"', literal)


if __name__ == "__main__":
    unittest.main()
