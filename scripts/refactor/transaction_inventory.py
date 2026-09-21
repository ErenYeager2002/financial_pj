"""Reproducible direct transaction/event call inventory; never imports application code."""
from __future__ import annotations
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def classify(path, scope, kind, expression):
    if "/tests/" in path or Path(path).name.startswith("test_"):
        return "test", "synthetic test code; not a production commit owner"
    if path.startswith("backend/app/infrastructure/database/"):
        return "migration", "explicit schema/lock lifecycle, outside business transaction classes"
    if kind != "commit":
        return "event-interface", "append is caller-owned; legacy wrapper defaults to commit"
    if path == "backend/app/ar_staging_retention.py" and scope.endswith("heartbeat"):
        return "stage-checkpoint", "staging-maintenance heartbeat reuses caller Session; not an independent heartbeat transaction"
    if path == "backend/app/leases.py" or scope == "heartbeat_pi_harness_work":
        return "independent-heartbeat", "heartbeat entry point; verify session isolation separately"
    if scope in {"claim_next_run", "claim_next_workflow_action", "claim_pi_harness_work", "lock_execution", "lock_investigation", "_claim_rollout", "run_discovery_tick"}:
        return "worker-claim", "claim/scheduler transaction owner"
    if path == "backend/app/main.py" or path.startswith("backend/app/routers/"):
        return "api-use-case", "HTTP handler or nested response iterator owns commit"
    if scope in {"_execute_claimed_run", "publish_run_progress", "_persist_model_trace", "execute_phase", "complete_reconciliation", "execute_workflow_action", "_execute_named_workflow_phase", "persist_workspace_state", "execute_task_discovery", "execute_investigation", "_finalize_batch_reports", "_execute_rollout", "_set_failed_disabled", "_finish_interrupted_rollout", "_handle_rollout_failure"}:
        return "stage-checkpoint", "explicit execution/fact checkpoint; see transaction-boundaries for reviewed subset"
    if path.startswith("backend/app/"):
        return "helper-implicit-commit", "service/helper commits internally; caller composition requires semantic review"
    if path.startswith(("skills/", "sources/", "standalone-skills/")):
        return "business-skill-persistence", "separate Skill persistence API; not rewritten by platform PR-02"
    return "operator-or-tooling", "non-runtime operator/tooling commit; not an API transaction"


def inventory(root=ROOT):
    paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root).decode().split("\0")
    rows, failures, hashes = [], [], {}
    for name in sorted(set(paths)):
        path = root / name
        if not name.endswith(".py") or not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            tree = ast.parse(raw.decode("utf-8-sig"))
        except (SyntaxError, UnicodeError) as error:
            failures.append({"path": name, "error": type(error).__name__})
            continue
        hashes[name] = hashlib.sha256(raw).hexdigest()
        class Visitor(ast.NodeVisitor):
            def __init__(self):
                self.scope = []
            def visit_FunctionDef(self, node):
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()
            visit_AsyncFunctionDef = visit_FunctionDef
            def visit_Call(self, node):
                function = node.func
                kind = function.attr if isinstance(function, ast.Attribute) else function.id if isinstance(function, ast.Name) else ""
                if kind in {"commit", "emit_event", "append_run_event", "publish_run_progress"}:
                    scope = ".".join(self.scope) or "<module>"
                    category, basis = classify(name, scope, kind, ast.unparse(function))
                    rows.append({"path": name, "line": node.lineno, "function": scope, "call": ast.unparse(function), "kind": kind, "category": category, "classification_basis": basis, "commit_argument": next((ast.unparse(k.value) for k in node.keywords if k.arg == "commit"), None)})
                self.generic_visit(node)
        Visitor().visit(tree)
    return {"schema_version": "transaction-inventory-v2", "scope": "All git-listed Python source including untracked files. Direct AST calls only; aliases, dynamic dispatch, SQL COMMIT strings and non-Python code are not resolved. Categories describe lexical owners, not proof that every caller has safe transaction composition.", "source_hashes": hashes, "parse_errors": failures, "counts": dict(Counter(row["kind"] for row in rows)), "categories": dict(Counter(row["category"] for row in rows)), "calls": rows}


def main():
    report = inventory()
    target = ROOT / "docs/refactor/reports/PR-02-transaction-call-inventory.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("counts", "categories", "parse_errors")}, ensure_ascii=False))
    return 1 if report["parse_errors"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
