from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import UserContext, get_current_user, require_admin
from ..contracts import WorkflowDefinitionRead
from ..database import get_db
from ..workflow_definition_service import list_workflow_definitions

router = APIRouter(tags=["admin-workflows"])


@router.get(
    "/api/admin/workflow-definitions",
    response_model=list[WorkflowDefinitionRead],
)
def admin_list_workflow_definitions(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[WorkflowDefinitionRead]:
    require_admin(user)
    return list_workflow_definitions(db, user)
