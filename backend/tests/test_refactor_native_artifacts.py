"""Service/UDS/archive baseline with a synthetic executor, not sandbox certification."""
import hashlib
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import socketserver
import subprocess
import sys
import threading
from types import SimpleNamespace
from uuid import uuid4

from app.auth import UserContext
from app.auth_service import create_user
from app.database import init_db, SessionLocal
from app.models import FileRecord, RunRecord
from app import native_skill_service as native
from app.contracts import NativeSkillRead


def test_native_command_archives_real_generated_file_and_keeps_runs_distinct():
    init_db()
    name='synthetic-'+uuid4().hex[:12]
    session='skill-native--'+name+'__test'
    root=native.native_root();root.mkdir(parents=True,exist_ok=True)
    commit='a'*40
    package=root/'packages'/name/commit;package.mkdir(parents=True)
    (package/'SKILL.md').write_text('---\nname: Synthetic\ndescription: Fabricated file test\n---\nCreate a synthetic file.\n')
    index=root/'installed';index.mkdir(exist_ok=True)
    skill=NativeSkillRead(id=name,name='Synthetic',description='Synthetic only',commit=commit,source_path='synthetic',installed_at='2026-09-18T00:00:00Z')
    (index/(name+'.json')).write_text(skill.model_dump_json())
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body['command']=='generate synthetic artifact'
            workspace=(root/body['workspace']).resolve()
            assert workspace.is_relative_to(root.resolve())
            calls.append(body)
            # The command producer is a fixture. HTTP transport, service state,
            # ownership and archive registration use the actual implementation.
            text=f'synthetic-command-{len(calls)}'
            subprocess.run([sys.executable,'-B','-c',"from pathlib import Path; import sys; Path('outputs/result.txt').write_text(sys.argv[1])",text],cwd=workspace,check=True,timeout=5)
            raw=json.dumps({'exit_code':0,'output':'synthetic completed'}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    socket=root/'executor.sock'
    assert not socket.exists(), 'Isolated test must not replace an existing executor'
    server=socketserver.UnixStreamServer(str(socket),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with SessionLocal() as db:
            user=create_user(db,username=name,password='synthetic-test-only',role='skill_admin')
            db.commit()
            actor=UserContext(user_id=user.id,display_name=user.display_name,role=user.role,department_id=user.department_id)
            body=SimpleNamespace(session_id=session,turn_id='',file_ids=[],command='generate synthetic artifact')
            first=native.execute_command(db,actor,name,body)
            second=native.execute_command(db,actor,name,body)
            assert first['run']['id']!=second['run']['id']
            assert len(calls)==2
            for number,result in enumerate((first,second),1):
                assert result['run']['state']=='succeeded'
                assert len(result['artifacts'])==1
                artifact=result['artifacts'][0]
                record=db.get(FileRecord,artifact['id'])
                expected=f'synthetic-command-{number}'.encode()
                assert record.owner_id==actor.user_id
                assert Path(record.stored_path).read_bytes()==expected
                assert artifact['sha256']==hashlib.sha256(expected).hexdigest()
                assert artifact['url'].endswith('/'+record.id+'/download')
                assert db.get(RunRecord,result['run']['id']).result_json
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close();socket.unlink(missing_ok=True)
