"""Material page and mutation entry points share the authoritative safety policy."""
from .ar_execution_safety import (
    ACTIVE_MATERIAL_MESSAGE as MESSAGE,
    MaterialOccupancyConflict,
    assert_operation_allowed,
    get_safety_view,
)


def material_edit_state(db, user, skill_id):
    view = get_safety_view(db, user.user_id, user.department_id, skill_id,
                          operation="replace_materials")
    return {"locked": not view["material_admission_allowed"], "reason": view["message"]}


def assert_material_editable(db, user, skill_id):
    from .workflow_material_service import MaterialVersionConflict
    try:
        assert_operation_allowed(db, user.user_id, user.department_id, skill_id,
                                 operation="replace_materials")
    except MaterialOccupancyConflict as exc:
        raise MaterialVersionConflict(str(exc)) from exc
