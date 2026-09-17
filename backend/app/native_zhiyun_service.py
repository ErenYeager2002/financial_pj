"""Owner-scoped, read-only Zhiyun broker for native AR Skills.

Only platform code sees credentials. Native packages cannot choose a URL,
executable, output directory, account, or shell arguments for this capability.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import yaml
from fastapi import HTTPException

from .network_policy import assert_url_allowed, execution_network_environment, subprocess_base_environment
from .service_credential_service import resolve_service_credential
from .settings import settings

PREFIX = "platform-zhiyun"
TIMEOUT = 600


def parse_request(name: str, command: str) -> tuple[str, str] | None:
    if not command.strip().startswith(PREFIX):
        return None
    if name != "ar-hexiao-daily":
        raise HTTPException(403, "该 Skill 未授权使用智云取数。")
    if command.strip() == PREFIX + " probe":
        return "probe", ""
    match = re.fullmatch(r"platform-zhiyun fetch --date (\d{4}-\d{2}-\d{2})", command.strip())
    if not match:
        raise HTTPException(422, "使用 platform-zhiyun probe 或 platform-zhiyun fetch --date YYYY-MM-DD；不接受其他参数。")
    try:
        day = date.fromisoformat(match.group(1))
    except ValueError as exc:
        raise HTTPException(422, "核销日期无效。") from exc
    return "fetch", day.isoformat()


def trusted_configuration():
    root = settings.skill_dir / "ar-hexiao-daily"
    config = yaml.safe_load((root / "tool.yaml").read_text())
    runtime = SimpleNamespace(**config["runtime"])
    env = subprocess_base_environment()
    # API and worker use the same existing controlled proxy. Never route via
    # package-provided URLs, proxy values or environment variables.
    policy = execution_network_environment(runtime)
    env.update(policy)
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    base = settings.zhiyun_base_url or runtime.network_targets[0]
    assert_url_allowed(base, runtime)
    env["ZHIYUN_BASE"] = base
    return root / "vendor" / "scripts", env


def safe_workspace(workspace: Path) -> Path:
    root = workspace / "outputs"
    target = root / "ar-work"
    if workspace.is_symlink() or root.is_symlink() or target.is_symlink():
        raise ValueError("Invalid workspace")
    if root.resolve() != root or target.resolve() != target:
        raise ValueError("Invalid workspace")
    for item in root.rglob("*"):
        if item.is_symlink() or not item.resolve().is_relative_to(root):
            raise ValueError("Invalid workspace entry")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _run(command, payload, env, cwd):
    # A process group includes Playwright children; timeout must not leave a
    # browser using credentials or writing exports after the run has failed.
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               errors="replace", cwd=cwd, env=env, start_new_session=True)
    try:
        process.communicate(json.dumps(payload), timeout=TIMEOUT)
        return process.returncode
    except subprocess.TimeoutExpired:
        return 124
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def execute_fetch(db, user, workspace: Path, request: tuple[str, str]):
    mode, day = request
    try:
        account, password = resolve_service_credential(db, user.user_id, user.department_id, "zhiyun")
    except RuntimeError:
        return {"exit_code": 2, "output": "", "error": "请先在平台安全凭据设置中保存当前账号的智云凭据，再调用取数；不要把密码发送到聊天。"}
    try:
        scripts, env = trusted_configuration()
        payload = {"account": account, "password": password}
        if mode == "probe":
            code = "import json,sys,os; from fetch_secure import _edge_login; p=json.load(sys.stdin); _edge_login(os.environ['ZHIYUN_BASE'],p['account'],p['password'])"
            command = [sys.executable, "-c", code]
        else:
            payload.update(workspace=str(safe_workspace(workspace)), reconciliation_date=day)
            command = [sys.executable, str(scripts / "fetch_secure.py")]
        result = _run(command, payload, env, scripts)
        if result:
            message = "智云取数或登录超过10分钟，本次已停止，未自动重试。" if result == 124 else "智云登录或取数失败；请检查平台凭据和智云服务，本次未自动重试。"
            return {"exit_code": result, "output": "", "error": message}
        output = "智云网络连通且当前用户登录验证成功。" if mode == "probe" else f"{day} 智云只读取数完成，工作区 /workspace/outputs/ar-work；请继续核对来源日期和导出完整性。"
        return {"exit_code": 0, "output": output, "error": ""}
    finally:
        password = ""
        if "payload" in locals():
            payload.clear()
