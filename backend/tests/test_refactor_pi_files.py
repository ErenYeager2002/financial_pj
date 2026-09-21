"""Synthetic Pi file transport baseline; no model, Docker daemon, or live DB."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import socketserver
import sys
import threading
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.auth import UserContext, get_current_user
from app.database import get_db
from app import pi_runtime_service as runtime
from app.routers import pi_runtime as routes
from app.settings import settings
from test_refactor_event_transactions import database
from sqlalchemy.orm import Session
from app.auth_models import User

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deployment"))
from pi_runtime_manager import RuntimeManager, RuntimeErrorWithStatus


@pytest.fixture
def transport(tmp_path, monkeypatch, database):
    from app import database as database_module
    monkeypatch.setattr(database_module, "SessionLocal", lambda: Session(database))
    with Session(database) as db:
        db.get(User, "synthetic-owner").department_id = "synthetic"
        db.commit()
    assert os.geteuid() == 0, "Pi host-manager baseline requires root inside the isolated test container"
    # Production environment/settings isolation is established by check.py before imports.
    root = settings.data_dir / "pi-runtime"
    root.mkdir(parents=True, exist_ok=True)
    manager = RuntimeManager(tmp_path / "runtime", tmp_path / "control", "synthetic-unused")
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["operation"] == "files", "Fixture forbids runtime/model operations"
            calls.append(body)
            try:
                value, status = manager.dispatch(body), 200
            except RuntimeErrorWithStatus as error:
                value, status = {"error": "synthetic file request rejected"}, error.status
            encoded = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
    socket = root / "manager.sock"
    assert not socket.exists()
    server = socketserver.UnixStreamServer(str(socket), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        actor = UserContext(user_id="synthetic-owner", display_name="Synthetic", role="finance_user", department_id="synthetic")
        session = runtime.create_session(actor, "Synthetic files")
        other = runtime.create_session(actor, "Independent session")
        foreign = UserContext(user_id="synthetic-other", display_name="Other", role="finance_user", department_id="synthetic")
        yield manager, calls, actor, session["id"], other["id"], foreign
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        socket.unlink(missing_ok=True)


def test_pi_upload_generated_download_and_owner_session_isolation(transport, monkeypatch):
    manager, calls, actor, session, other, foreign = transport
    payload = b"synthetic input " * 80000  # More than one transfer chunk.
    def operate(action, **data):
        return runtime.operate(actor, session, "files", {"action": action, **data})
    started = operate("upload_begin", name="input.txt", size=len(payload))
    upload_id = started["upload_id"]
    for offset in range(0, len(payload), 1024 * 1024):
        chunk = payload[offset:offset + 1024 * 1024]
        response = operate("upload_chunk", upload_id=upload_id, offset=offset, data=base64.b64encode(chunk).decode())
        assert response["next"] == offset + len(chunk)
    uploaded = operate("upload_commit", upload_id=upload_id)
    assert uploaded["sha256"] == hashlib.sha256(payload).hexdigest()
    session_root = manager.root / "owners" / runtime.owner_scope(actor) / "sessions" / session
    assert (session_root / "inputs" / uploaded["path"]).read_bytes() == payload
    # Synthetic producer substitutes only model execution. Transfer and stream use real code.
    workspace = session_root / "workspace"
    workspace.mkdir()
    generated = payload + b"generated-result"
    (workspace / "result.txt").write_bytes(generated)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(commit=lambda: None)
    audits = []
    monkeypatch.setattr(routes, "record_audit", lambda *args, **kwargs: audits.append(kwargs))
    with TestClient(app) as client:
        response = client.get(f"/api/pi-runtime/sessions/{session}/download", params={"path": "result.txt"})
        assert response.status_code == 200
        assert response.content == generated
        assert int(response.headers["content-length"]) == len(generated)
        assert response.headers["cache-control"] == "no-store"
    assert audits[0]["action"] == "pi.file.download"
    assert any(c["payload"].get("offset", 0) > 0 and c["payload"].get("version") for c in calls)
    before = len(calls)
    with pytest.raises(HTTPException) as rejected:
        runtime.operate(foreign, session, "files", {"action": "read", "path": "result.txt"})
    assert rejected.value.status_code == 404
    assert len(calls) == before  # Reject before dispatch to host manager.
    with pytest.raises(HTTPException) as rejected:
        runtime.operate(actor, other, "files", {"action": "read", "path": "result.txt"})
    assert rejected.value.status_code == 404


def test_pi_changed_file_and_path_escape_are_rejected(transport):
    manager, calls, actor, session, other, foreign = transport
    session_root = manager.root / "owners" / runtime.owner_scope(actor) / "sessions" / session
    workspace = session_root / "workspace"
    workspace.mkdir(parents=True)
    target = workspace / "result.txt"
    target.write_bytes(b"a" * (1024 * 1024 + 7))
    first = runtime.operate(actor, session, "files", {"action": "read", "path": "result.txt"})
    target.write_bytes(b"changed")
    with pytest.raises(HTTPException) as rejected:
        runtime.operate(actor, session, "files", {"action": "read", "path": "result.txt", "offset": first["next"], "version": first["version"]})
    assert rejected.value.status_code == 422
    outside = session_root / "private.txt"
    outside.write_text("synthetic private")
    (workspace / "escape.txt").symlink_to(outside)
    for path in ["../private.txt", "escape.txt"]:
        with pytest.raises(HTTPException) as rejected:
            runtime.operate(actor, session, "files", {"action": "read", "path": path})
        assert rejected.value.status_code == 422
