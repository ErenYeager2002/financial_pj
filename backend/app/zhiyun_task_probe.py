from __future__ import annotations

import json
import subprocess
import sys

from .network_policy import assert_url_allowed, skill_subprocess_environment
from .redaction import sanitize_text
from .registry import registry
from .settings import settings
from .task_discovery import TaskDiscoveryDayResult

SKILL_ID = "ar-hexiao-daily"


def _parse_results(stdout: str, business_dates: tuple[str, ...]) -> list[TaskDiscoveryDayResult]:
    try:
        payload = json.loads(stdout)
        raw_results = payload["results"]
        if set(payload) != {"results"} or not isinstance(raw_results, list):
            raise ValueError
        results = [
            TaskDiscoveryDayResult(
                business_date=str(item["business_date"]),
                record_count=int(item["record_count"]),
                fingerprint=str(item["fingerprint"]),
            )
            for item in raw_results
            if isinstance(item, dict)
            and set(item) == {"business_date", "record_count", "fingerprint"}
        ]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("智云任务检查返回了无效结果。") from exc
    if len(results) != len(raw_results):
        raise RuntimeError("智云任务检查返回了无效结果。")
    if [item.business_date for item in results] != list(business_dates):
        raise RuntimeError("智云任务检查返回日期与请求不一致。")
    if any(
        item.record_count < 0
        or len(item.fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in item.fingerprint)
        for item in results
    ):
        raise RuntimeError("智云任务检查返回了无效结果。")
    return results


def probe_zhiyun_tasks(
    account: str,
    password: str,
    business_dates: tuple[str, ...],
) -> list[TaskDiscoveryDayResult]:
    registered = registry.get(SKILL_ID)
    if registered is None:
        raise RuntimeError("应收核销 Skill 当前不可用。")

    runtime = registered.manifest.runtime
    environment = skill_subprocess_environment(runtime)
    environment["FINANCIAL_SKILL_DIR"] = str(
        (registered.directory / "vendor" / "scripts").resolve()
    )
    if settings.zhiyun_base_url:
        assert_url_allowed(settings.zhiyun_base_url, runtime)
        environment["ZHIYUN_BASE"] = settings.zhiyun_base_url

    request_json = json.dumps(
        {
            "account": account,
            "password": password,
            "business_dates": list(business_dates),
        },
        ensure_ascii=False,
    )
    script_path = (settings.project_root / "scripts" / "secure_zhiyun_probe.py").resolve()
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(script_path.parent),
        input=request_json,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=max(30, min(int(runtime.timeout_seconds), 600)),
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        safe_error = sanitize_text(completed.stderr.strip(), error=True)
        raise RuntimeError(safe_error or "智云只读任务检查失败。")
    return _parse_results(completed.stdout, business_dates)
