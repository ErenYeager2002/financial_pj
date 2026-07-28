from __future__ import annotations

import json
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
from app import model_service, workflow_orchestrator, workflow_service
from app.database import SessionLocal
from app.main import app
from app.models import FileRecord, ServiceCredential, WorkflowAction
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select


def workbook_bytes() -> bytes:
    workbook = Workbook()
    workbook.active.append(["测试列"])
    workbook.active.append(["假数据"])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


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


def test_apply_confirmed_verifies_before_write_and_refreshes_final_baseline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workflow_id = str(uuid.uuid4())
    workflow_root = tmp_path / workflow_id
    workspace = workflow_root / "actions" / "prepare" / "工作区"
    checked = workspace / "04_产出" / "写入计划_校验后.json"
    ledger = workspace / "02_我的表副本" / "盈亏核算表.xlsx"
    checked.parent.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    checked.write_text("{}", encoding="utf-8")
    ledger.write_bytes(workbook_bytes())
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
        "settings",
        SimpleNamespace(workflow_dir=tmp_path),
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
                }
            }
        ),
    )
    workflow = SimpleNamespace(id=workflow_id)

    result = workflow_service._apply_confirmed(
        SimpleNamespace(),
        action,
        workflow,
    )

    assert result["workspace"] == str(workspace.resolve())
    assert {item["name"] for item in result["artifacts"]} == {
        "盈亏核算表.xlsx",
        "写入计划_校验后.json",
    }
    assert [(name, args[0]) for name, args in calls] == [
        ("verify_sources.py", "verify"),
        ("apply_all.py", "--checked"),
        ("verify_sources.py", "snapshot"),
        ("verify_sources.py", "verify"),
    ]


def test_unbound_upload_can_be_deleted() -> None:
    with TestClient(app) as client:
        file_id = upload(client, "finance_workbooks", "待删除.xlsx")
        with SessionLocal() as db:
            record = db.get(FileRecord, file_id)
            assert record is not None
            stored_path = Path(record.stored_path)
            assert stored_path.is_file()

        denied = client.delete(
            f"/api/files/{file_id}",
            headers={"X-User-Id": "another-user"},
        )
        assert denied.status_code == 403
        assert stored_path.is_file()

        deleted = client.delete(f"/api/files/{file_id}")
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

    def fake_copy_inputs(_db, _action, business):
        ledgers = business / "02_我的表副本"
        ledgers.mkdir(parents=True, exist_ok=True)
        (business / "04_产出").mkdir(parents=True, exist_ok=True)
        (ledgers / "测试盈亏表.xlsx").write_bytes(b"test")

    def fake_run_script(
        script_dir,
        script_name,
        arguments,
        timeout=900,
        stdin_data=None,
        sensitive_values=(),
    ):
        del script_dir, timeout, sensitive_values
        calls.append((script_name, arguments, stdin_data))
        if script_name == "build_worklist.py":
            business = workflow_service.settings.workflow_dir / workflow_id / "actions"
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
        workflow_service.settings.workflow_dir
        / workflow_id
        / "skill"
        / "vendor"
        / "scripts"
    )
    skill_scripts.mkdir(parents=True)
    (skill_scripts / "classify_hexiao.py").write_text("", encoding="utf-8")
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

    def unavailable_model(*_, **__):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(workflow_orchestrator.httpx, "post", unavailable_model)
    monkeypatch.setattr(
        workflow_service,
        "_prepare_worklist",
        lambda db, action, workflow: {
            "workspace": "isolated-test-workspace",
            "checked_plan": "checked-plan.json",
            "ledger": "ledger.xlsx",
            "summary": {"今天要填": 3, "异常": 0},
            "artifacts": [],
        },
    )
    monkeypatch.setattr(
        workflow_service,
        "_apply_confirmed",
        lambda db, action, workflow: {
            "workspace": "isolated-test-workspace",
            "artifacts": [],
        },
    )

    with TestClient(app) as client:
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
        with SessionLocal() as db:
            stored = db.scalar(
                select(ServiceCredential).where(
                    ServiceCredential.service == "zhiyun",
                    ServiceCredential.owner_id == "demo-user",
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
        assert applying.json()["stage"] == "applying"
        assert len(applying.json()["actions"]) == 2

        execute_next_action(workflow_id)
        completed = client.get(f"/api/workflows/{workflow_id}").json()
        assert completed["stage"] == "completed"
        assert completed["state"] == "succeeded"

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
