"""使用 Selenium 接管已开启远程调试的 Edge，执行金蝶现金流量明细导出。

Edge 必须先用 ``--remote-debugging-port=9222`` 启动。本脚本不会启动或
关闭浏览器；默认新建运行标签页，自动填写凭据、勾选协议并登录，也可通过
``--manual-login`` 改为人工提交，随后继续执行查询和导出流程。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import (
    JavascriptException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.edge.service import Service
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement


DEFAULT_URL = "http://www.jdy.com/"
DEFAULT_DEBUGGER_ADDRESS = "127.0.0.1:9222"
DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "工作区" / "rpa"
DEFAULT_CREDENTIALS_FILE = DEFAULT_ARTIFACTS_DIR / "jdy_credentials.local.json"
DEFAULT_DOWNLOAD_ROOT = (
    Path(__file__).resolve().parents[1] / "工作区" / "04_产出" / "现金流量调整导出"
)
LOGIN_POLL_SECONDS = 2.0
ROW_OPEN_TIMEOUT_SECONDS = 3.0
ROW_CLICK_ATTEMPTS = 2
PERIOD_RE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*期")
AMOUNT_RE = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")

USERNAME_LOCATORS = (
    (By.CSS_SELECTOR, "#login_username"),
    (By.CSS_SELECTOR, 'input[name*="user"]'),
    (By.CSS_SELECTOR, 'input[id*="user"]'),
    (By.CSS_SELECTOR, 'input[name*="account"]'),
    (By.CSS_SELECTOR, 'input[id*="account"]'),
    (By.CSS_SELECTOR, 'input[placeholder*="用户名"]'),
    (By.CSS_SELECTOR, 'input[placeholder*="账号"]'),
    (By.CSS_SELECTOR, 'input[placeholder*="手机号"]'),
    (By.CSS_SELECTOR, 'input[type="tel"]'),
    (By.CSS_SELECTOR, 'input[type="text"]'),
)
PASSWORD_LOCATORS = (
    (By.CSS_SELECTOR, "#login_pwd"),
    (By.CSS_SELECTOR, 'input[type="password"]'),
    (By.CSS_SELECTOR, 'input[name*="password"]'),
    (By.CSS_SELECTOR, 'input[id*="password"]'),
    (By.CSS_SELECTOR, 'input[name*="pwd"]'),
    (By.CSS_SELECTOR, 'input[id*="pwd"]'),
    (By.CSS_SELECTOR, 'input[placeholder*="密码"]'),
)
LOGIN_LINK_LOCATORS = (
    (By.CSS_SELECTOR, 'a[href="/login"]'),
    (By.CSS_SELECTOR, 'a[href="/login/"]'),
    (By.CSS_SELECTOR, "a.toplogin"),
)
MY_WORKBENCH_LOCATORS = (
    (By.CSS_SELECTOR, ".workstation.btn-green"),
    (By.XPATH, "//*[contains(normalize-space(.),'我的工作台')]"),
)


class RpaError(RuntimeError):
    pass


@dataclass
class Located:
    frame_path: tuple[int, ...]
    element: WebElement

    def activate(self, driver: WebDriver) -> WebElement:
        switch_to_frame_path(driver, self.frame_path)
        return self.element


@dataclass
class CashflowTable:
    frame_path: tuple[int, ...]
    table: WebElement
    current_period_column_index: int


@dataclass
class AdjustmentSurface:
    window_handle: str
    frame_path: tuple[int, ...]
    opened_new_window: bool


def xpath_literal(text: str) -> str:
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = text.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"


def visible(element: WebElement) -> bool:
    try:
        return element.is_displayed()
    except (StaleElementReferenceException, WebDriverException):
        return False


def switch_to_frame_path(driver: WebDriver, path: tuple[int, ...]) -> None:
    driver.switch_to.default_content()
    for index in path:
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
        if index >= len(frames):
            raise StaleElementReferenceException("iframe path changed")
        driver.switch_to.frame(frames[index])


def find_visible_anywhere(
    driver: WebDriver,
    locators: Sequence[tuple[str, str]],
    *,
    max_depth: int = 3,
) -> Located | None:
    def search(path: tuple[int, ...], depth: int) -> Located | None:
        try:
            switch_to_frame_path(driver, path)
            for by, value in locators:
                for element in driver.find_elements(by, value):
                    if visible(element):
                        return Located(path, element)
            if depth >= max_depth:
                return None
            frame_count = len(driver.find_elements(By.CSS_SELECTOR, "iframe,frame"))
            for index in range(frame_count):
                result = search(path + (index,), depth + 1)
                if result is not None:
                    return result
        except (StaleElementReferenceException, WebDriverException):
            return None
        return None

    result = search((), 0)
    driver.switch_to.default_content()
    return result


def find_all_visible_anywhere(
    driver: WebDriver,
    locators: Sequence[tuple[str, str]],
    *,
    max_depth: int = 3,
    limit: int = 200,
) -> list[Located]:
    found: list[Located] = []

    def search(path: tuple[int, ...], depth: int) -> None:
        if len(found) >= limit:
            return
        try:
            switch_to_frame_path(driver, path)
            for by, value in locators:
                for element in driver.find_elements(by, value):
                    if visible(element):
                        found.append(Located(path, element))
                        if len(found) >= limit:
                            return
            if depth >= max_depth:
                return
            frame_count = len(driver.find_elements(By.CSS_SELECTOR, "iframe,frame"))
            for index in range(frame_count):
                search(path + (index,), depth + 1)
        except (StaleElementReferenceException, WebDriverException):
            return

    search((), 0)
    driver.switch_to.default_content()
    return found


def text_locators(text: str) -> tuple[tuple[str, str], ...]:
    literal = xpath_literal(text)
    return (
        (
            By.XPATH,
            "//*[self::button or self::a or @role='button']"
            f"[normalize-space(.)={literal}]",
        ),
        (By.XPATH, f"//*[normalize-space(.)={literal}]"),
    )


def find_text_anywhere(driver: WebDriver, texts: Iterable[str]) -> Located | None:
    for text in texts:
        result = find_visible_anywhere(driver, text_locators(text))
        if result is not None:
            return result
    return None


def click_located(driver: WebDriver, located: Located) -> None:
    element = located.activate(driver)
    try:
        element.click()
    except TimeoutException:
        return
    except WebDriverException:
        driver.execute_script("arguments[0].click()", element)


def click_and_follow_window(
    driver: WebDriver, located: Located, wait_seconds: float = 5.0
) -> None:
    before = set(driver.window_handles)
    click_located(driver, located)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        new_handles = [handle for handle in driver.window_handles if handle not in before]
        if new_handles:
            driver.switch_to.window(new_handles[-1])
            return
        time.sleep(0.2)
    driver.switch_to.default_content()


def is_authenticated_surface(driver: WebDriver) -> bool:
    """只有真正显示“进入使用”按钮才视为登录完成。"""

    try:
        if "service.jdy.com" not in (driver.current_url or ""):
            return False
    except WebDriverException:
        return False
    return find_text_anywhere(driver, ("进入使用",)) is not None


def wait_for_login_inputs(driver: WebDriver) -> tuple[Located, Located] | None:
    while True:
        if is_authenticated_surface(driver):
            return None
        try:
            driver.switch_to.default_content()
            username_element = find_visible_in_root(driver, USERNAME_LOCATORS)
            password_element = find_visible_in_root(driver, PASSWORD_LOCATORS)
            if username_element is not None and password_element is not None:
                return Located((), username_element), Located((), password_element)
        except WebDriverException:
            pass
        username = find_visible_anywhere(driver, USERNAME_LOCATORS)
        password = find_visible_anywhere(driver, PASSWORD_LOCATORS)
        if username is not None and password is not None:
            return username, password
        print("正在寻找账号密码输入框", flush=True)
        time.sleep(LOGIN_POLL_SECONDS)


def enter_login_page(driver: WebDriver) -> None:
    workbench_clicked = False
    workbench_clicked_at = 0.0
    while True:
        if is_authenticated_surface(driver):
            return
        driver.switch_to.default_content()
        if not workbench_clicked:
            workbench_element = find_visible_in_root(
                driver, MY_WORKBENCH_LOCATORS
            )
            if workbench_element is not None:
                print("检测到“我的工作台”，正在复用现有登录状态。", flush=True)
                click_and_follow_window(
                    driver, Located((), workbench_element)
                )
                workbench_clicked = True
                workbench_clicked_at = time.monotonic()
                continue
        login_element = find_visible_in_root(driver, LOGIN_LINK_LOCATORS)
        if login_element is not None:
            print("已找到登录按钮，正在进入登录界面。", flush=True)
            click_and_follow_window(driver, Located((), login_element))
            return
        username = find_visible_anywhere(driver, USERNAME_LOCATORS)
        password = find_visible_anywhere(driver, PASSWORD_LOCATORS)
        if username is not None and password is not None:
            return
        if (
            workbench_clicked
            and time.monotonic() - workbench_clicked_at >= 15
        ):
            print(
                "“我的工作台”登录状态无效，正在转到账号登录页面。",
                flush=True,
            )
            try:
                driver.get("https://www.jdy.com/login/")
            except TimeoutException:
                pass
            workbench_clicked = False
            continue
        if workbench_clicked:
            print("正在等待“进入使用”按钮加载", flush=True)
        else:
            print("正在寻找“我的工作台”或登录按钮", flush=True)
        time.sleep(1)


def fill_input(driver: WebDriver, located: Located, value: str) -> None:
    element = located.activate(driver)
    element.clear()
    element.send_keys(value)
    try:
        driver.execute_script(
            """
            arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
            arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
            """,
            element,
        )
    except JavascriptException:
        pass


def wait_for_manual_login(
    driver: WebDriver, *, manual_prompt: bool = True
) -> None:
    if manual_prompt:
        print(
            "账号密码已填写，请在浏览器中手动勾选协议并点击登录。",
            flush=True,
        )
    else:
        print("正在等待自动登录完成。", flush=True)
    rounds = 0
    while True:
        for handle in reversed(driver.window_handles):
            try:
                driver.switch_to.window(handle)
                if is_authenticated_surface(driver):
                    return
            except WebDriverException:
                continue
        if rounds % 5 == 0:
            message = (
                "正在等待人工完成登录"
                if manual_prompt
                else "正在等待登录完成"
            )
            print(message, flush=True)
        rounds += 1
        time.sleep(1)


def auto_submit_login(driver: WebDriver, password: Located) -> None:
    while True:
        checkbox = find_visible_anywhere(
            driver,
            (
                (By.CSS_SELECTOR, "#reg_agreement"),
                (By.CSS_SELECTOR, 'input[type="checkbox"][id*="agreement"]'),
            ),
        )
        if checkbox is not None:
            element = checkbox.activate(driver)
            if not element.is_selected():
                element.click()
            print("登录协议已自动勾选。", flush=True)
            break
        time.sleep(0.2)

    login_button = find_visible_anywhere(
        driver,
        (
            (By.CSS_SELECTOR, "#login_btn"),
            (By.CSS_SELECTOR, "#login_btn_gray"),
            (By.CSS_SELECTOR, 'button[type="submit"]'),
            (By.CSS_SELECTOR, 'input[type="button"][value="登录"]'),
            (By.XPATH, "//button[normalize-space(.)='登录']"),
        ),
    )
    if login_button is not None:
        print("正在自动点击登录。", flush=True)
        click_and_follow_window(driver, login_button)
    else:
        password.activate(driver).send_keys(Keys.ENTER)

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        agree = find_text_anywhere(driver, ("我同意", "同意"))
        if agree is not None:
            click_located(driver, agree)
            break
        time.sleep(0.2)
    wait_for_manual_login(driver, manual_prompt=False)


def perform_login(
    driver: WebDriver,
    url: str,
    username: str,
    password: str,
    *,
    auto_submit: bool,
) -> None:
    if not is_authenticated_surface(driver):
        try:
            driver.get(url)
        except TimeoutException:
            print("官网仍有资源加载中，继续检测登录入口。", flush=True)
    enter_login_page(driver)
    if is_authenticated_surface(driver):
        return
    inputs = wait_for_login_inputs(driver)
    if inputs is None:
        return
    username_input, password_input = inputs
    fill_input(driver, username_input, username)
    fill_input(driver, password_input, password)
    print("账号密码已填写。", flush=True)
    if auto_submit:
        auto_submit_login(driver, password_input)
    else:
        wait_for_manual_login(driver)


def enter_application(driver: WebDriver) -> None:
    while True:
        enter_button = find_text_anywhere(driver, ("进入使用",))
        if enter_button is not None:
            print("正在点击“进入使用”。", flush=True)
            click_and_follow_window(driver, enter_button)
            time.sleep(2)
            return
        print("正在等待“进入使用”按钮加载", flush=True)
        time.sleep(2)


def wait_and_click_text(driver: WebDriver, text: str) -> None:
    while True:
        target = find_text_anywhere(driver, (text,))
        if target is not None:
            click_and_follow_window(driver, target, wait_seconds=3)
            return
        print(f"正在寻找“{text}”", flush=True)
        time.sleep(2)


def navigate_to_cashflow(driver: WebDriver) -> None:
    print("正在进入“财务报表”。", flush=True)
    wait_and_click_text(driver, "财务报表")
    time.sleep(1)
    print("正在进入“现金流量表”。", flush=True)
    wait_and_click_text(driver, "现金流量表")
    time.sleep(2)


def dismiss_cashflow_balance_check(
    driver: WebDriver,
    *,
    timeout_seconds: float = 5.0,
) -> bool:
    """关闭只读的现金流量表平衡检查提示，不触发任何重算操作。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        acknowledgement = find_text_anywhere(driver, ("我知道了",))
        if acknowledgement is not None:
            print("检测到现金流量表平衡检查提示，正在关闭提示。", flush=True)
            click_located(driver, acknowledgement)
            wait_deadline = time.monotonic() + 5
            while time.monotonic() < wait_deadline:
                if find_text_anywhere(driver, ("我知道了",)) is None:
                    driver.switch_to.default_content()
                    return True
                time.sleep(0.2)
            raise RpaError("已点击“我知道了”，但平衡检查提示没有关闭。")
        time.sleep(0.2)
    driver.switch_to.default_content()
    return False


def find_cashflow_frame_path(driver: WebDriver) -> tuple[int, ...]:
    while True:
        current_period = find_text_anywhere(driver, ("本期金额",))
        if current_period is not None:
            try:
                switch_to_frame_path(driver, current_period.frame_path)
                line = driver.find_elements(
                    By.XPATH, "//*[normalize-space(.)='行次']"
                )
                if any(visible(item) for item in line):
                    driver.switch_to.default_content()
                    return current_period.frame_path
            except WebDriverException:
                pass
        print("正在等待现金流量表数据区域", flush=True)
        time.sleep(2)


def find_period_input(driver: WebDriver, frame_path: tuple[int, ...]) -> WebElement:
    switch_to_frame_path(driver, frame_path)
    for element in driver.find_elements(By.CSS_SELECTOR, "input"):
        if not visible(element):
            continue
        value = (element.get_attribute("value") or "").strip()
        placeholder = (element.get_attribute("placeholder") or "").strip()
        if "期间" in placeholder or PERIOD_RE.search(value):
            return element
    raise RpaError("现金流量表页面没有找到期间选择框。")


def select_max_period(driver: WebDriver, frame_path: tuple[int, ...]) -> int:
    period_input = find_period_input(driver, frame_path)
    period_input.click()
    time.sleep(0.5)
    options = find_all_visible_anywhere(
        driver,
        (
            (By.CSS_SELECTOR, '[role="option"]'),
            (By.CSS_SELECTOR, ".el-select-dropdown__item"),
            (By.CSS_SELECTOR, ".ant-select-item-option"),
            (By.CSS_SELECTOR, ".kd-select-option"),
            (By.CSS_SELECTOR, "li"),
        ),
    )
    periods: list[tuple[int, Located]] = []
    for option in options:
        try:
            match = PERIOD_RE.search(option.element.text.strip())
        except StaleElementReferenceException:
            continue
        if match:
            periods.append((int(match.group(1)), option))
    if periods:
        max_period = max(period for period, _ in periods)
        target = next(item for period, item in periods if period == max_period)
        click_located(driver, target)
    else:
        switch_to_frame_path(driver, frame_path)
        period_input.send_keys(Keys.END, Keys.ENTER)
        value = period_input.get_attribute("value") or ""
        found = [int(item) for item in PERIOD_RE.findall(value)]
        if not found:
            raise RpaError("期间下拉列表中没有识别到第 1 至第 12 期。")
        max_period = max(found)
    print(f"已选择最大期间：第 {max_period} 期。", flush=True)
    return max_period


def find_visible_in_root(
    root: WebDriver | WebElement,
    locators: Sequence[tuple[str, str]],
) -> WebElement | None:
    for by, value in locators:
        try:
            for element in root.find_elements(by, value):
                if visible(element):
                    return element
        except (StaleElementReferenceException, WebDriverException):
            continue
    return None


def click_button_in_current_frame(driver: WebDriver, text: str) -> None:
    literal = xpath_literal(text)
    target = find_visible_in_root(
        driver,
        (
            (
                By.XPATH,
                "//*[self::button or self::a or @role='button']"
                f"[normalize-space(.)={literal}]",
            ),
            (By.CSS_SELECTOR, f'input[type="button"][value="{text}"]'),
            (By.CSS_SELECTOR, f'input[type="submit"][value="{text}"]'),
        ),
    )
    if target is None:
        raise RpaError(f"没有找到按钮：{text}")
    target.click()


def discover_cashflow_table(
    driver: WebDriver, frame_path: tuple[int, ...]
) -> CashflowTable:
    switch_to_frame_path(driver, frame_path)
    tables = [table for table in driver.find_elements(By.TAG_NAME, "table") if visible(table)]
    for header_table in tables:
        headers = header_table.find_elements(By.CSS_SELECTOR, "thead th,thead td")
        header_texts = [item.text.strip() for item in headers]
        for column_index, text in enumerate(header_texts):
            if "本期金额" not in text:
                continue
            body_rows = header_table.find_elements(By.CSS_SELECTOR, "tbody tr")
            data_table = header_table
            if not body_rows:
                best_rows = 0
                for candidate in tables:
                    rows = candidate.find_elements(By.CSS_SELECTOR, "tbody tr")
                    max_cells = max(
                        (
                            len(row.find_elements(By.TAG_NAME, "td"))
                            for row in rows[:10]
                        ),
                        default=0,
                    )
                    if len(rows) > best_rows and max_cells > column_index:
                        data_table = candidate
                        best_rows = len(rows)
            return CashflowTable(frame_path, data_table, column_index)
    raise RpaError("没有识别到包含“本期金额”的现金流量表格。")


def eligible_row_indexes(driver: WebDriver, table: CashflowTable) -> list[int]:
    return [index for index, _ in eligible_row_targets(driver, table)]


def eligible_row_targets(
    driver: WebDriver, table: CashflowTable
) -> list[tuple[int, str | None]]:
    switch_to_frame_path(driver, table.frame_path)
    snapshots = driver.execute_script(
        """
        const columnIndex = arguments[1];
        return Array.from(arguments[0].querySelectorAll('tbody tr')).map(
            (row, index) => {
                const cells = row.querySelectorAll('td');
                return {
                    index,
                    key: row.getAttribute('data-row-key'),
                    text: cells.length > columnIndex
                        ? (cells[columnIndex].innerText || '')
                        : ''
                };
            }
        );
        """,
        table.table,
        table.current_period_column_index,
    )
    eligible: list[tuple[int, str | None]] = []
    for snapshot in snapshots:
        text = (
            str(snapshot.get("text") or "")
            .strip()
            .replace(" ", "")
            .replace("￥", "")
            .replace("¥", "")
        )
        if text and AMOUNT_RE.fullmatch(text):
            eligible.append(
                (
                    int(snapshot["index"]),
                    str(snapshot["key"]) if snapshot.get("key") is not None else None,
                )
            )
    driver.switch_to.default_content()
    return eligible


def cashflow_scroll_container(
    driver: WebDriver, table: CashflowTable
) -> WebElement:
    switch_to_frame_path(driver, table.frame_path)
    try:
        return table.table.find_element(
            By.XPATH,
            "ancestor::div[contains(concat(' ',normalize-space(@class),' '),"
            "' kd-table-body ')][1]",
        )
    except NoSuchElementException:
        return table.table


def select_row_occurrences(
    collected: dict[str, list[tuple[int, str | None, int]]],
    *,
    max_scroll: int,
) -> list[tuple[int, str | None, int]]:
    """为虚拟表格中的每个业务行选择最接近其理论位置的一次渲染。"""
    numeric_keys = [
        int(identity)
        for identity in collected
        if identity.isdigit()
    ]
    max_key = max(numeric_keys, default=1)
    selected: list[tuple[int, str | None, int]] = []
    for identity, occurrences in collected.items():
        if identity.isdigit():
            ideal = int(identity) / max_key * max_scroll
            selected.append(
                min(occurrences, key=lambda item: abs(item[2] - ideal))
            )
        else:
            selected.append(occurrences[0])
    return sorted(
        selected,
        key=lambda item: (
            int(item[1]) if item[1] is not None and item[1].isdigit() else 10**9,
            item[0],
        ),
    )


def collect_all_eligible_rows(
    driver: WebDriver,
    *,
    settle_seconds: float = 1.0,
) -> list[tuple[int, str | None, int]]:
    frame_path = find_cashflow_frame_path(driver)
    table = discover_cashflow_table(driver, frame_path)
    container = cashflow_scroll_container(driver, table)
    metrics = driver.execute_script(
        """
        return {
            height: arguments[0].clientHeight,
            scrollHeight: arguments[0].scrollHeight
        };
        """,
        container,
    )
    max_scroll = max(0, int(metrics["scrollHeight"]) - int(metrics["height"]))
    step = 100
    positions = list(range(0, max_scroll + 1, step))
    if not positions or positions[-1] != max_scroll:
        positions.append(max_scroll)

    collected: dict[str, list[tuple[int, str | None, int]]] = {}
    for position in positions:
        frame_path = find_cashflow_frame_path(driver)
        table = discover_cashflow_table(driver, frame_path)
        container = cashflow_scroll_container(driver, table)
        driver.execute_script("arguments[0].scrollTop=arguments[1]", container, position)
        driver.switch_to.default_content()
        time.sleep(settle_seconds)
        frame_path = find_cashflow_frame_path(driver)
        table = discover_cashflow_table(driver, frame_path)
        for index, row_key in eligible_row_targets(driver, table):
            identity = row_key if row_key is not None else f"{position}:{index}"
            collected.setdefault(identity, []).append((index, row_key, position))

    frame_path = find_cashflow_frame_path(driver)
    table = discover_cashflow_table(driver, frame_path)
    container = cashflow_scroll_container(driver, table)
    driver.execute_script("arguments[0].scrollTop=0", container)
    driver.switch_to.default_content()
    if not collected:
        raise RpaError("现金流量表查询后没有加载出可处理的本期金额行。")

    return select_row_occurrences(collected, max_scroll=max_scroll)


def click_amount(
    driver: WebDriver,
    table: CashflowTable,
    row_index: int,
    row_key: str | None = None,
    scroll_top: int = 0,
) -> None:
    switch_to_frame_path(driver, table.frame_path)
    try:
        container = table.table.find_element(
            By.XPATH,
            "ancestor::div[contains(concat(' ',normalize-space(@class),' '),"
            "' kd-table-body ')][1]",
        )
        driver.execute_script(
            "arguments[0].scrollTop=arguments[1]", container, scroll_top
        )
        driver.switch_to.default_content()
        time.sleep(0.5)
        frame_path = find_cashflow_frame_path(driver)
        table = discover_cashflow_table(driver, frame_path)
        switch_to_frame_path(driver, table.frame_path)
    except (NoSuchElementException, StaleElementReferenceException):
        switch_to_frame_path(driver, table.frame_path)
    rows = table.table.find_elements(By.CSS_SELECTOR, "tbody tr")
    row = rows[row_index]
    if row_key is not None:
        matches = table.table.find_elements(
            By.XPATH,
            f".//tbody/tr[@data-row-key={xpath_literal(row_key)}]",
        )
        if matches:
            row = matches[0]
    cells = row.find_elements(By.TAG_NAME, "td")
    cell = cells[table.current_period_column_index]
    candidates = [
        item
        for item in cell.find_elements(
            By.CSS_SELECTOR, "a,button,[role='button'],[onclick]"
        )
        if visible(item)
    ]
    for item in cell.find_elements(By.XPATH, ".//*"):
        if not visible(item):
            continue
        try:
            if driver.execute_script(
                "return getComputedStyle(arguments[0]).cursor", item
            ) == "pointer":
                candidates.append(item)
        except WebDriverException:
            continue
    if candidates:
        target = min(
            candidates,
            key=lambda item: max(
                1,
                item.rect.get("width", 0) * item.rect.get("height", 0),
            ),
        )
    else:
        target = cell
    try:
        ActionChains(driver).move_to_element(target).click().perform()
    except WebDriverException:
        driver.execute_script("arguments[0].click()", target)


def wait_for_adjustment(
    driver: WebDriver,
    before_handles: set[str],
    timeout_seconds: float,
) -> AdjustmentSurface | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        new_handles = [
            handle for handle in driver.window_handles if handle not in before_handles
        ]
        if new_handles:
            driver.switch_to.window(new_handles[-1])
        title = find_text_anywhere(driver, ("现金流量调整列表",))
        if title is not None:
            return AdjustmentSurface(
                driver.current_window_handle,
                title.frame_path,
                bool(new_handles),
            )
        time.sleep(0.2)
    return None


def adjustment_root(
    driver: WebDriver, surface: AdjustmentSurface
) -> WebDriver | WebElement:
    driver.switch_to.window(surface.window_handle)
    switch_to_frame_path(driver, surface.frame_path)
    dialogs = [
        element
        for element in driver.find_elements(By.CSS_SELECTOR, "#dialogShow")
        if visible(element)
    ]
    for dialog in reversed(dialogs):
        if dialog.find_elements(
            By.XPATH, ".//*[normalize-space(.)='现金流量调整列表']"
        ):
            return dialog

    title = find_visible_in_root(
        driver,
        ((By.XPATH, "//*[normalize-space(.)='现金流量调整列表']"),),
    )
    if title is None:
        return driver
    try:
        return title.find_element(
            By.XPATH,
            "ancestor::*[@role='dialog' or contains(@class,'modal') "
            "or contains(@class,'dialog')][1]",
        )
    except NoSuchElementException:
        return driver


def root_button(root: WebDriver | WebElement, text: str) -> WebElement | None:
    literal = xpath_literal(text)
    return find_visible_in_root(
        root,
        (
            (
                By.XPATH,
                ".//*[self::button or self::a or @role='button']"
                f"[normalize-space(.)={literal}]"
                if isinstance(root, WebElement)
                else "//*[self::button or self::a or @role='button']"
                f"[normalize-space(.)={literal}]",
            ),
            (By.CSS_SELECTOR, f'input[type="button"][value="{text}"]'),
            (By.CSS_SELECTOR, f'input[type="submit"][value="{text}"]'),
        ),
    )


def set_adjustment_full_year(
    driver: WebDriver, surface: AdjustmentSurface
) -> None:
    period_input = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and period_input is None:
        root = adjustment_root(driver, surface)
        for element in root.find_elements(By.CSS_SELECTOR, "input"):
            if not visible(element):
                continue
            value = element.get_attribute("value") or ""
            placeholder = element.get_attribute("placeholder") or ""
            if "期间" in placeholder or (
                "年" in value and PERIOD_RE.search(value) is not None
            ):
                period_input = element
                break
        if period_input is None:
            time.sleep(0.25)
    if period_input is None:
        raise RpaError("等待 10 秒后，现金流量调整列表仍未加载期间输入框。")
    value = period_input.get_attribute("value") or ""
    if "01期" in value and "12期" in value:
        print("调整列表期间已是本年。", flush=True)
        return

    this_year = find_text_anywhere(driver, ("本年",))
    if this_year is None:
        try:
            period_control = period_input.find_element(By.XPATH, "..")
            ActionChains(driver).move_to_element(period_control).click().perform()
        except (NoSuchElementException, WebDriverException):
            driver.execute_script(
                "arguments[0].parentElement.click()",
                period_input,
            )

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        this_year = this_year or find_text_anywhere(driver, ("本年",))
        if this_year is not None:
            click_located(driver, this_year)
            verify_deadline = time.monotonic() + 3
            while time.monotonic() < verify_deadline:
                root = adjustment_root(driver, surface)
                values = [
                    element.get_attribute("value") or ""
                    for element in root.find_elements(By.CSS_SELECTOR, "input")
                    if visible(element)
                    and "年" in (element.get_attribute("value") or "")
                    and PERIOD_RE.search(element.get_attribute("value") or "")
                ]
                if any("01期" in item and "12期" in item for item in values):
                    print("调整列表期间已选择本年。", flush=True)
                    return
                time.sleep(0.2)
            raise RpaError("已点击“本年”，但期间没有变为第 1 期至第 12 期。")
        time.sleep(0.2)
    raise RpaError("调整列表期间不是本年，且没有找到“本年”选项。")


def query_adjustment_rows(
    driver: WebDriver, surface: AdjustmentSurface
) -> None:
    root = adjustment_root(driver, surface)
    query = root_button(root, "查询")
    if query is None:
        raise RpaError("现金流量调整列表没有找到查询按钮。")
    try:
        query.click()
    except WebDriverException:
        driver.execute_script("arguments[0].click()", query)

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root = adjustment_root(driver, surface)
        if root.find_elements(By.CSS_SELECTOR, "input.kd-checkbox-input"):
            print("调整列表查询完成。", flush=True)
            return
        time.sleep(0.3)
    raise RpaError("调整列表查询后没有加载出多选框。")


def select_all_adjustment_rows(
    driver: WebDriver, surface: AdjustmentSurface
) -> None:
    def selected() -> bool:
        current_root = adjustment_root(driver, surface)
        current = current_root.find_elements(
            By.CSS_SELECTOR, "input.kd-checkbox-input"
        )
        if not current:
            return False
        first = current[0]
        try:
            if first.is_selected() or bool(
                driver.execute_script("return !!arguments[0].checked", first)
            ):
                return True
        except WebDriverException:
            pass
        selected_status = current_root.find_elements(
            By.XPATH,
            ".//*[contains(normalize-space(.),'已选中') "
            "and contains(normalize-space(.),'条')]",
        )
        return any(
            re.search(r"已选中\s*[1-9]\d*\s*条", element.text or "")
            for element in selected_status
            if visible(element)
        )

    def wait_selected(seconds: float = 3.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if selected():
                return True
            time.sleep(0.2)
        return False

    root = adjustment_root(driver, surface)
    checkboxes = root.find_elements(By.CSS_SELECTOR, "input.kd-checkbox-input")
    if not checkboxes:
        raise RpaError("现金流量调整列表没有找到 kd-checkbox-input 多选框。")
    if selected():
        print("调整列表已全选。", flush=True)
        return

    select_all = checkboxes[0]
    click_target = select_all
    try:
        click_target = select_all.find_element(By.XPATH, "ancestor::label[1]")
    except NoSuchElementException:
        try:
            click_target = select_all.find_element(By.XPATH, "..")
        except NoSuchElementException:
            pass
    try:
        ActionChains(driver).move_to_element(click_target).click().perform()
    except WebDriverException:
        driver.execute_script("arguments[0].click()", click_target)

    if not wait_selected():
        root = adjustment_root(driver, surface)
        checkboxes = root.find_elements(
            By.CSS_SELECTOR, "input.kd-checkbox-input"
        )
        if not checkboxes:
            raise RpaError("全选操作后，多选框已从调整列表中消失。")
        driver.execute_script("arguments[0].click()", checkboxes[0])
        if not wait_selected():
            raise RpaError(
                "点击全选复选框后，页面仍显示已选中 0 条。"
            )
    print("调整列表已全选。", flush=True)


def export_adjustment(
    driver: WebDriver,
    surface: AdjustmentSurface,
    run_dir: Path,
    ordinal: int,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {"behavior": "allow", "downloadPath": str(run_dir.resolve())},
    )
    before = {item.name: item.stat().st_mtime_ns for item in run_dir.iterdir()}
    root = adjustment_root(driver, surface)
    export_candidates = [
        item
        for item in root.find_elements(
            By.CSS_SELECTOR,
            "._2zTfwwd5._3PwtlkVv, span._3PwtlkVv",
        )
        if item.text.strip() == "导出"
    ]
    if not export_candidates:
        export_candidates = [
            item
            for item in driver.find_elements(
                By.CSS_SELECTOR,
                "._2zTfwwd5._3PwtlkVv, span._3PwtlkVv",
            )
            if visible(item) and item.text.strip() == "导出"
        ]
    if not export_candidates:
        prefix = ".//" if isinstance(root, WebElement) else "//"
        export_candidates = [
            item
            for item in root.find_elements(
                By.XPATH,
                f"{prefix}*[normalize-space(.)='导出']",
            )
            if visible(item)
        ]
    export_button = export_candidates[-1] if export_candidates else None
    if export_button is None:
        export_button = root_button(root, "导出")
    if export_button is None:
        raise RpaError("现金流量调整列表没有找到导出按钮。")
    driver.execute_script("arguments[0].click()", export_button)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        current = {
            item.name: item.stat().st_mtime_ns
            for item in run_dir.iterdir()
            if not item.name.endswith((".crdownload", ".tmp"))
        }
        if any(name not in before or before[name] != stamp for name, stamp in current.items()):
            return
        time.sleep(0.5)
    raise RpaError(f"第 {ordinal} 行点击导出后未检测到下载文件。")


def close_adjustment(
    driver: WebDriver,
    surface: AdjustmentSurface,
    main_handle: str,
) -> None:
    if surface.opened_new_window:
        driver.switch_to.window(surface.window_handle)
        driver.close()
        driver.switch_to.window(main_handle)
        return
    root = adjustment_root(driver, surface)
    close_button = find_visible_in_root(
        root,
        (
            (By.CSS_SELECTOR, ".ant-modal-close"),
            (By.CSS_SELECTOR, ".el-dialog__headerbtn"),
            (By.CSS_SELECTOR, '[aria-label="Close"]'),
            (By.CSS_SELECTOR, ".close"),
        ),
    )
    if close_button is not None:
        close_button.click()
    else:
        driver.switch_to.active_element.send_keys(Keys.ESCAPE)
    time.sleep(0.5)
    driver.switch_to.window(main_handle)
    driver.switch_to.default_content()


def run_cashflow_export(
    driver: WebDriver,
    *,
    download_dir: Path | None,
    artifacts_dir: Path,
    row_open_timeout_seconds: float,
    row_click_attempts: int,
    max_rows: int | None,
) -> tuple[int, int, int, Path]:
    enter_application(driver)
    navigate_to_cashflow(driver)
    dismiss_cashflow_balance_check(driver)
    frame_path = find_cashflow_frame_path(driver)
    max_period = select_max_period(driver, frame_path)
    switch_to_frame_path(driver, frame_path)
    click_button_in_current_frame(driver, "查询")
    driver.switch_to.default_content()
    dismiss_cashflow_balance_check(driver)
    eligible = collect_all_eligible_rows(driver)
    if max_rows is not None:
        eligible = eligible[:max_rows]
    run_dir = download_dir or (
        DEFAULT_DOWNLOAD_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"本期金额列共有 {len(eligible)} 行可处理。", flush=True)

    main_handle = driver.current_window_handle
    exported = skipped = failed = 0
    for ordinal, (row_index, row_key, scroll_top) in enumerate(
        eligible, start=1
    ):
        print(f"正在处理第 {ordinal}/{len(eligible)} 行。", flush=True)
        surface: AdjustmentSurface | None = None
        try:
            driver.switch_to.window(main_handle)
            frame_path = find_cashflow_frame_path(driver)
            table = discover_cashflow_table(driver, frame_path)
            before_handles = set(driver.window_handles)
            for attempt in range(1, row_click_attempts + 1):
                click_amount(
                    driver,
                    table,
                    row_index,
                    row_key,
                    scroll_top,
                )
                surface = wait_for_adjustment(
                    driver, before_handles, row_open_timeout_seconds
                )
                if surface is not None:
                    break
                if attempt < row_click_attempts:
                    print(
                        f"第 {ordinal} 行首次点击未打开调整列表，正在重试。",
                        flush=True,
                    )
                    driver.switch_to.window(main_handle)
                    frame_path = find_cashflow_frame_path(driver)
                    table = discover_cashflow_table(driver, frame_path)
            if surface is None:
                skipped += 1
                print(
                    f"第 {ordinal} 行重试 {row_click_attempts} 次后"
                    "仍未打开调整列表，已跳过。",
                    flush=True,
                )
                driver.switch_to.window(main_handle)
                continue
            try:
                set_adjustment_full_year(driver, surface)
                query_adjustment_rows(driver, surface)
                select_all_adjustment_rows(driver, surface)
                export_adjustment(driver, surface, run_dir, ordinal)
                exported += 1
                print(f"第 {ordinal} 行导出完成。", flush=True)
            except Exception:
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                screenshot = artifacts_dir / f"jdy-row-{ordinal:03d}-failure.png"
                try:
                    driver.switch_to.window(surface.window_handle)
                    driver.save_screenshot(str(screenshot))
                    print(f"第 {ordinal} 行失败现场：{screenshot}", file=sys.stderr)
                except WebDriverException:
                    pass
                raise
            finally:
                close_adjustment(driver, surface, main_handle)
        except Exception as exc:
            failed += 1
            detail = str(exc) if isinstance(exc, RpaError) else type(exc).__name__
            print(f"第 {ordinal} 行处理失败：{detail}", file=sys.stderr)
            try:
                driver.switch_to.window(main_handle)
                driver.switch_to.default_content()
            except WebDriverException:
                pass
    return exported, skipped, failed, run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通过 Selenium 接管现有 Edge 的现金流量调整明细导出 RPA"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="登录入口 URL")
    parser.add_argument(
        "--debugger-address",
        default=DEFAULT_DEBUGGER_ADDRESS,
        help="Edge 远程调试地址，默认 127.0.0.1:9222",
    )
    parser.add_argument(
        "--edge-driver",
        type=Path,
        help="可选 EdgeDriver 路径；不提供时由 Selenium Manager 匹配",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("JDY_USERNAME"),
        help="用户名；优先于环境变量和本地配置",
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=DEFAULT_CREDENTIALS_FILE,
        help="本地测试凭据 JSON；默认位于被 Git 忽略的工作区/rpa",
    )
    login_mode = parser.add_mutually_exclusive_group()
    login_mode.add_argument(
        "--auto-submit-login",
        dest="auto_submit_login",
        action="store_true",
        help="自动勾选协议并点击登录（默认）",
    )
    login_mode.add_argument(
        "--manual-login",
        dest="auto_submit_login",
        action="store_false",
        help="填写账号密码后等待人工勾选协议并登录",
    )
    parser.set_defaults(auto_submit_login=True)
    tab_group = parser.add_mutually_exclusive_group()
    tab_group.add_argument(
        "--use-current-tab",
        dest="use_current_tab",
        action="store_true",
        help="显式复用当前标签页",
    )
    tab_group.add_argument(
        "--new-tab",
        dest="use_current_tab",
        action="store_false",
        help="清理旧金蝶页面并新建标签页执行（默认）",
    )
    parser.set_defaults(use_current_tab=False)
    parser.add_argument("--login-only", action="store_true", help="只完成登录")
    parser.add_argument("--download-dir", type=Path, help="导出目录")
    parser.add_argument(
        "--row-open-timeout-seconds",
        type=float,
        default=ROW_OPEN_TIMEOUT_SECONDS,
        help="点击金额后等待调整列表的秒数，默认 3 秒",
    )
    parser.add_argument(
        "--row-click-attempts",
        type=int,
        default=ROW_CLICK_ATTEMPTS,
        help="金额行未打开调整列表时的点击次数，默认 2 次",
    )
    parser.add_argument("--max-rows", type=int, help="只处理前 N 行")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="诊断截图目录",
    )
    return parser.parse_args()


def load_credentials(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RpaError(f"无法读取本地凭据配置：{path}") from exc
    if not isinstance(data, dict):
        raise RpaError(f"本地凭据配置必须是 JSON 对象：{path}")
    return {
        key: value
        for key, value in data.items()
        if key in {"username", "password"} and isinstance(value, str)
    }


def connect_edge(args: argparse.Namespace) -> WebDriver:
    options = webdriver.EdgeOptions()
    options.page_load_strategy = "eager"
    options.add_experimental_option("debuggerAddress", args.debugger_address)
    service = (
        Service(executable_path=str(args.edge_driver.resolve()))
        if args.edge_driver
        else Service()
    )
    try:
        driver = webdriver.Edge(service=service, options=options)
        driver.set_page_load_timeout(20)
        return driver
    except WebDriverException as exc:
        raise RpaError(
            f"无法连接 Edge 调试地址 {args.debugger_address}。"
            "请先运行 start_jdy_edge.ps1，并确认 http://127.0.0.1:9222/json/version 可访问。"
        ) from exc


def open_fresh_run_tab(driver: WebDriver) -> None:
    old_handles = list(driver.window_handles)
    driver.switch_to.new_window("tab")
    fresh_handle = driver.current_window_handle
    closed = 0
    for handle in old_handles:
        try:
            driver.switch_to.window(handle)
            current_url = driver.current_url or ""
            parsed = urlparse(current_url)
            host = (parsed.hostname or "").lower()
            if (
                current_url.startswith("edge://newtab")
                or host == "jdy.com"
                or host.endswith(".jdy.com")
            ):
                driver.close()
                closed += 1
        except WebDriverException:
            continue
    driver.switch_to.window(fresh_handle)
    print(f"已创建全新运行页面，并清理 {closed} 个旧金蝶页面。", flush=True)


def stop_driver_without_closing_edge(driver: WebDriver) -> None:
    try:
        driver.service.stop()
    except Exception:
        pass


def main() -> int:
    args = parse_args()
    try:
        credentials = load_credentials(args.credentials_file)
    except RpaError as exc:
        print(f"流程失败：{exc}", file=sys.stderr)
        return 2
    username = (
        args.username
        or os.getenv("JDY_USERNAME")
        or credentials.get("username")
        or input("用户名：").strip()
    )
    password = (
        os.getenv("JDY_PASSWORD")
        or credentials.get("password")
        or getpass.getpass("密码：")
    )
    if not username or not password:
        print("流程失败：用户名和密码不能为空。", file=sys.stderr)
        return 2

    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    driver: WebDriver | None = None
    try:
        driver = connect_edge(args)
        if not args.use_current_tab:
            open_fresh_run_tab(driver)
        perform_login(
            driver,
            args.url,
            username,
            password,
            auto_submit=args.auto_submit_login,
        )
        print(f"登录成功，当前页面：{driver.current_url}", flush=True)
        if not args.login_only:
            exported, skipped, failed, run_dir = run_cashflow_export(
                driver,
                download_dir=args.download_dir,
                artifacts_dir=args.artifacts_dir,
                row_open_timeout_seconds=args.row_open_timeout_seconds,
                row_click_attempts=max(1, args.row_click_attempts),
                max_rows=args.max_rows,
            )
            print(
                f"现金流量调整明细处理完成：导出 {exported} 行，"
                f"跳过 {skipped} 行，失败 {failed} 行。",
                flush=True,
            )
            print(f"导出目录：{run_dir}", flush=True)
        return 0
    except (RpaError, WebDriverException) as exc:
        if driver is not None:
            try:
                screenshot = args.artifacts_dir / "jdy-selenium-failure.png"
                driver.save_screenshot(str(screenshot))
                print(f"流程失败：{exc}\n诊断截图：{screenshot}", file=sys.stderr)
            except Exception:
                print(f"流程失败：{exc}", file=sys.stderr)
        else:
            print(f"流程失败：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已退出。")
        return 130
    finally:
        if driver is not None:
            stop_driver_without_closing_edge(driver)


if __name__ == "__main__":
    raise SystemExit(main())
