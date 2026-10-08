from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def test_lease_loss_notifies_process_owner(monkeypatch):
    from app import leases

    called = []
    heartbeat = leases.LeaseHeartbeat(
        "workflow_action",
        "action-id",
        "worker-id",
        attempt=1,
        on_lease_lost=lambda: called.append(True),
    )
    monkeypatch.setattr(heartbeat, "_touch", lambda: False)
    monkeypatch.setattr(heartbeat._stop, "wait", lambda _seconds: False)

    heartbeat._loop()

    assert heartbeat.lease_lost is True
    assert called == [True]


def test_process_group_termination_waits_for_exit():
    from app.ar_process_evidence import _terminate_process_group

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    _terminate_process_group(process)
    assert process.poll() is not None


def test_scheduler_exit_gate_requires_exited_fact(monkeypatch, tmp_path: Path):
    from app import ar_process_inspection

    owner = "owner"
    workflow_id = "workflow"
    action_id = "action"
    root = tmp_path / owner / workflow_id
    journal = root / "execution-processes" / action_id / ("a" * 32)
    journal.mkdir(parents=True)
    monkeypatch.setattr(
        ar_process_inspection,
        "workflow_root",
        lambda _owner, _workflow: root,
    )
    workflow = SimpleNamespace(owner_id=owner, id=workflow_id)
    action = SimpleNamespace(id=action_id)

    assert ar_process_inspection.action_process_exit_confirmed(workflow, action) is False
    (journal / "started.json").write_text("{}", encoding="utf-8")
    (journal / "exited.json").write_text(
        json.dumps({"direct_process_exit_confirmed": True}), encoding="utf-8"
    )
    assert ar_process_inspection.action_process_exit_confirmed(workflow, action) is True
