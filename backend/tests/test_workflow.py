from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from helpers import auth_client
from openpyxl import Workbook
from sqlalchemy import select

from app import model_service, workflow_orchestrator, workflow_service
from app.database import SessionLocal
from app.models import (
    FileRecord,
    ServiceCredential,
    WorkflowAction,
    WorkflowBatch,
    WorkflowSession,
)


@pytest.fixture(autouse=True)
def _allow_disabled_workflow_skill(monkeypatch):
    """工作流测试始终允许读取目标 Skill，避免发布状态影响状态机测试。"""
    from app.registry import registry as _registry

    real_get = _registry.get

    def get(skill_id: str, include_unpublished: bool = False):
        return real_get(skill_id, include_unpublished=True)

    monkeypatch.setattr(_registry, "get", get)


def workbook_bytes() -> bytes:
    workbook = Workbook()
    workbook.active.append(["测试列"])
    workbook.active.append(["假数据"])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


class FakeVerificationResponse:
    """符合 Tool Calling 验证要求的成功响应结构。"""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "tool_call_supported",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ]
        }


def upload(client: TestClient, role: str, name: str) -> str:
    response = client.post(
        "/api/files",
        data={"role": role},
        files={
            "upload": (
                name,
                workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def execute_next_action(workflow_id: str) -> None:
    with SessionLocal() as db:
        action = db.scalar(
            select(WorkflowAction)
            .where(
                WorkflowAction.workflow_id == workflow_id,
                WorkflowAction.state == "queued",
            )
            .order_by(WorkflowAction.queued_at.asc())
        )
        assert action is not None
        action.state = "running"
        db.commit()
        workflow_service.execute_workflow_action(db, action)
        db.commit()


def fake_prepare_worklist(_db, action, workflow) -> dict[str, object]:
    business = (
        workflow_service.workflow_root(workflow.owner_id, workflow.id)
        / "actions"
        / action.id
        / "工作区"
    )
    checked = business / "04_产出" / "写入计划_校验后.json"
    ledger = business / "02_我的表副本" / "盈亏表.xlsx"
    preview = business / "04_产出" / "核销日清_测试.xlsx"
    checked.parent.mkdir(parents=True, exist_ok=True)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    checked.write_text('{"rows": 1}', encoding="utf-8")
    ledger.write_bytes(workbook_bytes())
    preview.write_bytes(workbook_bytes())
    return {
        "workspace": str(business.resolve()),
        "checked_plan": str(checked.resolve()),
        "ledger": str(ledger.resolve()),
        "summary": {"今天要填": 1, "异常": 0},
        "artifacts": [
            {
                "file_id": f"preview-{action.id}",
                "name": preview.name,
                "sha256": workflow_service.sha256_file(preview),
                "size_bytes": preview.stat().st_size,
            }
        ],
    }


def approve_pending_workflow(workflow_id: str) -> dict[str, object]:
    with auth_client(role="skill_admin") as admin:
        listed = admin.get("/api/admin/approvals?status=pending")
        assert listed.status_code == 200, listed.text
        approval = next(
            item for item in listed.json() if item.get("workflow_id") == workflow_id
        )
        decided = admin.post(
            f"/api/admin/approvals/{approval['id']}/decision",
            json={"decision": "approve", "reason": "变更预览和执行快照复核通过。"},
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["status"] == "approved"
        return decided.json()


def test_apply_confirmed_verifies_before_write_and_refreshes_final_baseline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workflow_id = str(uuid.uuid4())
    owner_id = "workflow-unit-user"
    workflow_root = tmp_path / owner_id / workflow_id
    workspace = workflow_root / "actions" / "prepare" / "工作区"
    checked = workspace / "04_产出" / "写入计划_校验后.json"
    ledger = workspace / "02_我的表副本" / "盈亏核算表.xlsx"
    flow = workspace / "02_我的表副本" / "到账流转表.xlsx"
    checked.parent.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    checked.write_text("{}", encoding="utf-8")
    ledger.write_bytes(workbook_bytes())
    flow.write_bytes(workbook_bytes())
    (workflow_root / "skill" / "vendor" / "scripts").mkdir(parents=True)

    calls: list[tuple[str, list[str]]] = []

    def fake_run_script(
        script_dir: Path,
        script_name: str,
        arguments: list[str],
        **_kwargs,
    ) -> str:
        calls.append((script_name, arguments))
        return ""

    monkeypatch.setattr(
        workflow_service,
        "workflow_root",
        lambda selected_owner, selected_workflow: (
            tmp_path / selected_owner / selected_workflow
        ).resolve(),
    )
    monkeypatch.setattr(workflow_service, "_run_script", fake_run_script)
    monkeypatch.setattr(
        workflow_service,
        "_register_artifact",
        lambda _db, _workflow, path, _action_id: {"name": path.name},
    )
    action = SimpleNamespace(
        id="apply-action",
        input_json=json.dumps(
            {
                "context": {
                    "workspace": str(workspace),
                    "checked_plan": str(checked),
                    "ledger": str(ledger),
                    "flow_file": str(flow),
                }
            }
        ),
    )
    workflow = SimpleNamespace(id=workflow_id, owner_id=owner_id)

    result = workflow_service._apply_confirmed(
        SimpleNamespace(),
        action,
        workflow,
    )

    assert result["workspace"] == str(workspace.resolve())
    assert {item["name"] for item in result["artifacts"]} == {
        "盈亏核算表.xlsx",
        "到账流转表.xlsx",
    }
    assert [(name, args[0]) for name, args in calls] == [
        ("verify_sources.py", "verify"),
        ("apply_all.py", "--checked"),
        ("verify_sources.py", "snapshot"),
        ("verify_sources.py", "verify"),
    ]


def test_annual_ledgers_have_no_count_limit_and_are_passed_explicitly(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workflow_id = str(uuid.uuid4())
    owner_id = "workflow-multi-year-user"
    workflow_root = tmp_path / owner_id / workflow_id
    workspace = workflow_root / "actions" / "prepare" / "工作区"
    checked = workspace / "04_产出" / "写入计划_校验后.json"
    ledger_dir = workspace / "02_我的表副本"
    checked.parent.mkdir(parents=True)
    ledger_dir.mkdir(parents=True)
    checked.write_text("{}", encoding="utf-8")
    ledgers = {
        year: ledger_dir / f"{year}年盈亏核算表.xlsx"
        for year in (2024, 2025, 2026)
    }
    for ledger in ledgers.values():
        ledger.write_bytes(workbook_bytes())
    flow = ledger_dir / "到账流转表.xlsx"
    flow.write_bytes(workbook_bytes())
    (workflow_root / "skill" / "vendor" / "scripts").mkdir(parents=True)

    calls: list[tuple[str, list[str]]] = []

    def fake_run_script(_script_dir, script_name, arguments, **_kwargs):
        calls.append((script_name, arguments))
        return ""

    monkeypatch.setattr(
        workflow_service,
        "workflow_root",
        lambda selected_owner, selected_workflow: (
            tmp_path / selected_owner / selected_workflow
        ).resolve(),
    )
    monkeypatch.setattr(workflow_service, "_run_script", fake_run_script)
    monkeypatch.setattr(
        workflow_service,
        "_register_artifact",
        lambda _db, _workflow, path, _action_id: {"name": path.name},
    )
    context = {
        "workspace": str(workspace),
        "checked_plan": str(checked),
        "ledger_years": {str(year): str(path) for year, path in ledgers.items()},
        "flow_file": str(flow),
    }
    action = SimpleNamespace(id="apply-action", input_json=json.dumps({"context": context}))
    workflow = SimpleNamespace(id=workflow_id, owner_id=owner_id)

    workflow_service._apply_confirmed(SimpleNamespace(), action, workflow)

    apply_args = next(args for name, args in calls if name == "apply_all.py")
    specs = [
        apply_args[index + 1]
        for index, value in enumerate(apply_args)
        if value == "--ledger-year"
    ]
    assert specs == [f"{year}={ledgers[year]}" for year in (2024, 2025, 2026)]
    assert "--ledger" not in apply_args


def test_duplicate_annual_ledger_year_is_rejected(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "02_我的表副本"
    ledger_dir.mkdir()
    for name in ("2026年盈亏核算表.xlsx", "2026年盈亏核算表_第二份.xlsx"):
        (ledger_dir / name).write_bytes(workbook_bytes())

    with pytest.raises(RuntimeError, match="每个年度只能上传一份"):
        workflow_service._discover_annual_ledger_paths(tmp_path)


def test_workflow_reuses_and_updates_the_two_material_roles(monkeypatch) -> None:
    class FakeModelsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"id": "qwen3.7-plus"}]}

    monkeypatch.setattr(model_service.httpx, "get", lambda *_, **__: FakeModelsResponse())
    monkeypatch.setattr(
        model_service.httpx,
        "post",
        lambda *_, **__: FakeVerificationResponse(),
    )
    username = f"material-reuse-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        connection = client.post(
            "/api/model-connections",
            json={"api_key": "sk-material-reuse-test"},
        )
        assert connection.status_code == 200, connection.text
        first = client.post(
            "/api/workflows",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
            },
        )
        assert first.status_code == 200, first.text
        first_id = first.json()["id"]
        ledger_2025 = upload(client, "profit_loss_ledgers", "2025年盈亏核算表.xlsx")
        flow = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        bound = client.put(
            f"/api/workflows/{first_id}/files",
            json={
                "files": {
                    "profit_loss_ledgers": [ledger_2025],
                    "receipt_flow_table": [flow],
                }
            },
        )
        assert bound.status_code == 200, bound.text

        second = client.post(
            "/api/workflows",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
            },
        )
        assert second.status_code == 200, second.text
        assert second.json()["files"]["profit_loss_ledgers"][0]["file_id"] == ledger_2025
        assert second.json()["files"]["receipt_flow_table"][0]["file_id"] == flow

        ledger_2026 = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        added = client.put(
            f"/api/workflows/{second.json()['id']}/files",
            json={"files": {"profit_loss_ledgers": [ledger_2026]}},
        )
        assert added.status_code == 200, added.text
        assert {
            item["file_id"] for item in added.json()["files"]["profit_loss_ledgers"]
        } == {ledger_2025, ledger_2026}
        replacement = upload(client, "receipt_flow_table", "到账流转表_新版.xlsx")
        replaced = client.put(
            f"/api/workflows/{second.json()['id']}/files",
            json={"files": {"receipt_flow_table": [replacement]}},
        )
        assert replaced.status_code == 200, replaced.text
        assert [
            item["file_id"] for item in replaced.json()["files"]["receipt_flow_table"]
        ] == [replacement]


def test_background_start_accepts_one_or_many_past_dates_without_model_connection() -> None:
    with auth_client(username=f"background-start-{uuid.uuid4().hex[:8]}") as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "background-test-user", "password": "background-test-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        files = {
            "profit_loss_ledgers": [ledger_id],
            "receipt_flow_table": [flow_id],
        }

        single = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-12",
                "files": files,
            },
        )
        assert single.status_code == 200, single.text
        assert single.json()["model_provider"] == "platform"
        assert single.json()["model_name"] == "后台 Skill Worker"
        assert single.json()["stage"] == "preparing"
        context = client.get(f"/api/workflows/{single.json()['id']}/agent/context")
        assert context.status_code == 200, context.text
        assert context.json()["connection_id"] is None
        assert context.json()["model"] == ""

        future = (date.today() + timedelta(days=1)).isoformat()
        rejected = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": future,
                "files": files,
            },
        )
        assert rejected.status_code == 422
        assert "不能晚于今天" in rejected.text

        batch = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-11", "2026-08-12"],
                "files": files,
            },
        )
        assert batch.status_code == 200, batch.text
        assert batch.json()["reconciliation_dates"] == ["2026-08-11", "2026-08-12"]
        assert batch.json()["model_provider"] == "platform"


def test_unbound_upload_can_be_deleted() -> None:
    with auth_client() as owner:
        file_id = upload(owner, "finance_workbooks", "待删除.xlsx")
        with SessionLocal() as db:
            record = db.get(FileRecord, file_id)
            assert record is not None
            stored_path = Path(record.stored_path)
            assert stored_path.is_file()

        with auth_client(username="other-upload-user") as other:
            denied = other.delete(f"/api/files/{file_id}")
            assert denied.status_code == 404
        assert stored_path.is_file()

        deleted = owner.delete(f"/api/files/{file_id}")
        assert deleted.status_code == 204
        assert not stored_path.exists()
        with SessionLocal() as db:
            assert db.get(FileRecord, file_id) is None


def test_qwen_workflow_supports_natural_multi_turn(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "到账日期是银行收款日，核销日期是销售关联订单的日期。",
                        }
                    }
                ]
            }

    def fake_post(*_, **kwargs):
        captured.update(kwargs["json"])
        return FakeChatResponse()

    monkeypatch.setattr(workflow_orchestrator.httpx, "post", fake_post)
    decision = workflow_orchestrator.decide_workflow_turn(
        SimpleNamespace(
            provider="qwen",
            model="qwen3.7-plus",
            base_url="https://dashscope.example/v1",
            api_key="test-key",
        ),
        "awaiting_date",
        "核销日期和到账日期有什么区别？",
        "",
        [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，需要一起处理什么财务工作？"},
            {"role": "user", "content": "核销日期和到账日期有什么区别？"},
        ],
    )

    assert decision.action == "reply"
    assert "银行收款日" in decision.arguments["content"]
    assert captured["tool_choice"] == "auto"
    assert captured["enable_thinking"] is False
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert messages[-3:] == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，需要一起处理什么财务工作？"},
        {"role": "user", "content": "核销日期和到账日期有什么区别？"},
    ]


def test_questions_containing_action_words_do_not_execute() -> None:
    assert workflow_orchestrator._fallback_decision(
        "awaiting_files",
        "为什么还不能开始？",
    ).action == "show_status"
    assert workflow_orchestrator._fallback_decision(
        "awaiting_apply_confirmation",
        "确认写入是什么意思？",
    ).action == "show_status"
    assert workflow_orchestrator._fallback_decision(
        "awaiting_date",
        "2026-07-24 是星期几？",
    ).action == "show_status"
    assert workflow_orchestrator._fallback_decision(
        "preparing",
        "停止按钮有什么作用？",
    ).action == "show_status"


def test_prepare_worklist_fetches_zhiyun_before_analysis(monkeypatch) -> None:
    workflow_id = str(uuid.uuid4())
    action_id = str(uuid.uuid4())
    calls: list[tuple[str, list[str], str | None]] = []

    def fake_copy_inputs(_db, _action, _workflow, business):
        ledgers = business / "02_我的表副本"
        ledgers.mkdir(parents=True, exist_ok=True)
        (business / "04_产出").mkdir(parents=True, exist_ok=True)
        (ledgers / "测试盈亏表.xlsx").write_bytes(b"test")
        (ledgers / "测试到账流转表.xlsx").write_bytes(b"test")

    def fake_run_script(
        script_dir,
        script_name,
        arguments,
        timeout=900,
        stdin_data=None,
        sensitive_values=(),
        extra_env=None,
    ):
        del script_dir, timeout, sensitive_values, extra_env
        calls.append((script_name, arguments, stdin_data))
        if script_name == "build_worklist.py":
            business = workflow_service.workflow_root("demo-user", workflow_id) / "actions"
            workspace = business / action_id / "工作区"
            (workspace / "04_产出" / "核销日清_20260724.xlsx").write_bytes(b"worklist")
            (workspace / "04_产出" / "写入计划_校验后.json").write_text(
                "{}",
                encoding="utf-8",
            )
        return ""

    monkeypatch.setattr(workflow_service, "_copy_inputs", fake_copy_inputs)
    monkeypatch.setattr(workflow_service, "_run_script", fake_run_script)
    monkeypatch.setattr(
        workflow_service,
        "_register_artifact",
        lambda *_: {"name": "核销日清_20260724.xlsx", "file_id": "output-test"},
    )
    monkeypatch.setattr(
        workflow_service,
        "resolve_service_credential",
        lambda *_: ("test-account", "test-password"),
    )

    skill_scripts = (
        workflow_service.workflow_root("demo-user", workflow_id)
        / "skill"
        / "vendor"
        / "scripts"
    )
    skill_scripts.mkdir(parents=True)
    (skill_scripts / "classify_hexiao.py").write_text("", encoding="utf-8")
    (skill_scripts.parents[1] / "tool.yaml").write_text(
        """schema_version: 1
id: ar-hexiao-daily
name: 应收核销日清
version: 1.0.0
status: disabled
description: 合成测试
handler:
  adapter: workflow
runtime:
  network_access: true
  network_allowlist: [zhiyun.synthetic.example]
risk:
  level: write
  requires_approval: true
""",
        encoding="utf-8",
    )
    workflow = SimpleNamespace(
        id=workflow_id,
        owner_id="demo-user",
        department_id="finance",
        reconciliation_date="2026-07-24",
        progress=0,
        progress_message="",
    )
    action = SimpleNamespace(id=action_id)
    db = SimpleNamespace(commit=lambda: None)

    result = workflow_service._prepare_worklist(db, action, workflow)

    assert calls[0][0] == "fetch_secure.py"
    assert calls[0][1] == []
    payload = json.loads(calls[0][2] or "{}")
    assert payload["reconciliation_date"] == "2026-07-24"
    assert payload["account"] == "test-account"
    assert calls[1][0] == "inspect_inputs.py"
    assert result["artifacts"][0]["file_id"] == "output-test"


def test_conversational_workflow_hard_gates(monkeypatch) -> None:
    class FakeModelsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"id": "qwen3.7-plus"}]}

    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(),
    )

    def unavailable_model(url, **kwargs):
        payload = kwargs.get("json") or {}
        tools = payload.get("tools") or []
        if tools and tools[0].get("function", {}).get("name") == "tool_call_supported":
            return FakeVerificationResponse()
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(workflow_orchestrator.httpx, "post", unavailable_model)
    monkeypatch.setattr(
        workflow_service,
        "_prepare_worklist",
        fake_prepare_worklist,
    )
    monkeypatch.setattr(
        workflow_service,
        "_apply_confirmed",
        lambda db, action, workflow: {
            "workspace": "isolated-test-workspace",
            "artifacts": [],
        },
    )

    with auth_client() as client:
        connection = client.post(
            "/api/model-connections",
            json={"api_key": "sk-workflow-test-secret"},
        )
        assert connection.status_code == 200, connection.text

        created = client.post(
            "/api/workflows",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
            },
        )
        assert created.status_code == 200, created.text
        workflow_id = created.json()["id"]
        assert created.json()["stage"] == "awaiting_date"

        status_before_date = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "上传好了"},
        )
        assert status_before_date.status_code == 200
        assert status_before_date.json()["stage"] == "awaiting_date"
        assert status_before_date.json()["messages"][-1]["content"] == "请先告诉我核销日期。"

        dated = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "2026年7月24日"},
        )
        assert dated.status_code == 200
        assert dated.json()["stage"] == "awaiting_date_confirmation"
        assert dated.json()["reconciliation_date"] == "2026-07-24"

        confirmed = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "确认"},
        )
        assert confirmed.json()["stage"] == "awaiting_files"

        premature = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "确认写入"},
        )
        assert premature.json()["stage"] == "awaiting_files"
        assert premature.json()["actions"] == []

        ledger_id = upload(client, "finance_workbooks", "盈亏表.xlsx")
        flow_id = upload(client, "finance_workbooks", "到账流转表.xlsx")

        too_few = client.put(
            f"/api/workflows/{workflow_id}/files",
            json={"files": {"finance_workbooks": [ledger_id]}},
        )
        assert too_few.status_code == 200
        insufficient = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "上传好了"},
        )
        assert insufficient.json()["stage"] == "awaiting_files"
        assert insufficient.json()["actions"] == []
        assert "还缺" in insufficient.json()["messages"][-1]["content"]

        attached = client.put(
            f"/api/workflows/{workflow_id}/files",
            json={
                "files": {
                    "finance_workbooks": [ledger_id, flow_id],
                }
            },
        )
        assert attached.status_code == 200, attached.text
        still_bound = client.delete(f"/api/files/{ledger_id}")
        assert still_bound.status_code == 409
        assert "仍被任务使用" in still_bound.text

        missing_credential = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "上传好了"},
        )
        assert missing_credential.json()["stage"] == "awaiting_files"
        assert missing_credential.json()["actions"] == []
        assert "还缺智云账号" in missing_credential.json()["messages"][-1]["content"]

        test_account = "test-zhiyun-user"
        test_password = "not-a-real-password"
        saved = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": test_account, "password": test_password},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["configured"] is True
        assert test_account not in saved.text
        assert test_password not in saved.text
        status = client.get("/api/service-credentials/zhiyun")
        assert status.status_code == 200
        assert status.json()["configured"] is True
        assert test_account not in status.text
        assert test_password not in status.text
        owner_id = client.get("/api/session").json()["user_id"]
        with SessionLocal() as db:
            stored = db.scalar(
                select(ServiceCredential).where(
                    ServiceCredential.service == "zhiyun",
                    ServiceCredential.owner_id == owner_id,
                )
            )
            assert stored is not None
            assert test_account not in stored.account_encrypted
            assert test_password not in stored.password_encrypted

        preparing = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "上传好了"},
        )
        assert preparing.json()["stage"] == "preparing"
        assert preparing.json()["actions"][0]["name"] == "prepare_worklist"
        with SessionLocal() as db:
            queued = db.scalar(
                select(WorkflowAction).where(
                    WorkflowAction.workflow_id == workflow_id,
                    WorkflowAction.state == "queued",
                )
            )
            assert queued is not None
            assert test_account not in queued.input_json
            assert test_password not in queued.input_json

        execute_next_action(workflow_id)
        review = client.get(f"/api/workflows/{workflow_id}").json()
        assert review["stage"] == "awaiting_apply_confirmation"
        assert review["state"] == "waiting_confirmation"

        original_decider = workflow_service.decide_workflow_turn
        monkeypatch.setattr(
            workflow_service,
            "decide_workflow_turn",
            lambda *_, **__: workflow_orchestrator.WorkflowDecision(
                "confirm_apply",
                {},
                "malformed-model",
            ),
        )
        guarded = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "现在进度怎么样"},
        )
        assert guarded.json()["stage"] == "awaiting_apply_confirmation"
        assert len(guarded.json()["actions"]) == 1
        monkeypatch.setattr(
            workflow_service,
            "decide_workflow_turn",
            original_decider,
        )

        applying = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "我已检查核销日清，确认写入"},
        )
        assert applying.status_code == 200, applying.text
        assert applying.json()["stage"] == "applying"
        assert applying.json()["state"] == "running"
        assert len(applying.json()["actions"]) == 2

        execute_next_action(workflow_id)
        completed = client.get(f"/api/workflows/{workflow_id}").json()
        assert completed["stage"] == "completed"
        assert completed["state"] == "succeeded"
        assert "到账流转表" in completed["messages"][-1]["content"]

        monkeypatch.setattr(
            workflow_service,
            "decide_workflow_turn",
            lambda *_, **__: workflow_orchestrator.WorkflowDecision(
                "reply",
                {"content": "任务已经完成，我还可以继续解释结果或回答问题。"},
                "llm",
            ),
        )
        continued = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "任务完成后还能继续聊吗？"},
        )
        assert continued.status_code == 200
        assert continued.json()["stage"] == "completed"
        assert "继续解释结果" in continued.json()["messages"][-1]["content"]


def test_workflow_reset_clears_current_state_and_preserves_audit(monkeypatch) -> None:
    class FakeModelsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"id": "qwen3.7-plus"}]}

    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(),
    )
    monkeypatch.setattr(
        model_service.httpx,
        "post",
        lambda *_, **__: FakeVerificationResponse(),
    )

    with auth_client() as client:
        connection = client.post(
            "/api/model-connections",
            json={"api_key": "sk-workflow-reset-test"},
        )
        assert connection.status_code == 200, connection.text
        created = client.post(
            "/api/workflows",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
            },
        )
        assert created.status_code == 200, created.text
        workflow_id = created.json()["id"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            workflow.state = "failed"
            workflow.stage = "failed"
            workflow.reconciliation_date = "2026-07-24"
            workflow.context_json = '{"workspace": "old"}'
            workflow.files_json = '{"finance_workbooks": [{"file_id": "old"}]}'
            workflow.artifacts_json = '[{"file_id": "output-old"}]'
            workflow.progress = 77
            workflow.progress_message = "旧任务失败"
            workflow.error_message = "旧错误"
            db.add(
                WorkflowAction(
                    id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    name="prepare_worklist",
                    state="failed",
                    error_message="旧动作失败",
                )
            )
            db.commit()

        reset = client.post(f"/api/workflows/{workflow_id}/reset")
        assert reset.status_code == 200, reset.text
        body = reset.json()
        assert body["id"] == workflow_id
        assert body["state"] == "active"
        assert body["stage"] == "awaiting_date"
        assert body["reconciliation_date"] == ""
        assert body["files"] == {}
        assert body["artifacts"] == []
        assert body["progress"] == 0
        assert body["error_message"] == ""
        assert len(body["actions"]) == 1
        assert body["actions"][0]["state"] == "failed"
        assert body["messages"][-1]["data"]["kind"] == "workflow_reset"
        assert "已经完成的写入不会撤销" in body["messages"][-1]["content"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            db.add(
                WorkflowAction(
                    id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    name="prepare_worklist",
                    state="queued",
                )
            )
            workflow.stage = "preparing"
            workflow.state = "running"
            db.commit()

        blocked = client.post(f"/api/workflows/{workflow_id}/reset")
        assert blocked.status_code == 409
        assert "正在执行" in blocked.text

        # 这个测试故意留下运行中的动作来验证 reset 的保护条件；
        # 断言完成后清理它，避免后续审批测试把它误认为待领取动作。
        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            for action in db.scalars(
                select(WorkflowAction).where(
                    WorkflowAction.workflow_id == workflow_id,
                    WorkflowAction.state == "queued",
                )
            ).all():
                action.state = "cancelled"
            workflow.state = "failed"
            workflow.stage = "failed"
            db.commit()


def test_multi_date_batch_runs_children_in_order_and_chains_files(monkeypatch) -> None:
    class FakeModelsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"id": "qwen3.7-plus"}]}

    monkeypatch.setattr(model_service.httpx, "get", lambda *_, **__: FakeModelsResponse())
    monkeypatch.setattr(
        model_service.httpx,
        "post",
        lambda *_, **__: FakeVerificationResponse(),
    )
    monkeypatch.setattr(
        workflow_service,
        "_prepare_worklist",
        fake_prepare_worklist,
    )

    def fake_apply(_db, _action, workflow):
        return {
            "workspace": f"isolated-{workflow.id}",
            "artifacts": [],
            "next_files": json.loads(workflow.files_json),
        }

    monkeypatch.setattr(workflow_service, "_apply_confirmed", fake_apply)

    with auth_client() as client:
        connection = client.post(
            "/api/model-connections",
            json={"api_key": "sk-workflow-batch-test"},
        )
        assert connection.status_code == 200, connection.text
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "batch-test-user", "password": "batch-test-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "finance_workbooks", "盈亏表.xlsx")
        flow_id = upload(client, "finance_workbooks", "到账流转表.xlsx")

        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
                "reconciliation_dates": ["2026-07-21", "2026-07-20"],
                "files": {"finance_workbooks": [ledger_id, flow_id]},
            },
        )
        assert started.status_code == 200, started.text
        batch = started.json()
        assert batch["id"].startswith("BAT-")
        assert batch["reconciliation_dates"] == ["2026-07-20", "2026-07-21"]
        assert [item["batch_sequence"] for item in batch["workflows"]] == [1, 2]
        first, second = batch["workflows"]
        assert first["stage"] == "preparing"
        assert second["stage"] == "queued"
        assert len(first["actions"]) == 1
        assert second["actions"] == []

        execute_next_action(first["id"])
        after_prepare = client.get(f"/api/workflows/{first['id']}").json()
        assert after_prepare["stage"] == "awaiting_apply_confirmation"
        assert [item["name"] for item in after_prepare["actions"]] == ["prepare_worklist"]

        confirmed = client.post(
            f"/api/workflows/{first['id']}/messages",
            json={"content": "确认写入"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["stage"] == "applying"
        assert [item["name"] for item in confirmed.json()["actions"]] == [
            "prepare_worklist",
            "apply_confirmed",
        ]
        assert client.get(f"/api/workflows/{second['id']}").json()["stage"] == "queued"

        execute_next_action(first["id"])
        first_complete = client.get(f"/api/workflows/{first['id']}").json()
        second_started = client.get(f"/api/workflows/{second['id']}").json()
        assert first_complete["state"] == "succeeded"
        assert second_started["stage"] == "preparing"
        assert ledger_id in {
            item["file_id"] for item in second_started["files"]["profit_loss_ledgers"]
        }

        execute_next_action(second["id"])
        second_prepare = client.get(f"/api/workflows/{second['id']}").json()
        assert second_prepare["stage"] == "awaiting_apply_confirmation"
        confirmed_second = client.post(
            f"/api/workflows/{second['id']}/messages",
            json={"content": "确认写入"},
        )
        assert confirmed_second.json()["stage"] == "applying"
        execute_next_action(second["id"])
        completed = client.get(f"/api/workflow-batches/{batch['id']}").json()
        assert completed["state"] == "succeeded"
        assert completed["progress"] == 100
        assert all(item["state"] == "succeeded" for item in completed["workflows"])
        with SessionLocal() as db:
            stored = db.get(WorkflowBatch, batch["id"])
            assert stored is not None
            assert stored.state == "succeeded"
