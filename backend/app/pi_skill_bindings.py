"""Resolve only server-authorized installed Skill versions for official Pi."""
import json
from . import native_skill_service as native
from .native_skill_policy import require_native_skill, visible_native_skills
from . import pi_runtime_service as runtime


def selected(db, user, skill_id):
    require_native_skill(db, user, skill_id)
    item = native.installed_skill(skill_id)
    return {"id": item.id, "commit": item.commit}


def for_session(db, user, session_id):
    session_id = runtime.require_session(user, session_id, check_skill=False)
    record = json.loads((runtime.catalog(user) / (session_id + '.json')).read_text())
    if record.get('skill_id'):
        require_native_skill(db, user, record['skill_id'])
        return [{"id":record['skill_id'], "commit":record['skill_commit']}]
    return [{"id":item.id, "commit":item.commit} for item in visible_native_skills(db, user, native.list_native_skills())]


def require_upload(db, user, session_id):
    session_id = runtime.require_session(user, session_id)
    record = json.loads((runtime.catalog(user) / (session_id + '.json')).read_text())
    names = [record['skill_id']] if record.get('skill_id') else list({*[item['id'] for item in for_session(db, user, session_id)], *record.get('mounted_skill_ids', [])})
    for name in names:
        require_native_skill(db, user, name, 'can_upload')
