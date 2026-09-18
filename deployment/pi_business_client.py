"""Session-scoped platform query; no provider or business service secrets returned."""
import http.client
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit


def query(body, path='/platform/query'):
    config = json.loads(Path('/control/business.json').read_text())
    proxy = urlsplit(os.environ.get('HTTP_PROXY',''))
    if not proxy.hostname or not proxy.port:
        raise RuntimeError('Platform proxy unavailable')
    connection = http.client.HTTPConnection(proxy.hostname,proxy.port,timeout=45)
    connection.set_tunnel('platform-model.internal',80)
    try:
        payload = {**body,'session_id':config['session_id']}
        connection.request('POST',path,json.dumps(payload),
                           {'Content-Type':'application/json','Authorization':'Bearer '+config['token']})
        response = connection.getresponse()
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data)>2 * 1024 * 1024:
            return {'error':'Platform response too large; narrow the query','status':413}
        value = json.loads(data)
        if response.status != 200:
            return {'error':value.get('detail','Platform query failed'),'status':response.status}
        return value
    finally:
        connection.close()

if __name__ == '__main__':
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:raise ValueError('request too large')
        body=json.loads(raw)
        if not isinstance(body,dict):raise ValueError('invalid request')
        print(json.dumps(query(body),ensure_ascii=False))
    except Exception:
        print(json.dumps({'error':'Platform business connection unavailable'}))
        sys.exit(1)
