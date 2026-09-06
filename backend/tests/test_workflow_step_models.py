from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_models import User
from app.database import Base
from app.models import ApprovalRecord, FileRecord, RunRecord, WorkflowSession


def _sqlite_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


def _legacy_read_only_manifest() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "id": "legacy-compatibility",
            "name": "旧任务兼容",
            "version": "1.0.0",
            "status": "published",
            "description": "验证旧任务不依赖步骤模型",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "handler": {
                "adapter": "python",
                "entrypoint": "scripts/entry.py",
                "worker_pool": "python",
            },
            "runtime": {
                "timeout_seconds": 30,
                "memory_mb": 128,
                "concurrency_limit": 1,
            },
            "risk": {"level": "read_only", "requires_confirmation": False},
        },
        ensure_ascii=False,
    )


def _add_standard_step_run(
    db: Session,
    *,
    prefix: str,
    owner_id: str,
    department_id: str = "finance",
):
    from app.models import StepDefinition, StepRun, WorkflowDefinition

    db.add(
        User(
            id=owner_id,
            username=f"{prefix}-owner",
            password_hash="not-used-by-this-test",
            role="skill_admin",
            department_id=department_id,
        )
    )
    run = RunRecord(
        id=f"{prefix}-run",
        owner_id=owner_id,
        department_id=department_id,
        skill_id="reconcile-bank",
        skill_name="银行流水核对",
        skill_version="1.0.0",
        skill_hash="a" * 64,
        manifest_path="skills/reconcile-bank/tool.yaml",
        manifest_snapshot="{}",
        adapter="python",
        worker_pool="python",
    )
    db.add(run)
    db.flush()
    definition = WorkflowDefinition(
        id=f"{prefix}-definition",
        department_id=department_id,
        workflow_key=f"{prefix}-workflow",
        name="范围约束测试流程",
        version="1",
        skill_id="reconcile-bank",
        skill_version="1.0.0",
        skill_hash="a" * 64,
        created_by=owner_id,
    )
    db.add(definition)
    db.flush()
    step = StepDefinition(
        id=f"{prefix}-step",
        workflow_definition_id=definition.id,
        department_id=department_id,
        step_key="validate-files",
        name="文件校验",
        step_type="file_validation",
        position=0,
        timeout_seconds=30,
        max_attempts=1,
        worker_pool="python",
    )
    db.add(step)
    db.flush()
    step_run = StepRun(
        id=f"{prefix}-step-run",
        step_definition_id=step.id,
        run_id=run.id,
        owner_id=owner_id,
        department_id=department_id,
    )
    db.add(step_run)
    db.flush()
    return run, step_run


def test_step_execution_keeps_versioned_file_and_approval_snapshots() -> None:
    from app.models import (
        ApprovalBinding,
        ArtifactBinding,
        StepDefinition,
        StepRun,
        WorkflowDefinition,
    )

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)

    with Session(engine) as db:
        db.add(
            User(
                id="user-1",
                username="finance-admin",
                display_name="财务管理员",
                password_hash="not-used-by-this-test",
                role="skill_admin",
                department_id="finance",
            )
        )
        db.add(
            RunRecord(
                id="run-1",
                owner_id="user-1",
                owner_name="财务管理员",
                department_id="finance",
                skill_id="reconcile-bank",
                skill_name="银行流水核对",
                skill_version="1.0.0",
                skill_hash="a" * 64,
                manifest_path="skills/reconcile-bank/tool.yaml",
                manifest_snapshot="{}",
                adapter="python",
                worker_pool="python",
            )
        )
        db.add(
            FileRecord(
                id="file-1",
                owner_id="user-1",
                department_id="finance",
                kind="input",
                original_name="bank.xlsx",
                stored_path="uploads/user-1/file-1/bank.xlsx",
                size_bytes=128,
                sha256="b" * 64,
            )
        )
        db.flush()
        db.add(
            ApprovalRecord(
                id="approval-1",
                resource_type="run",
                resource_id="run-1",
                run_id="run-1",
                department_id="finance",
                skill_id="reconcile-bank",
                snapshot_sha256="c" * 64,
                preview_sha256="d" * 64,
                snapshot_json="{}",
                preview_json="{}",
                requested_by="user-1",
                expires_at=now + timedelta(hours=1),
            )
        )
        db.flush()
        definition = WorkflowDefinition(
            id="definition-1",
            department_id="finance",
            workflow_key="reconcile-bank-default",
            name="银行流水核对标准流程",
            version="1",
            status="published",
            skill_id="reconcile-bank",
            skill_version="1.0.0",
            skill_hash="a" * 64,
            created_by="user-1",
        )
        step = StepDefinition(
            id="step-1",
            workflow_definition_id="definition-1",
            step_key="validate-files",
            name="校验平台文件",
            step_type="file_validation",
            position=1,
            input_schema_json='{"type":"object"}',
            output_schema_json='{"type":"object"}',
            timeout_seconds=60,
            max_attempts=1,
            risk_level="read_only",
            worker_pool="python",
        )
        step_run = StepRun(
            id="step-run-1",
            step_definition_id="step-1",
            run_id="run-1",
            owner_id="user-1",
            department_id="finance",
            state="pending",
            input_summary_json='{"file_count":1}',
        )
        artifact = ArtifactBinding(
            id="artifact-1",
            step_run_id="step-run-1",
            file_id="file-1",
            owner_id="user-1",
            department_id="finance",
            direction="input",
            role="bank_statement",
            sha256="b" * 64,
        )
        approval = ApprovalBinding(
            id="approval-binding-1",
            step_run_id="step-run-1",
            approval_record_id="approval-1",
            owner_id="user-1",
            department_id="finance",
            snapshot_sha256="c" * 64,
        )
        db.add(definition)
        db.flush()
        db.add(step)
        db.flush()
        db.add(step_run)
        db.flush()
        db.add_all([artifact, approval])
        db.commit()

        file_record = db.get(FileRecord, "file-1")
        assert file_record is not None
        file_record.sha256 = "e" * 64
        db.commit()

        saved_step = db.scalar(select(StepDefinition).where(StepDefinition.id == "step-1"))
        saved_run = db.scalar(select(StepRun).where(StepRun.id == "step-run-1"))
        saved_artifact = db.scalar(
            select(ArtifactBinding).where(ArtifactBinding.id == "artifact-1")
        )
        saved_approval = db.scalar(
            select(ApprovalBinding).where(ApprovalBinding.id == "approval-binding-1")
        )

        assert saved_step is not None and saved_step.workflow_definition_id == definition.id
        assert saved_run is not None and saved_run.run_id == "run-1"
        assert saved_run.workflow_session_id is None
        assert saved_artifact is not None and saved_artifact.sha256 == "b" * 64
        assert saved_approval is not None and saved_approval.snapshot_sha256 == "c" * 64

    engine.dispose()


def test_workflow_step_runs_are_scoped_to_their_owner() -> None:
    from app.models import StepDefinition, StepRun, WorkflowDefinition

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            User(
                id="admin-1",
                username="admin-1",
                password_hash="not-used-by-this-test",
                role="skill_admin",
                department_id="finance",
            )
        )
        db.add_all(
            [
                WorkflowSession(
                    id="workflow-user-1",
                    owner_id="user-1",
                    department_id="finance",
                    skill_id="ar-hexiao-daily",
                    skill_name="应收核销日清",
                    skill_version="1.5.1",
                    skill_hash="1" * 64,
                    model_connection_id="model-1",
                    model_provider="qwen",
                    model_name="qwen-plus",
                ),
                WorkflowSession(
                    id="workflow-user-2",
                    owner_id="user-2",
                    department_id="finance",
                    skill_id="ar-hexiao-daily",
                    skill_name="应收核销日清",
                    skill_version="1.5.1",
                    skill_hash="1" * 64,
                    model_connection_id="model-1",
                    model_provider="qwen",
                    model_name="qwen-plus",
                ),
            ]
        )
        db.flush()
        db.add(
            WorkflowDefinition(
                id="definition-owner-scope",
                department_id="finance",
                workflow_key="ar-hexiao-daily-default",
                name="应收核销受控流程",
                version="1",
                status="published",
                skill_id="ar-hexiao-daily",
                skill_version="1.5.1",
                skill_hash="1" * 64,
                created_by="admin-1",
            )
        )
        db.flush()
        db.add(
            StepDefinition(
                id="step-owner-scope",
                workflow_definition_id="definition-owner-scope",
                step_key="validate-parameters",
                name="参数校验",
                step_type="parameter_validation",
                position=0,
                timeout_seconds=30,
                max_attempts=1,
                worker_pool="workflow",
            )
        )
        db.flush()
        db.add_all(
            [
                StepRun(
                    id="step-run-user-1",
                    step_definition_id="step-owner-scope",
                    workflow_session_id="workflow-user-1",
                    owner_id="user-1",
                    department_id="finance",
                ),
                StepRun(
                    id="step-run-user-2",
                    step_definition_id="step-owner-scope",
                    workflow_session_id="workflow-user-2",
                    owner_id="user-2",
                    department_id="finance",
                ),
            ]
        )
        db.commit()

        visible = db.scalars(
            select(StepRun).where(
                StepRun.owner_id == "user-1",
                StepRun.department_id == "finance",
            )
        ).all()

        assert [item.id for item in visible] == ["step-run-user-1"]
        assert visible[0].run_id is None
        assert visible[0].workflow_session_id == "workflow-user-1"

    engine.dispose()


def test_step_definition_rejects_uncontrolled_step_type() -> None:
    from app.models import StepDefinition, WorkflowDefinition

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            User(
                id="admin-step-types",
                username="admin-step-types",
                password_hash="not-used-by-this-test",
                role="skill_admin",
                department_id="finance",
            )
        )
        db.flush()
        db.add(
            WorkflowDefinition(
                id="definition-step-types",
                department_id="finance",
                workflow_key="controlled-types",
                name="受控步骤类型",
                version="1",
                skill_id="reconcile-bank",
                skill_version="1.0.0",
                skill_hash="f" * 64,
                created_by="admin-step-types",
            )
        )
        db.flush()
        db.add(
            StepDefinition(
                id="step-uncontrolled",
                workflow_definition_id="definition-step-types",
                step_key="unrestricted-shell",
                name="任意命令",
                step_type="unrestricted_shell",
                position=0,
                timeout_seconds=30,
                max_attempts=1,
                worker_pool="python",
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

    engine.dispose()


@pytest.mark.parametrize(
    ("owner_id", "department_id"),
    [
        ("other-user", "finance"),
        ("user-scope", "other-department"),
    ],
)
def test_step_run_rejects_run_scope_mismatch(owner_id: str, department_id: str) -> None:
    from app.models import StepDefinition, StepRun, WorkflowDefinition

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            User(
                id="admin-scope",
                username="admin-scope",
                password_hash="not-used-by-this-test",
                role="skill_admin",
                department_id="finance",
            )
        )
        db.add(
            RunRecord(
                id="run-scope",
                owner_id="user-scope",
                department_id="finance",
                skill_id="reconcile-bank",
                skill_name="银行流水核对",
                skill_version="1.0.0",
                skill_hash="a" * 64,
                manifest_path="skills/reconcile-bank/tool.yaml",
                manifest_snapshot="{}",
                adapter="python",
                worker_pool="python",
            )
        )
        db.flush()
        db.add(
            WorkflowDefinition(
                id="definition-scope",
                department_id="finance",
                workflow_key="scope-check",
                name="范围校验流程",
                version="1",
                skill_id="reconcile-bank",
                skill_version="1.0.0",
                skill_hash="a" * 64,
                created_by="admin-scope",
            )
        )
        db.flush()
        step = StepDefinition(
            id="step-scope",
            workflow_definition_id="definition-scope",
            step_key="validate-files",
            name="文件校验",
            step_type="file_validation",
            position=0,
            timeout_seconds=30,
            max_attempts=1,
            worker_pool="python",
        )
        step.department_id = "finance"
        db.add(step)
        db.flush()
        db.add(
            StepRun(
                id="step-run-scope",
                step_definition_id="step-scope",
                run_id="run-scope",
                owner_id=owner_id,
                department_id=department_id,
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

    engine.dispose()


def test_step_run_rejects_step_definition_department_mismatch() -> None:
    from app.models import StepDefinition, StepRun, WorkflowDefinition

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            User(
                id="admin-definition-scope",
                username="admin-definition-scope",
                password_hash="not-used-by-this-test",
                role="skill_admin",
                department_id="other-department",
            )
        )
        db.add(
            RunRecord(
                id="run-definition-scope",
                owner_id="user-definition-scope",
                department_id="finance",
                skill_id="reconcile-bank",
                skill_name="银行流水核对",
                skill_version="1.0.0",
                skill_hash="a" * 64,
                manifest_path="skills/reconcile-bank/tool.yaml",
                manifest_snapshot="{}",
                adapter="python",
                worker_pool="python",
            )
        )
        db.flush()
        db.add(
            WorkflowDefinition(
                id="definition-other-department",
                department_id="other-department",
                workflow_key="other-department-flow",
                name="其他部门流程",
                version="1",
                skill_id="reconcile-bank",
                skill_version="1.0.0",
                skill_hash="a" * 64,
                created_by="admin-definition-scope",
            )
        )
        db.flush()
        step = StepDefinition(
            id="step-other-department",
            workflow_definition_id="definition-other-department",
            step_key="validate-files",
            name="文件校验",
            step_type="file_validation",
            position=0,
            timeout_seconds=30,
            max_attempts=1,
            worker_pool="python",
        )
        step.department_id = "other-department"
        db.add(step)
        db.flush()
        db.add(
            StepRun(
                id="step-run-definition-scope",
                step_definition_id="step-other-department",
                run_id="run-definition-scope",
                owner_id="user-definition-scope",
                department_id="finance",
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

    engine.dispose()


@pytest.mark.parametrize(
    ("owner_id", "department_id"),
    [
        ("other-user", "finance"),
        ("workflow-owner", "other-department"),
    ],
)
def test_step_run_rejects_workflow_scope_mismatch(
    owner_id: str,
    department_id: str,
) -> None:
    from app.models import StepDefinition, StepRun, WorkflowDefinition

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            User(
                id="admin-workflow-scope",
                username="admin-workflow-scope",
                password_hash="not-used-by-this-test",
                role="skill_admin",
                department_id="finance",
            )
        )
        db.add(
            WorkflowSession(
                id="workflow-scope",
                owner_id="workflow-owner",
                department_id="finance",
                skill_id="ar-hexiao-daily",
                skill_name="应收核销日清",
                skill_version="1.5.1",
                skill_hash="1" * 64,
                model_connection_id="model-1",
                model_provider="qwen",
                model_name="qwen-plus",
            )
        )
        db.flush()
        db.add(
            WorkflowDefinition(
                id="definition-workflow-scope",
                department_id="finance",
                workflow_key="workflow-scope",
                name="工作流范围校验",
                version="1",
                skill_id="ar-hexiao-daily",
                skill_version="1.5.1",
                skill_hash="1" * 64,
                created_by="admin-workflow-scope",
            )
        )
        db.flush()
        db.add(
            StepDefinition(
                id="step-workflow-scope",
                workflow_definition_id="definition-workflow-scope",
                department_id="finance",
                step_key="validate-parameters",
                name="参数校验",
                step_type="parameter_validation",
                position=0,
                timeout_seconds=30,
                max_attempts=1,
                worker_pool="workflow",
            )
        )
        db.flush()
        db.add(
            StepRun(
                id="step-run-workflow-scope",
                step_definition_id="step-workflow-scope",
                workflow_session_id="workflow-scope",
                owner_id=owner_id,
                department_id=department_id,
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

    engine.dispose()


@pytest.mark.parametrize(
    ("binding_owner", "file_owner"),
    [
        ("artifact-other-owner", "artifact-other-owner"),
        ("artifact-run-owner", "artifact-other-owner"),
    ],
)
def test_artifact_binding_rejects_parent_scope_mismatch(
    binding_owner: str,
    file_owner: str,
) -> None:
    from app.models import ArtifactBinding

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        _, step_run = _add_standard_step_run(
            db,
            prefix="artifact-scope",
            owner_id="artifact-run-owner",
        )
        db.add(
            FileRecord(
                id="artifact-scope-file",
                owner_id=file_owner,
                department_id="finance",
                kind="input",
                original_name="bank.xlsx",
                stored_path="uploads/bank.xlsx",
                size_bytes=128,
                sha256="b" * 64,
            )
        )
        db.flush()
        db.add(
            ArtifactBinding(
                id="artifact-scope-binding",
                step_run_id=step_run.id,
                file_id="artifact-scope-file",
                owner_id=binding_owner,
                department_id="finance",
                direction="input",
                role="bank_statement",
                sha256="b" * 64,
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

    engine.dispose()


@pytest.mark.parametrize(
    ("binding_owner", "approval_owner"),
    [
        ("approval-other-owner", "approval-other-owner"),
        ("approval-run-owner", "approval-other-owner"),
    ],
)
def test_approval_binding_rejects_parent_scope_mismatch(
    binding_owner: str,
    approval_owner: str,
) -> None:
    from app.models import ApprovalBinding

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)

    with Session(engine) as db:
        run, step_run = _add_standard_step_run(
            db,
            prefix="approval-scope",
            owner_id="approval-run-owner",
        )
        db.add(
            User(
                id="approval-other-owner",
                username="approval-other-owner",
                password_hash="not-used-by-this-test",
                department_id="finance",
            )
        )
        db.flush()
        db.add(
            ApprovalRecord(
                id="approval-scope-record",
                resource_type="run",
                resource_id=run.id,
                run_id=run.id,
                department_id="finance",
                skill_id="reconcile-bank",
                snapshot_sha256="c" * 64,
                preview_sha256="d" * 64,
                snapshot_json="{}",
                preview_json="{}",
                requested_by=approval_owner,
                expires_at=now + timedelta(hours=1),
            )
        )
        db.flush()
        db.add(
            ApprovalBinding(
                id="approval-scope-binding",
                step_run_id=step_run.id,
                approval_record_id="approval-scope-record",
                owner_id=binding_owner,
                department_id="finance",
                snapshot_sha256="c" * 64,
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

    engine.dispose()


@pytest.mark.parametrize(
    ("max_attempts", "retryable"),
    [
        (2, False),
        (1, True),
    ],
)
def test_non_idempotent_step_rejects_retry_configuration(
    max_attempts: int,
    retryable: bool,
) -> None:
    from app.models import StepDefinition

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        _, step_run = _add_standard_step_run(
            db,
            prefix="non-idempotent-retry",
            owner_id="non-idempotent-owner",
        )
        step = db.get(StepDefinition, step_run.step_definition_id)
        assert step is not None
        step.is_idempotent = False
        step.max_attempts = max_attempts
        step.retryable = retryable

        with pytest.raises(IntegrityError):
            db.commit()

    engine.dispose()


def test_non_idempotent_step_run_cannot_be_marked_retryable() -> None:
    from app.models import StepDefinition

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        _, step_run = _add_standard_step_run(
            db,
            prefix="non-idempotent-step-run",
            owner_id="non-idempotent-step-run-owner",
        )
        step = db.get(StepDefinition, step_run.step_definition_id)
        assert step is not None
        step.is_idempotent = False
        step.retryable = False
        step.max_attempts = 1
        db.commit()

        step_run.can_retry = True
        with pytest.raises(ValueError, match="idempotent"):
            db.commit()

    engine.dispose()


def test_workflow_creator_must_belong_to_definition_department() -> None:
    from app.models import WorkflowDefinition

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            User(
                id="cross-department-creator",
                username="cross-department-creator",
                display_name="跨部门创建者",
                password_hash="hash",
                role="skill_admin",
                department_id="other-department",
            )
        )
        db.flush()
        db.add(
            WorkflowDefinition(
                id="cross-department-definition",
                department_id="finance",
                workflow_key="cross-department-definition",
                name="非法跨部门流程",
                version="1",
                status="draft",
                skill_id="synthetic-skill",
                skill_version="1.0.0",
                skill_hash="a" * 64,
                created_by="cross-department-creator",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()

    engine.dispose()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("workflow_status", "public"),
        ("step_risk", "unrestricted"),
        ("step_worker_pool", "shell"),
        ("step_run_state", "thinking"),
    ],
)
def test_workflow_step_models_reject_uncontrolled_values(
    field: str,
    invalid_value: str,
) -> None:
    from app.models import StepDefinition, WorkflowDefinition

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        _, step_run = _add_standard_step_run(
            db,
            prefix=f"controlled-{field}",
            owner_id=f"controlled-{field}-owner",
        )
        step = db.get(StepDefinition, step_run.step_definition_id)
        assert step is not None
        definition = db.get(WorkflowDefinition, step.workflow_definition_id)
        assert definition is not None

        if field == "workflow_status":
            definition.status = invalid_value
        elif field == "step_risk":
            step.risk_level = invalid_value
        elif field == "step_worker_pool":
            step.worker_pool = invalid_value
        else:
            step_run.state = invalid_value

        with pytest.raises(IntegrityError):
            db.commit()

    engine.dispose()


@pytest.mark.parametrize("binding_kind", ["artifact", "approval"])
def test_binding_snapshots_are_immutable_after_insert(binding_kind: str) -> None:
    from app.models import ApprovalBinding, ArtifactBinding

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)

    with Session(engine) as db:
        run, step_run = _add_standard_step_run(
            db,
            prefix=f"immutable-{binding_kind}",
            owner_id=f"immutable-{binding_kind}-owner",
        )
        if binding_kind == "artifact":
            db.add(
                FileRecord(
                    id="immutable-artifact-file",
                    owner_id=step_run.owner_id,
                    department_id=step_run.department_id,
                    kind="input",
                    original_name="source.xlsx",
                    stored_path="uploads/source.xlsx",
                    size_bytes=128,
                    sha256="b" * 64,
                )
            )
            db.flush()
            binding = ArtifactBinding(
                id="immutable-artifact-binding",
                step_run_id=step_run.id,
                file_id="immutable-artifact-file",
                owner_id=step_run.owner_id,
                department_id=step_run.department_id,
                direction="input",
                role="source",
                sha256="b" * 64,
            )
        else:
            db.add(
                ApprovalRecord(
                    id="immutable-approval-record",
                    resource_type="run",
                    resource_id=run.id,
                    run_id=run.id,
                    department_id=step_run.department_id,
                    skill_id=run.skill_id,
                    snapshot_sha256="c" * 64,
                    preview_sha256="d" * 64,
                    snapshot_json="{}",
                    preview_json="{}",
                    requested_by=step_run.owner_id,
                    expires_at=now + timedelta(hours=1),
                )
            )
            db.flush()
            binding = ApprovalBinding(
                id="immutable-approval-binding",
                step_run_id=step_run.id,
                approval_record_id="immutable-approval-record",
                owner_id=step_run.owner_id,
                department_id=step_run.department_id,
                snapshot_sha256="c" * 64,
            )
        db.add(binding)
        db.commit()

        if binding_kind == "artifact":
            binding.metadata_json = '{"changed":true}'
        else:
            binding.snapshot_sha256 = "e" * 64

        with pytest.raises(ValueError, match="immutable"):
            db.commit()

        db.rollback()
        stored = db.get(type(binding), binding.id)
        assert stored is not None
        db.delete(stored)
        with pytest.raises(ValueError, match="cannot be deleted"):
            db.flush()

    engine.dispose()


def test_legacy_standard_run_worker_claim_does_not_require_step_rows() -> None:
    from app.models import StepRun
    from app.worker import claim_next_run

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            User(
                id="legacy-worker-owner",
                username="legacy-worker-owner",
                password_hash="not-used-by-this-test",
                department_id="finance",
            )
        )
        run = RunRecord(
            id="legacy-worker-run",
            owner_id="legacy-worker-owner",
            department_id="finance",
            skill_id="legacy-compatibility",
            skill_name="旧标准任务",
            skill_version="1.0.0",
            skill_hash="a" * 64,
            manifest_path="skills/legacy/tool.yaml",
            manifest_snapshot=_legacy_read_only_manifest(),
            adapter="python",
            worker_pool="python",
            state="queued",
            queued_at=datetime.now(UTC),
        )
        db.add(run)
        db.commit()
        assert list(db.scalars(select(StepRun).where(StepRun.run_id == run.id))) == []

        claimed = claim_next_run(db, ("python",), "legacy-worker")

        assert claimed is not None
        assert claimed.id == run.id
        assert claimed.state == "running"

    engine.dispose()


def test_legacy_workflow_worker_claim_does_not_require_step_rows() -> None:
    from app.auth_models import UserSkillPermission
    from app.models import StepRun, WorkflowAction
    from app.resource_policy import workflow_root
    from app.workflow_service import claim_next_workflow_action

    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(User(id="legacy-workflow-owner", username="legacy-workflow-owner",
                    password_hash="not-used", department_id="finance"))
        db.flush()
        db.add(UserSkillPermission(id=str(uuid.uuid4()), user_id="legacy-workflow-owner",
                                   skill_id="ar-hexiao-daily", can_run=True))
        workflow = WorkflowSession(
            id="legacy-worker-workflow",
            owner_id="legacy-workflow-owner",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="旧工作流任务",
            skill_version="1.5.1",
            skill_hash="b" * 64,
            model_connection_id="model-legacy",
            model_provider="qwen",
            model_name="qwen-plus",
            state="running",
            stage="preparing",
        )
        action = WorkflowAction(
            id="legacy-workflow-action",
            workflow_id=workflow.id,
            name="prepare_worklist",
            state="queued",
        )
        db.add_all([workflow, action])
        db.commit()
        (workflow_root(workflow.owner_id, workflow.id) / "skill").mkdir(parents=True, exist_ok=True)

        claimed = claim_next_workflow_action(db, ("workflow",), "legacy-workflow-worker")

        assert claimed is not None
        assert claimed.id == action.id
        assert claimed.state == "running"
        assert list(
            db.scalars(
                select(StepRun).where(StepRun.workflow_session_id == workflow.id)
            )
        ) == []

    engine.dispose()


def test_legacy_run_step_api_returns_empty_timeline() -> None:
    from helpers import auth_client

    from app.auth_service import get_user_by_username
    from app.database import SessionLocal, init_db

    init_db()
    username = f"legacy-step-api-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())

    with auth_client(username=username) as client:
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            db.add(
                RunRecord(
                    id=run_id,
                    owner_id=user.id,
                    owner_name=user.display_name,
                    department_id=user.department_id,
                    skill_id="legacy-compatibility",
                    skill_name="旧任务 API 兼容",
                    skill_version="1.0.0",
                    skill_hash="a" * 64,
                    manifest_path="skills/legacy/tool.yaml",
                    manifest_snapshot=_legacy_read_only_manifest(),
                    adapter="python",
                    worker_pool="python",
                )
            )
            db.commit()

        response = client.get(f"/api/runs/{run_id}/steps")
        assert response.status_code == 200, response.text
        assert response.json() == []
