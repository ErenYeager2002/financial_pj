"""Native capability grants share platform identity, not fixed-tool IDs."""
from .authorization import assert_skill_permission, allowed_skill_ids, refresh_active_user

def require_native_skill(db, user, name, capability="can_run"):
    user = refresh_active_user(db, user)
    assert_skill_permission(db, user, "native--" + name, capability)
    return user

def visible_native_skills(db, user, skills):
    user = refresh_active_user(db, user)
    if user.is_admin:
        return skills
    allowed = allowed_skill_ids(db, user)
    return [item for item in skills if "native--" + item.id in allowed]
