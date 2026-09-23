"""Resolve only server-authorized installed Skill versions for official Pi."""
import json
from . import native_skill_service as native
from .native_skill_policy import require_native_skill
from . import pi_runtime_service as runtime


def selected(db, user, skill_id):
    require_native_skill(db, user, skill_id)
    item = native.installed_skill(skill_id)
    return {"id": item.id, "commit": item.commit}


def _bindings_for_names(db, user, names):
    bindings = []
    for name in dict.fromkeys(names):
        require_native_skill(db, user, name)
        item = native.installed_skill(name)
        bindings.append({"id": item.id, "commit": item.commit})
    return bindings


def for_session(db, user, session_id):
    session_id = runtime.require_session(user, session_id, check_skill=False)
    record = json.loads((runtime.catalog(user) / (session_id + '.json')).read_text())
    if record.get('skill_id'):
        return [{"id": record['skill_id'], "commit": record['skill_commit']}]
    # A general Pi session starts with no native packages. Skills are mounted
    # only when the caller selected them explicitly or an older session already
    # recorded an explicit mounted list. This prevents a default session from
    # receiving every visible package, including write-capable packages.
    return _bindings_for_names(db, user, record.get('mounted_skill_ids') or [])


def require_upload(db, user, session_id):
    session_id = runtime.require_session(user, session_id)
    record = json.loads((runtime.catalog(user) / (session_id + '.json')).read_text())
    names = [record['skill_id']] if record.get('skill_id') else record.get('mounted_skill_ids') or []
    for name in names:
        require_native_skill(db, user, name, 'can_upload')
