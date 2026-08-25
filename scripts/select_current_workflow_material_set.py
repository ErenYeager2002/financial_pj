from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.auth import UserContext
from app.auth_models import User
from app.database import SessionLocal, init_db
from app.models import FileRecord
from app.workflow_material_service import (
    create_or_replace_current_set,
    material_set_bindings,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="由管理员显式选择应收核销的当前权威年度表和到账流转表。"
    )
    result.add_argument("--admin-id", required=True, help="执行选择的平台管理员 ID")
    result.add_argument("--owner-id", required=True, help="材料所属平台用户 ID")
    result.add_argument("--skill-id", default="ar-hexiao-daily")
    result.add_argument("--ledger-file-id", action="append", required=True)
    result.add_argument("--flow-file-id", required=True)
    result.add_argument(
        "--apply",
        action="store_true",
        help="确认保存；不提供时只校验并回滚。",
    )
    return result


def _entry(record: FileRecord) -> dict[str, object]:
    return {
        "file_id": record.id,
        "name": record.original_name,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
    }


def main() -> int:
    args = parser().parse_args()
    init_db()
    with SessionLocal() as db:
        admin = db.get(User, args.admin_id)
        owner = db.get(User, args.owner_id)
        if not admin or admin.role != "skill_admin" or admin.status != "active":
            raise SystemExit("--admin-id 必须是已启用的平台 Skill 管理员。")
        if not owner or owner.status != "active":
            raise SystemExit("--owner-id 对应的平台用户不存在或已禁用。")
        if admin.department_id != owner.department_id:
            raise SystemExit("管理员与材料所属用户不在同一部门。")
        ledger_records = [db.get(FileRecord, file_id) for file_id in args.ledger_file_id]
        flow_record = db.get(FileRecord, args.flow_file_id)
        if any(record is None for record in ledger_records) or flow_record is None:
            raise SystemExit("指定的平台文件不存在。")

        user = UserContext(
            user_id=owner.id,
            display_name=owner.display_name,
            role=owner.role,
            department_id=owner.department_id,
        )
        selected = create_or_replace_current_set(
            db,
            user,
            args.skill_id,
            {
                "profit_loss_ledgers": [
                    _entry(record) for record in ledger_records if record is not None
                ],
                "receipt_flow_table": [_entry(flow_record)],
            },
        )
        bindings = material_set_bindings(db, selected)
        if args.apply:
            db.commit()
            mode = "已保存"
        else:
            db.rollback()
            mode = "校验通过，未保存"
        print(
            f"{mode}：V{selected.version}，年度表 "
            f"{len(bindings['profit_loss_ledgers'])} 份，到账流转表 1 份。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
