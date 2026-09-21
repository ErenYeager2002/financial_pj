"""Run existing suites with isolation configured before application imports."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from verify_isolation import verify
from process_control import run_group

ROOT = Path(__file__).resolve().parents[2]

def scrub(text):
    text = re.sub(r"(?i)(authorization[:=]\s*(?:bearer\s+)?)[^\s]+", r"\1<REDACTED>", text)
    text = re.sub(r"(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{20,}", "<REDACTED>", text)
    text = re.sub(r"(postgresql(?:\+psycopg)?://)[^\s]+", r"\1<REDACTED>", text)
    return text

def commands(suite, temp):
    if suite == "retry-policy": return [[sys.executable,"-B","-m","pytest","backend/tests/test_retry_policy.py","--basetemp",str(temp/"retry-policy"),"-p","no:cacheprovider","-q"]]
    if suite == "submission-reservations": return [[sys.executable,"-B","-m","pytest","backend/tests/test_submission_reservations.py","--basetemp",str(temp/"reservations-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "draft-locking": return [[sys.executable,"-B","-m","pytest","backend/tests/test_draft_locking.py","--basetemp",str(temp/"draft-lock-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "draft-submission": return [[sys.executable,"-B","-m","pytest","backend/tests/test_task_drafts.py::test_prepare_draft_does_not_create_run_until_confirmed","backend/tests/test_task_drafts.py::test_draft_submission_failure_rolls_back_and_recovers_frozen_input","backend/tests/test_task_drafts.py::test_confirm_rejects_changed_file_and_cross_user_access","--basetemp",str(temp/"draft-submission-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "ordinary-retry": return [[sys.executable,"-B","-m","pytest","backend/tests/test_workbench_files_runs.py::test_failed_read_only_run_retry_is_bounded_and_audited","--basetemp",str(temp/"retry-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "execution-lifecycle": return [[sys.executable,"-B","-m","pytest","backend/tests/test_parallel_workers.py","backend/tests/test_run_step_runtime.py","--basetemp",str(temp/"execution-lifecycle-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "pi-attempt": return [[sys.executable,"-B","-m","pytest","backend/tests/test_pi_attempt_protocol.py","--basetemp",str(temp/"pi-attempt-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "approval-authorization": return [[sys.executable,"-B","-m","pytest","backend/tests/test_approval_authorization.py","backend/tests/test_ar_published_cancellation.py","backend/tests/test_publication_current_evidence.py","backend/tests/test_formal_ledger_registration.py","backend/tests/test_completion_after_revocation.py","backend/tests/test_ar_execution_boundaries.py::test_v2_action_heartbeat_preserves_queue_isolation","--basetemp",str(temp/"approval-auth-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "execution-authorization": return [[sys.executable,"-B","-m","pytest","backend/tests/test_execution_authorization.py","backend/tests/test_pi_admin_stop.py","backend/tests/test_workflow_admin_stop.py","backend/tests/test_run_execution_snapshot.py","backend/tests/test_workflow_agent_adapter.py","backend/tests/test_snapshot_replay.py::test_snapshot_replay_cannot_queue_live_supplement","backend/tests/test_workflow_action_pipeline.py::test_fetched_data_confirmation_is_idempotent_for_plan_action","backend/tests/test_workflow_action_pipeline.py::test_named_fetch_pipeline_cannot_confirm_without_a_bundle","--basetemp",str(temp/"authorization-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "submission-orchestration": return [[sys.executable,"-B","-m","pytest","backend/tests/test_submission_orchestration.py","--basetemp",str(temp/"submission-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "prepared-payload": return [[sys.executable,"-B","-m","pytest","backend/tests/test_prepared_payload.py","--basetemp",str(temp/"prepared-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "native-identity": return [[sys.executable,"-B","-m","pytest","backend/tests/test_native_identity.py","--basetemp",str(temp/"native-identity-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "submission-snapshot": return [[sys.executable,"-B","-m","pytest","backend/tests/test_submission_snapshot.py","backend/tests/test_refactor_event_transactions.py","--basetemp",str(temp/"snapshot-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "submission-canonical": return [[sys.executable,"-B","-m","pytest","backend/tests/test_submission_canonical.py","--basetemp",str(temp/"canonical-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "task-drafts": return [[sys.executable,"-B","-m","pytest","backend/tests/test_task_drafts.py","--basetemp",str(temp/"drafts-pytest"),"-p","no:cacheprovider","-q"]]
    if suite in {"event-transactions", "transactions-postgres"}: return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_event_transactions.py","--basetemp",str(temp/"events-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "database-lifecycle": return [[sys.executable,"-B","-m","pytest","backend/tests/test_database_migrations.py","backend/tests/test_parallel_workers.py","--basetemp",str(temp/"lifecycle-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "bootstrap-admin": return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_bootstrap_admin.py","--basetemp",str(temp/"bootstrap-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "schema-release": return [[sys.executable,"-B","-m","unittest","discover","-s","deployment","-p","test_schema_release.py","-v"]]
    if suite == "safety": return [[sys.executable,"-B","-m","unittest","discover","-s","scripts/refactor/tests","-v"]]
    if suite == "migrate": return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_migrate.py","backend/tests/test_refactor_legacy_adoption.py","backend/tests/test_refactor_sqlite_runtime_migration.py","backend/tests/test_refactor_migration_cli.py","backend/tests/test_refactor_assistant_turn_migration.py","--basetemp",str(temp/"migrate-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "migration-postgres": return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_migration_postgres.py","--basetemp",str(temp/"migration-pg-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "migration-lock": return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_migration_lock.py","--basetemp",str(temp/"lock-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "schema-check": return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_schema_check.py","backend/tests/test_refactor_runtime_database.py","--basetemp",str(temp/"schema-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "migration-connection": return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_migration_connection.py","--basetemp",str(temp/"migration-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "fetch-bundle-synthetic": return [[sys.executable,"-B","-m","pytest","backend/tests/test_fetched_bundle_service.py::test_materialize_bundle_atomically_publishes_validated_members","backend/tests/test_fetched_bundle_service.py::test_stage_bundle_files_copies_only_the_requested_date_atomically","backend/tests/test_ar_empty_day.py","backend/tests/test_empty_batch_report.py","--basetemp",str(temp/"bundle-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "ordinary-e2e": return [[sys.executable,"-B","-m","pytest","backend/tests/test_platform_e2e.py::test_upload_run_worker_and_download","--basetemp",str(temp/"ordinary-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "pi-files": return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_pi_files.py","--basetemp",str(temp/"pi-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "native-artifacts": return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_native_artifacts.py","--basetemp",str(temp/"native-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "ar-source-synthetic":
        base="sources/finance-skills/skills/ar-hexiao-daily/tests/"
        return [[sys.executable,"-B","-m","pytest",base+"test_yucun_so_and_flow_flag.py",base+"test_plan_apply.py::test_validate_by_year_keeps_same_row_number_isolated",base+"test_plan_apply.py::test_apply_all_writes_two_annual_ledgers_and_builds_combined_reports","--basetemp",str(temp/"source-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "ar-synthetic": return [[sys.executable,"-B","-m","unittest","discover","-s","skills/ar-hexiao-daily/vendor/scripts","-p",name,"-v"] for name in ["test_flow_monthly.py", "test_flow_order_only.py"]]
    if suite == "linux-ipc": return [[sys.executable,"-B","-m","unittest","discover","-s","scripts/refactor/tests","-p","test_linux_ipc.py","-v"]]
    if suite == "backend-unit": return [[sys.executable,"-B","-m","pytest","-c","backend/pyproject.toml","backend/tests","tests","--basetemp",str(temp/"pytest"),"-p","no:cacheprovider"]]
    if suite == "backend-format": return [[sys.executable,"-m","ruff","format","--check","backend","--config","backend/pyproject.toml","--no-cache"]]
    if suite == "backend-static": return [[sys.executable,"-m","ruff","check","backend","--config","backend/pyproject.toml","--no-cache"]]
    if suite == "contracts-export": return [[sys.executable,"-B","scripts/export_openapi.py"]]
    if suite == "contracts": return [[sys.executable,"-B","scripts/export_openapi.py","--check"]]
    if suite == "frontend": return [["pnpm","--dir","web",s] for s in ["typecheck","lint","test:navigation","test:run-access","test:platform-data","test:agent-wire","test:hydration","contracts:check","build"]]
    if suite == "postgres-integration":
        return [[sys.executable,"-B","-m","unittest","discover","-s","backend/tests","-p","test_file_retention_guard.py","-v"]]
    raise ValueError("UNKNOWN_SUITE")

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--suite",required=True,choices=["retry-policy","pi-attempt","approval-authorization","contracts-export","execution-lifecycle","execution-authorization","draft-locking","draft-submission","ordinary-retry","submission-orchestration","prepared-payload","native-identity","submission-snapshot","submission-reservations","submission-canonical","transactions-postgres","task-drafts","event-transactions","schema-release","bootstrap-admin","database-lifecycle","migrate","migration-postgres","migration-lock","schema-check","migration-connection","fetch-bundle-synthetic","ordinary-e2e","pi-files","native-artifacts","ar-source-synthetic","ar-synthetic","backend-format","linux-ipc","safety","backend-unit","backend-static","frontend","contracts","postgres-integration","all"]);parser.add_argument("--timeout",type=int,default=600);parser.add_argument("--continue-on-collection-errors", action="store_true", help="Collect remaining baseline evidence; collection errors still fail the suite");args=parser.parse_args()
    # No dotenv or production environment inheritance; no project import here.
    with tempfile.TemporaryDirectory(prefix="financial-refactor-") as temporary:
        temp=Path(temporary);(temp/".refactor-isolated").write_text("synthetic-only-v1")
        env={k:v for k,v in os.environ.items() if not k.startswith(("FINANCIAL_","AGENT_","PI_")) and k not in {"DATABASE_URL","OPENAI_API_KEY","ANTHROPIC_API_KEY"}}
        env.update(REFACTOR_TEST_ROOT=str(temp),FINANCIAL_ENV="test",FINANCIAL_PROJECT_ROOT=str(ROOT),FINANCIAL_DATA_DIR=str(temp/"data"),FINANCIAL_SKILL_DIR=str(ROOT/"skills"),FINANCIAL_DATABASE_URL="sqlite:///"+str(temp/"test.db"),FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED="false",FINANCIAL_TASK_DISCOVERY_ENABLED="false",REFACTOR_REAL_CONNECTORS="disabled",FINANCIAL_BOOTSTRAP_ADMIN_PASSWORD="synthetic-test-only",PYTHONPATH=str(ROOT/"backend"),PYTHONDONTWRITEBYTECODE="1",TMPDIR=str(temp),NEXT_TELEMETRY_DISABLED="1",AR_HEXIAO_TEST_DATA=str(temp/"synthetic-source-data"))
        verify(env)
        results=[]
        for suite in (["fetch-bundle-synthetic","ordinary-e2e","pi-files","safety","linux-ipc","ar-synthetic","ar-source-synthetic","native-artifacts","backend-format","backend-static","backend-unit","contracts","postgres-integration","frontend"] if args.suite=="all" else [args.suite]):
            try:
                suite_env = dict(env)
                if suite in {"postgres-integration", "migration-postgres", "transactions-postgres"} or (suite in {"ordinary-e2e", "draft-submission", "execution-lifecycle"} and os.environ.get("REFACTOR_POSTGRES_URL")):
                    suite_env["FINANCIAL_DATABASE_URL"] = os.environ.get("REFACTOR_POSTGRES_URL", "")
                    suite_env["FILE_RETENTION_ISOLATED_TEST"] = "1"
                    if suite in {"ordinary-e2e", "draft-submission", "execution-lifecycle"}:
                        suite_env["REFACTOR_HTTP_POSTGRES"] = "1"
                    verify(suite_env)
                selected=commands(suite,temp)
            except ValueError as error:
                results.append({"suite":suite,"status":"not_run","reason":str(error)});continue
            for command in selected:
                if args.continue_on_collection_errors and suite == "backend-unit":
                    command = [*command, "--continue-on-collection-errors"]
                started=time.monotonic()
                try:
                    result=run_group(command,cwd=ROOT,env=suite_env,timeout=args.timeout)
                    results.append({"suite":suite,"command":command,"exit_code":result.returncode,"status":"passed" if result.returncode==0 else "failed","seconds":round(time.monotonic()-started,2),"output":scrub(result.stdout+result.stderr)})
                except (FileNotFoundError,subprocess.TimeoutExpired) as error:
                    results.append({"suite":suite,"command":command,"status":"not_run" if isinstance(error,FileNotFoundError) else "failed","reason":type(error).__name__})
        print(json.dumps({"schema_version":"isolated-check-v1","results":results},ensure_ascii=False))
        return 0 if all(r['status']=='passed' for r in results) else 1
if __name__=="__main__":raise SystemExit(main())
