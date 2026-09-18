"""Persisted turn ownership and recovery. Never automatically replay a command."""
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from .models import AssistantTurn, AssistantMessage, RunRecord
from .authorization import refresh_active_user
from .auth_models import User

class TurnMutation(BaseModel):
    action: str = Field(pattern="^(begin|touch|finish|stop)$")
    turn_id: str = Field(default="",max_length=36)
    text: str = Field(default="",max_length=20000)
    error: str = Field(default="",max_length=2000)
    data: dict = Field(default_factory=dict)

def _key(user,session):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",session):raise HTTPException(422,"会话标识无效。")
    return (user.user_id,user.department_id,session)
def _utc(value):return value.replace(tzinfo=UTC) if value.tzinfo is None else value

def _message(db,row,text,data):
    message=db.get(AssistantMessage,row.turn_id)
    if message is None:
        message=AssistantMessage(id=row.turn_id,session_id=row.session_id,owner_id=row.owner_id,department_id=row.department_id,role="assistant",content=text)
        db.add(message)
    message.content=text
    message.data_json=json.dumps(data,ensure_ascii=False)

def _expire(db,row):
    if row and row.state=="running" and _utc(row.lease_expires_at)<=datetime.now(UTC):
        row.state="interrupted"
        row.error="会话执行连接已中断；已完成的命令和产物保留，请核对结果后继续，未自动重跑。"
        _message(db,row,(row.partial_text+"\n\n"+row.error).strip(),{**json.loads(row.data_json),"turn_state":"interrupted"})

def _state(row):
    return {"id":row.turn_id if row else "","active":bool(row and row.state=="running"),"stopped":bool(row and row.stopped),"state":row.state if row else "unknown","error":row.error if row else "","partial_text":row.partial_text if row else ""}

def turn_status(db,user,session):
    key=_key(user,session)
    row=db.scalar(select(AssistantTurn).where(AssistantTurn.owner_id==key[0],AssistantTurn.department_id==key[1],AssistantTurn.session_id==key[2]).with_for_update())
    _expire(db,row);db.commit();return _state(row)

def mutate_turn(db,user,session,body):
    user=refresh_active_user(db,user);key=_key(user,session)
    # Existing platform-user row serializes first insertion as well as updates.
    db.scalar(select(User.id).where(User.id==user.user_id).with_for_update())
    row=db.scalar(select(AssistantTurn).where(AssistantTurn.owner_id==key[0],AssistantTurn.department_id==key[1],AssistantTurn.session_id==key[2]).with_for_update())
    _expire(db,row)
    now=datetime.now(UTC)
    if body.action=="begin":
        if row and row.state=="running":raise HTTPException(409,"当前会话仍在执行，请等待或停止。")
        if row is None:
            row=AssistantTurn(owner_id=key[0],department_id=key[1],session_id=key[2]);db.add(row)
        row.turn_id=str(uuid4());row.state="running";row.stopped=False;row.error="";row.partial_text="";row.data_json="{}";row.lease_expires_at=now+timedelta(seconds=90)
    elif body.action=="stop":
        if row is None:
            db.commit();return _state(None)
        if row and row.state=="running":
            row.stopped=True
            row.error="已请求停止生成；正在执行的命令可能仍在结束，请核对任务记录。"
    else:
        if not row or row.turn_id!=body.turn_id or row.state!="running":raise HTTPException(409,"执行租约已结束，旧会话不能继续提交。")
        data={}
        ids=body.data.get("native_run_ids",[])
        if isinstance(ids,list):
            data["native_run_ids"]=list(db.scalars(select(RunRecord.id).where(RunRecord.id.in_(ids[:1000]),RunRecord.owner_id==user.user_id,RunRecord.department_id==user.department_id)))
        if isinstance(body.data.get("draft_id"),str):data["draft_id"]=body.data["draft_id"][:36]
        row.partial_text=body.text;row.data_json=json.dumps(data)
        if body.action=="finish":
            failed_run=db.scalar(select(RunRecord.id).where(RunRecord.id.in_(data.get("native_run_ids",[])),RunRecord.state!="succeeded").limit(1))
            row.error=body.error or ("本轮包含未成功的命令，请核对执行记录，不能认定任务全部完成。" if failed_run else "")
            row.state="cancelled" if row.stopped else "failed" if row.error else "completed"
            final_text=body.text or row.error or "回复已结束，请查看执行记录。"
            if row.error and row.error not in final_text:final_text+="\n\n"+row.error
            row.partial_text=final_text
            _message(db,row,final_text,{**data,"turn_state":row.state})
        else:
            row.lease_expires_at=now+timedelta(seconds=90)
            if body.text:_message(db,row,body.text,{**data,"turn_state":"running"})
    row.updated_at=now;db.commit();return _state(row)

def require_turn_command(db,user,session,turn_id):
    row=db.get(AssistantTurn,_key(user,session),populate_existing=True)
    if not turn_id:
        if row:raise HTTPException(409,"已有对话的命令必须携带有效执行标识。")
        return
    if not row or row.turn_id!=turn_id or row.state!="running" or row.stopped or _utc(row.lease_expires_at)<=datetime.now(UTC):
        raise HTTPException(409,"会话已停止或执行租约失效，未开始新命令。")
