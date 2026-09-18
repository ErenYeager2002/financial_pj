from __future__ import annotations

from typing import Any, Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..auth import UserContext, get_current_user
from ..database import get_db
from ..audit_service import record_audit
from .. import pi_runtime_service as runtime

router = APIRouter(prefix='/api/pi-runtime', tags=['pi-runtime'])


class CreateSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(default='Pi 会话', max_length=200)
    channel: Literal['assistant','workspace'] = 'assistant'
    skill_id: str | None = Field(default=None, pattern=r'^[a-z][a-z0-9-]{0,71}$')


class Operation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['start', 'send', 'resize', 'poll', 'stop', 'jobs']
    payload: dict[str, Any] = Field(default_factory=dict)


@router.get('/sessions')
def list_sessions(user: UserContext = Depends(get_current_user)):
    return runtime.sessions(user)


@router.post('/sessions')
def create_session(body: CreateSession, user: UserContext = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    from ..pi_skill_bindings import selected
    skill = selected(db, user, body.skill_id) if body.skill_id else None
    result = runtime.create_session(user, body.title, skill, body.channel)
    record_audit(db, actor=user, action='pi.session.create', resource_type='pi_session', resource_id=result['id'])
    db.commit()
    return result


@router.post('/sessions/{session_id}/operate')
def operate(session_id: str, body: Operation, user: UserContext = Depends(get_current_user),
            db: Session = Depends(get_db)):
    if body.operation == 'jobs':
        from fastapi import HTTPException
        if body.payload.get('operation') not in {'list', 'poll', 'cancel'}:
            raise HTTPException(422, '无效的后台任务操作。')
    model_config = None
    business_config = None
    skill_bindings = None
    if body.operation == 'start':
        runtime.require_session(user, session_id, check_skill=False)
        from ..pi_model_access import provision
        model_config = provision(db, user)
        from ..pi_business_access import provision as provision_business
        business_config = provision_business(db,user,session_id)
        from ..pi_skill_bindings import for_session
        skill_bindings = for_session(db, user, session_id)
    result = runtime.operate(user, session_id, body.operation, body.payload, model_config=model_config, skill_bindings=skill_bindings, business_config=business_config)
    if body.operation in {'start', 'stop'}:
        record_audit(db, actor=user, action='pi.session.' + body.operation,
                     resource_type='pi_session', resource_id=session_id)
        db.commit()
    if body.operation == 'jobs' and body.payload.get('operation') == 'cancel':
        record_audit(db, actor=user, action='pi.job.cancel', resource_type='pi_session', resource_id=session_id)
        db.commit()
    return result


class FileOperation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['list','upload_begin','upload_chunk','upload_commit','upload_abort']
    source: Literal['workspace','inputs'] = 'workspace'
    path: str = Field(default='', max_length=4096)
    offset: int = Field(default=0, ge=0)
    upload_id: str | None = None
    name: str | None = None
    size: int | None = Field(default=None, ge=0, le=32 * 1024**3)
    data: str = Field(default='', max_length=1398104)


@router.post('/sessions/{session_id}/files')
def files(session_id: str, body: FileOperation, user: UserContext = Depends(get_current_user),
          db: Session = Depends(get_db)):
    if body.action.startswith('upload_'):
        from ..pi_skill_bindings import require_upload
        require_upload(db, user, session_id)
    result = runtime.operate(user, session_id, 'files', body.model_dump(exclude_none=True))
    if body.action == 'upload_commit':
        record_audit(db, actor=user, action='pi.file.upload', resource_type='pi_session', resource_id=session_id)
        db.commit()
    return result


@router.get('/sessions/{session_id}/download')
def download(session_id: str, path: str, source: Literal['workspace','inputs'] = 'workspace',
             user: UserContext = Depends(get_current_user), db: Session = Depends(get_db)):
    import base64
    from urllib.parse import quote
    from fastapi.responses import StreamingResponse
    payload = {'action':'read', 'source':source, 'path':path, 'offset':0}
    first = runtime.operate(user, session_id, 'files', payload)
    def content():
        current = first
        while True:
            data = base64.b64decode(current['data'], validate=True)
            if data: yield data
            if current['next'] >= first['size']: break
            if not data: raise RuntimeError('File download interrupted')
            current = runtime.operate(user, session_id, 'files',
                                      {**payload, 'offset':current['next'], 'version':first['version']})
    record_audit(db, actor=user, action='pi.file.download', resource_type='pi_session', resource_id=session_id)
    db.commit()
    return StreamingResponse(content(), media_type='application/octet-stream', headers={
        'Content-Length':str(first['size']), 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
        'Content-Disposition':"attachment; filename*=UTF-8''" + quote(first['name'], safe='')})


class PublishCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

@router.get('/skill-proposals')
def proposals(user: UserContext = Depends(get_current_user)):
    from ..pi_skill_drafts import visible
    values=visible(user)
    return {'can_publish':user.is_admin,'items':sorted(values,key=lambda x:x['created_at'],reverse=True)[:30]}

@router.post('/skill-proposals/{candidate_id}/publish')
def publish_candidate(candidate_id: str, body: PublishCandidate, user: UserContext = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..pi_skill_drafts import publish
    return publish(db,user,candidate_id,body.sha256)
