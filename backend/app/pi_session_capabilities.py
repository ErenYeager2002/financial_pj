"""Authorization projection for an owned Pi session; it never grants execution rights."""
from .authorization import allowed_skill_ids, refresh_active_user
from .pi_runtime_service import _session_record_for_owner
from .pi_operation_contract import RPC_COMMANDS, requires_skill_grant


def session_capabilities(db, user, session_id):
    current = refresh_active_user(db, user)
    session_id, _, record = _session_record_for_owner(current.user_id, current.department_id, session_id)
    names = [record['skill_id']] if record.get('skill_id') else record.get('mounted_skill_ids', [])
    required = {'native--' + name for name in names}
    can_run = current.is_admin or required.issubset(allowed_skill_ids(db, current))
    can_upload = can_run and (current.is_admin or required.issubset(allowed_skill_ids(db, current, 'can_upload')))
    # Read/stop/negative-dialog actions use the same policy as dispatch. A listed
    # extension response without can_approve_input permits only refusal/cancel.
    commands = sorted(command for command in RPC_COMMANDS
                      if can_run or not requires_skill_grant('send', {'command': {'type': command, 'cancelled': True}}))
    return {
        'protocol': 'pi-session-capabilities-v1',
        'session_id': session_id,
        'can_send': can_run,
        'can_configure': can_run,
        'can_start': can_run,
        'can_upload': can_upload,
        'can_approve_input': can_run,
        'rpc_commands': commands,
        'reason': '' if can_run else '此会话的 Skill 权限已变化，可查看记录和停止已有执行，请联系管理员。',
    }
