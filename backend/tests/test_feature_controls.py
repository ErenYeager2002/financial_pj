from __future__ import annotations

from helpers import auth_client
from sqlalchemy import delete, select

from app.database import SessionLocal, init_db
from app.feature_control_service import TASK_DISCOVERY, task_discovery_enabled
from app.models import AuditEvent, PlatformFeatureControl


def _clear_task_discovery_override() -> None:
    init_db()
    with SessionLocal() as db:
        db.execute(
            delete(PlatformFeatureControl).where(PlatformFeatureControl.key == TASK_DISCOVERY)
        )
        db.commit()


def test_admin_can_manage_task_discovery_in_unified_feature_list() -> None:
    _clear_task_discovery_override()
    try:
        with auth_client(role="skill_admin", username="feature-control-admin") as admin:
            listed = admin.get("/api/admin/feature-controls")
            assert listed.status_code == 200, listed.text
            controls = {item["key"]: item for item in listed.json()}
            assert set(controls) == {
                "task-discovery",
                "ar-hexiao-execution",
                "local-session-login",
                "clerk-login",
            }
            assert controls[TASK_DISCOVERY]["editable"] is True

            enabled = admin.put(
                f"/api/admin/feature-controls/{TASK_DISCOVERY}",
                json={"enabled": True},
            )
            assert enabled.status_code == 200, enabled.text
            assert enabled.json()["enabled"] is True
            assert enabled.json()["source"] == "administrator"

            blocked = admin.put(
                "/api/admin/feature-controls/ar-hexiao-execution",
                json={"enabled": True},
            )
            assert blocked.status_code == 409, blocked.text

        with SessionLocal() as db:
            assert task_discovery_enabled(db) is True
            audit = db.scalar(
                select(AuditEvent)
                .where(AuditEvent.action == "admin.feature_control.update")
                .order_by(AuditEvent.id.desc())
            )
            assert audit is not None
            assert audit.resource_id == TASK_DISCOVERY
    finally:
        _clear_task_discovery_override()


def test_non_admin_cannot_read_or_change_feature_controls() -> None:
    with auth_client(username="feature-control-user") as employee:
        assert employee.get("/api/admin/feature-controls").status_code == 403
        assert (
            employee.put(
                f"/api/admin/feature-controls/{TASK_DISCOVERY}",
                json={"enabled": True},
            ).status_code
            == 403
        )
