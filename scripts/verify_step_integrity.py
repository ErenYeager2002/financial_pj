from __future__ import annotations

import uuid

from app.auth_models import User
from app.database import engine
from app.models import (
    ArtifactBinding,
    FileRecord,
    RunRecord,
    StepDefinition,
    StepRun,
    WorkflowDefinition,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


def _expect_rejected(db: Session, statement: str, label: str) -> None:
    try:
        with db.begin_nested():
            db.execute(text(statement))
    except DBAPIError:
        return
    raise RuntimeError(f"完整性检查失败：{label} 未被数据库拒绝。")


def main() -> None:
    prefix = f"integrity-{uuid.uuid4().hex[:10]}"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as db:
                user = User(
                    id=f"{prefix}-user",
                    username=f"{prefix}-user",
                    password_hash="unused",
                    role="skill_admin",
                    department_id="finance",
                )
                run = RunRecord(
                    id=f"{prefix}-run",
                    owner_id=user.id,
                    owner_name="完整性检查",
                    department_id="finance",
                    skill_id="integrity-check",
                    skill_name="完整性检查",
                    skill_version="1.0.0",
                    skill_hash="a" * 64,
                    manifest_path="tool.yaml",
                    manifest_snapshot="{}",
                    adapter="python",
                    worker_pool="python",
                )
                file_record = FileRecord(
                    id=f"{prefix}-file",
                    owner_id=user.id,
                    department_id="finance",
                    kind="input",
                    original_name="synthetic.xlsx",
                    stored_path="synthetic.xlsx",
                    size_bytes=1,
                    sha256="b" * 64,
                )
                db.add_all([user, run, file_record])
                db.flush()
                definition = WorkflowDefinition(
                    id=f"{prefix}-definition",
                    department_id="finance",
                    workflow_key=prefix,
                    name="完整性检查",
                    version="1",
                    status="published",
                    skill_id="integrity-check",
                    skill_version="1.0.0",
                    skill_hash="a" * 64,
                    created_by=user.id,
                )
                db.add(definition)
                db.flush()
                step = StepDefinition(
                    id=f"{prefix}-step",
                    workflow_definition_id=definition.id,
                    department_id="finance",
                    step_key="validate",
                    name="校验",
                    step_type="file_validation",
                    position=10,
                    worker_pool="python",
                )
                db.add(step)
                db.flush()
                step_run = StepRun(
                    id=f"{prefix}-step-run",
                    step_definition_id=step.id,
                    run_id=run.id,
                    owner_id=user.id,
                    department_id="finance",
                )
                db.add(step_run)
                db.flush()
                binding = ArtifactBinding(
                    id=f"{prefix}-binding",
                    step_run_id=step_run.id,
                    file_id=file_record.id,
                    owner_id=user.id,
                    department_id="finance",
                    direction="input",
                    role="source",
                    sha256=file_record.sha256,
                )
                db.add(binding)
                db.flush()

                _expect_rejected(
                    db,
                    f"UPDATE artifact_bindings SET role='changed' WHERE id='{binding.id}'",
                    "绑定更新",
                )
                _expect_rejected(
                    db,
                    f"DELETE FROM artifact_bindings WHERE id='{binding.id}'",
                    "绑定删除",
                )
                _expect_rejected(
                    db,
                    f"UPDATE step_runs SET can_retry=true WHERE id='{step_run.id}'",
                    "非幂等步骤重试",
                )
                print("PostgreSQL 步骤完整性检查通过。")
        finally:
            transaction.rollback()


if __name__ == "__main__":
    main()
