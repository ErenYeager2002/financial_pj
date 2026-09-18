"""Pending official RPC dialogs; the bridge lock serializes these with stdin."""
import time
import math

DIALOGS = {'confirm', 'select', 'input', 'editor'}

class PendingDialogs:
    def __init__(self):
        self.requests = {}

    def clear(self):
        self.requests.clear()

    def observe(self, event):
        if event.get('type') == 'platform_extension_ui_closed':
            self.complete(event.get('id'))
            return
        if event.get('type') != 'extension_ui_request' or event.get('method') not in DIALOGS:
            return
        request_id = event.get('id')
        if not isinstance(request_id, str):
            return
        value = dict(event)
        timeout = value.get('timeout')
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and math.isfinite(timeout) and timeout > 0:
            value['expires_at'] = time.time() * 1000 + timeout
        self.requests[request_id] = value

    def snapshot(self):
        now = time.time() * 1000
        self.requests = {key: value for key, value in self.requests.items()
                         if value.get('expires_at', float('inf')) > now}
        return list(self.requests.values())

    def validate(self, response):
        self.snapshot()
        request = self.requests.get(response.get('id'))
        if request is None:
            raise ValueError('Dialog no longer pending')
        allowed = {'type', 'id', 'cancelled', 'confirmed', 'value'}
        if set(response) - allowed:
            raise ValueError('Invalid dialog response fields')
        if response.get('cancelled') is True:
            return {'type':'extension_ui_response', 'id':request['id'], 'cancelled':True}
        if request['method'] == 'confirm':
            if not isinstance(response.get('confirmed'), bool):
                raise ValueError('Confirmation requires an explicit boolean')
            return {'type':'extension_ui_response', 'id':request['id'], 'confirmed':response['confirmed']}
        value = response.get('value')
        if not isinstance(value, str):
            raise ValueError('Dialog requires a text value')
        if request['method'] == 'select' and value not in request.get('options', []):
            raise ValueError('Selection is not one of the offered options')
        return {'type':'extension_ui_response', 'id':request['id'], 'value':value}

    def complete(self, request_id):
        self.requests.pop(request_id, None)
