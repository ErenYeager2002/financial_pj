"""Private Pi gateway. Separate credentials protect model and read-only business routes."""
from __future__ import annotations
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from .database import SessionLocal
from .pi_model_access import authenticate, resolve_model
from .agent_model_gateway import (
    AgentModelStreamStats, open_agent_model_stream,
    iter_agent_model_stream, save_agent_model_trace,
)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def build_pi_payload(model, incoming):
    # Preserve native Pi sampling/thinking semantics. The legacy assistant's
    # default thinking-disabled settings do not apply to this runtime.
    allowed = {'messages', 'tools', 'tool_choice', 'temperature', 'top_p',
               'max_tokens', 'max_completion_tokens', 'reasoning_effort',
               'parallel_tool_calls', 'response_format', 'stream_options',
               'thinking', 'reasoning', 'enable_thinking', 'verbosity',
               'frequency_penalty', 'presence_penalty', 'stop', 'seed'}
    payload = {key: incoming[key] for key in allowed if key in incoming}
    payload.update(model=model, stream=True)
    return payload


def normalize_reasoning(message):
    value = dict(message)
    if 'reasoning' in value:
        value.setdefault('reasoning_content', value.pop('reasoning'))
    return value


def normalize_go_stream(chunks):
    # Preserve the upstream Pi opencode-go compatibility rule even though the
    # user-facing provider has a distinct platform name.
    buffer = b''
    for chunk in chunks:
        buffer += chunk
        if len(buffer) > 16 * 1024 * 1024:
            raise ValueError('Model SSE record too large')
        while b'\n' in buffer:
            line, buffer = buffer.split(b'\n', 1)
            if line.startswith(b'data:') and line[5:].strip() != b'[DONE]':
                try:
                    value = json.loads(line[5:])
                    for choice in value.get('choices', []):
                        for name in ('delta', 'message'):
                            if isinstance(choice.get(name), dict):
                                choice[name] = normalize_reasoning(choice[name])
                    line = b'data: ' + json.dumps(value, ensure_ascii=False).encode()
                except (ValueError, TypeError, AttributeError):
                    pass
            yield line + b'\n'
    if buffer:
        yield buffer


def prepare(authorization, incoming):
    with SessionLocal() as db:
        user = authenticate(db, authorization)
        alias = incoming.get('model')
        if not isinstance(alias, str):
            raise HTTPException(422, 'Model is required')
        config = resolve_model(db, user, alias)
        if incoming.get('stream') is not True:
            raise HTTPException(422, 'Streaming model request required')
        payload = build_pi_payload(config.model, incoming)
        if config.provider == 'opencode_go' and isinstance(payload.get('messages'), list):
            payload['messages'] = [normalize_reasoning(item) if isinstance(item, dict) else item
                                   for item in payload['messages']]

    context = open_agent_model_stream(config, payload)
    try:
        upstream = context.__enter__()
    except Exception:
        raise HTTPException(502, 'Platform model connection failed') from None
    if upstream.status_code != 200:
        status = upstream.status_code
        context.__exit__(None, None, None)
        raise HTTPException(429 if status == 429 else 502, 'Platform model rejected request')
    return user, config, context, upstream


@app.post('/v1/chat/completions')
async def completions(request: Request):
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 8 * 1024 * 1024:
            raise HTTPException(413, 'Model request too large')
    try:
        body = json.loads(chunks)
    except ValueError:
        raise HTTPException(422, 'Invalid JSON request') from None
    if not isinstance(body, dict):
        raise HTTPException(422, 'Expected object')
    user, config, context, upstream = await run_in_threadpool(
        prepare, request.headers.get('authorization', ''), body)
    stats = AgentModelStreamStats()

    def stream():
        try:
            chunks = iter_agent_model_stream(upstream, stats)
            yield from normalize_go_stream(chunks) if config.provider == 'opencode_go' else chunks
        finally:
            context.__exit__(None, None, None)
            with SessionLocal() as db:
                save_agent_model_trace(db, user, config, stats)
                db.commit()
    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

from .pi_business_query import router as business_router
app.include_router(business_router)
