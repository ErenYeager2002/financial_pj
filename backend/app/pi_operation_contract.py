"""Public Pi controls supported by the platform; host identity is never a payload field."""
from __future__ import annotations
import base64
import json
from fastapi import HTTPException

READ_COMMANDS = frozenset({'get_state', 'get_messages', 'get_available_models', 'get_commands'})
EMPTY_COMMANDS = READ_COMMANDS | {'abort', 'clear_queue'}
TEXT_COMMANDS = frozenset({'prompt', 'steer', 'follow_up'})
RPC_COMMANDS = EMPTY_COMMANDS | TEXT_COMMANDS | {'set_model', 'set_thinking_level', 'compact', 'extension_ui_response'}

def invalid():
    raise HTTPException(422, 'Pi 操作参数无效或该指令尚未适配。')

def fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        invalid()

def text(value, limit, nonempty=True):
    if not isinstance(value, str) or len(value) > limit or (nonempty and not value.strip()):
        invalid()

def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        invalid()

def validate_command(command):
    if not isinstance(command, dict) or not isinstance(command.get('type'), str) or command.get('type') not in RPC_COMMANDS:
        invalid()
    kind = command['type']
    base = {'type', 'id'}
    if 'id' in command:
        text(command['id'], 256)
    if kind in EMPTY_COMMANDS:
        fields(command, base, {'type'})
    elif kind in TEXT_COMMANDS:
        fields(command, base | {'message'}, {'type', 'message'})
        text(command['message'], 8 * 1024 * 1024)
    elif kind == 'set_model':
        fields(command, base | {'provider', 'modelId'}, {'type', 'provider', 'modelId'})
        text(command['provider'], 256); text(command['modelId'], 1024)
    elif kind == 'set_thinking_level':
        fields(command, base | {'level'}, {'type', 'level'})
        if not isinstance(command['level'], str) or command['level'] not in {'off','minimal','low','medium','high','xhigh','max'}:
            invalid()
    elif kind == 'compact':
        fields(command, base | {'customInstructions'}, {'type'})
        if 'customInstructions' in command:
            text(command['customInstructions'], 65536, False)
    else:
        fields(command, base | {'confirmed','cancelled','value'}, {'type','id'})
        keys = set(command) - base
        if keys == {'cancelled'}:
            if command['cancelled'] is not True: invalid()
        elif keys == {'confirmed'}:
            if type(command['confirmed']) is not bool: invalid()
        elif keys == {'value'}:
            text(command['value'], 1024 * 1024, False)
        else:
            invalid()
        # Matching pending ID, dialog method, allowed options and expiry remain bridge-owned.
    # Same UTF-8 JSON + newline limit as the bridge, before a durable dispatch marker.
    try:
        encoded_size = len(json.dumps(command, ensure_ascii=False).encode('utf-8')) + 1
    except (UnicodeError, TypeError, ValueError):
        invalid()
    if encoded_size > 8 * 1024 * 1024:
        invalid()


def validate_operation(operation, payload):
    if operation == 'files':
        return  # Dedicated file API plus host pi_files owns this separately versioned contract.
    if operation == 'start':
        fields(payload, {'mode'})
        if not isinstance(payload.get('mode', 'terminal'), str) or payload.get('mode', 'terminal') not in {'rpc','terminal'}: invalid()
    elif operation == 'stop':
        fields(payload, set())
    elif operation == 'poll':
        fields(payload, {'after'})
        integer(payload.get('after', 0), 0, 2**53-1)
    elif operation == 'resize':
        fields(payload, {'rows','cols'})
        integer(payload.get('rows',32), 2, 500); integer(payload.get('cols',120), 10, 1000)
    elif operation == 'send':
        if isinstance(payload, dict) and 'command' in payload:
            fields(payload, {'command','client_request_id'}, {'command'})
            validate_command(payload['command'])
            if 'client_request_id' in payload and payload['command']['type'] not in TEXT_COMMANDS:
                invalid()
            # Message request UUID/content identity remains validated by the durable receipt module.
        else:
            fields(payload, {'data'}, {'data'})
            text(payload['data'], 87384, False)
            try:
                if len(base64.b64decode(payload['data'], validate=True)) > 65536: invalid()
            except (ValueError, UnicodeError):
                invalid()
    elif operation == 'jobs':
        if not isinstance(payload, dict): invalid()
        kind = payload.get('operation')
        if not isinstance(kind, str): invalid()
        if kind == 'list': fields(payload, {'operation'})
        elif kind in {'poll','cancel'}:
            fields(payload, {'operation','job_id'} | ({'after','wait_seconds'} if kind == 'poll' else set()), {'operation','job_id'})
            from uuid import UUID
            try:
                if str(UUID(payload['job_id'])) != payload['job_id']: invalid()
            except (ValueError, TypeError, AttributeError): invalid()
            if kind == 'poll':
                integer(payload.get('after',0),0,2**53-1)
                wait = payload.get('wait_seconds',0)
                if type(wait) not in {int,float} or not 0 <= wait <= 10: invalid()
        else: invalid()
    else:
        invalid()


def requires_skill_grant(operation, payload):
    """Revocation stops new work; active owner identity is still required for every call."""
    if operation in {'start', 'stop', 'poll'}:
        return False  # start separately revalidates requested bindings during provisioning.
    if operation == 'jobs' and payload.get('operation') in {'list', 'poll', 'cancel'}:
        return False
    if operation == 'send':
        command = payload.get('command') or {}
        kind = command.get('type')
        if kind in {'get_state', 'get_messages', 'abort', 'clear_queue'}:
            return False
        if kind == 'extension_ui_response' and (command.get('cancelled') is True or command.get('confirmed') is False):
            return False
    return True
