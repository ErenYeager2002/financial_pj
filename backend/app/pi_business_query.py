"""Read-only platform tool dispatch, with existing business permission services."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field
from .database import SessionLocal
from .pi_business_access import authenticate
from .redaction import sanitize_text
from .audit_service import record_audit

router = APIRouter()

class Query(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: UUID
    resource: Literal['tasks', 'skills', 'ar_materials']
    page: int = Field(default=1, ge=1, le=100000)
    query: str = Field(default='', max_length=128)
    state: Literal['pending','running','failed','succeeded','cancelled'] | None = None
    skill_id: str = Field(default='', max_length=128)


def clean(value):
    if isinstance(value, str):
        return sanitize_text(value, max_length=20000)
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        forbidden = {'owner_id','owner_name','department_id','source_path','stored_path','api_key','password','token','credential','sha256'}
        return {key:clean(item) for key,item in value.items() if key not in forbidden}
    return value


def query_platform(db, user, body):
    if body.resource == 'tasks':
        from .task_center_service import query_task_center
        return query_task_center(db,user,page=body.page,page_size=20,query=body.query,
                                 view_state=body.state,skill_id=body.skill_id).model_dump(mode='json')
    from .registry import registry
    registry.refresh()
    if body.resource == 'ar_materials':
        from .assistant_workflow_service import inspect_materials
        return inspect_materials(db,user,body.skill_id)[0]
    from .authorization import allowed_skill_ids
    allowed = allowed_skill_ids(db,user)
    fixed = [{'id':item.manifest.id,'name':item.manifest.name,'description':item.manifest.description,
              'version':item.manifest.version,'kind':'workflow_tool'}
             for item in registry.list() if user.is_admin or item.manifest.id in allowed]
    from .native_skill_policy import visible_native_skills
    from .native_skill_service import list_native_skills
    native = [{'id':item.id,'name':item.name,'description':item.description,'kind':'native_skill'}
              for item in visible_native_skills(db,user,list_native_skills())]
    return {'tools':fixed,'installed_skills':native}


@router.post('/platform/query')
def query(body: Query, authorization: str = Header(default='')):
    with SessionLocal() as db:
        user = authenticate(db,authorization,str(body.session_id))
        value = clean(query_platform(db,user,body))
        record_audit(db,actor=user,action='pi.business.query',resource_type='pi_session',
                     resource_id=str(body.session_id),details={'resource':body.resource})
        db.commit()
        return {'source':'live_platform','data':value}


class Proposal(BaseModel):
    model_config=ConfigDict(extra='forbid')
    session_id: UUID
    skill_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,71}$')
    base_commit: str = Field(pattern=r'^[a-f0-9]{40}$')
    archive: str = Field(max_length=8388608)

@router.post('/platform/skill-proposal')
def proposal(body: Proposal, authorization: str = Header(default='')):
    from .pi_skill_drafts import propose
    with SessionLocal() as db:
        user=authenticate(db,authorization,str(body.session_id))
        return propose(db,user,str(body.session_id),body.skill_id,body.base_commit,body.archive)
