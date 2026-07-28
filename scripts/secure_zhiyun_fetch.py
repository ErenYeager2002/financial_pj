#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def _edge_login(
    base_url: str,
    username: str,
    password: str,
    headless: bool = True,
) -> tuple[str, str | None]:
    import fetch_zhiyun
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=headless)
            try:
                context = browser.new_context(ignore_https_errors=True)
                page = context.new_page()
                page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
                page.locator("#txtMobilePhone").wait_for(state="visible", timeout=60_000)
                page.fill("#txtMobilePhone", username)
                page.fill("input[type=password]", password)
                clicked = False
                for selector in (".btnForLogin", "text=登 录", "text=登录", ".loginBtn"):
                    try:
                        page.click(selector, timeout=2_500)
                        clicked = True
                        break
                    except Exception:
                        continue
                if not clicked:
                    page.keyboard.press("Enter")
                token = None
                for _ in range(60):
                    token = next(
                        (
                            cookie["value"]
                            for cookie in context.cookies()
                            if cookie.get("name") == "md_pss_id" and cookie.get("value")
                        ),
                        None,
                    )
                    if token:
                        break
                    page.wait_for_timeout(500)
                if not token:
                    raise fetch_zhiyun.LoginError(
                        f"登录后未拿到会话凭据（url={page.url}）。"
                        "请检查账号密码、内网连接或登录页结构。"
                    )
                account_id = None
                try:
                    account_id = page.evaluate(
                        "() => { try { return (md && md.global && md.global.Account && "
                        "md.global.Account.accountId) || null; } catch(e) { return null; } }"
                    )
                except Exception:
                    account_id = None
                return token, account_id
            finally:
                browser.close()
    except fetch_zhiyun.LoginError:
        raise
    except Exception as exc:
        raise fetch_zhiyun.LoginError(
            f"登录异常 {type(exc).__name__}，请检查内网和 Edge。"
        ) from exc


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    import fetch_zhiyun

    try:
        payload = json.loads(sys.stdin.read())
        account = str(payload["account"]).strip()
        password = str(payload["password"])
        reconciliation_date = str(payload["reconciliation_date"]).strip()
        workspace = str(Path(payload["workspace"]).resolve())
    except (KeyError, TypeError, ValueError):
        print("ERROR: 自动取数凭据输入无效。", file=sys.stderr)
        return 2
    if not account or not password or not reconciliation_date:
        print("ERROR: 自动取数缺少账号、密码或核销日期。", file=sys.stderr)
        return 2

    fetch_zhiyun.login_with_password = _edge_login
    try:
        return fetch_zhiyun.main(
            [
                "--date",
                reconciliation_date,
                "--workspace",
                workspace,
                "--user",
                account,
                "--password",
                password,
                "--skip-gap-check",
            ]
        )
    finally:
        password = ""
        payload.clear()


if __name__ == "__main__":
    raise SystemExit(main())
