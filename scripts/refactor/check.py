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
    if suite == "safety": return [[sys.executable,"-B","-m","unittest","discover","-s","scripts/refactor/tests","-v"]]
    if suite == "native-artifacts": return [[sys.executable,"-B","-m","pytest","backend/tests/test_refactor_native_artifacts.py","--basetemp",str(temp/"native-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "ar-source-synthetic":
        base="sources/finance-skills/skills/ar-hexiao-daily/tests/"
        return [[sys.executable,"-B","-m","pytest",base+"test_yucun_so_and_flow_flag.py",base+"test_plan_apply.py::test_validate_by_year_keeps_same_row_number_isolated",base+"test_plan_apply.py::test_apply_all_writes_two_annual_ledgers_and_builds_combined_reports","--basetemp",str(temp/"source-pytest"),"-p","no:cacheprovider","-q"]]
    if suite == "ar-synthetic": return [[sys.executable,"-B","-m","unittest","discover","-s","skills/ar-hexiao-daily/vendor/scripts","-p",name,"-v"] for name in ["test_flow_monthly.py", "test_flow_order_only.py"]]
    if suite == "linux-ipc": return [[sys.executable,"-B","-m","unittest","discover","-s","scripts/refactor/tests","-p","test_linux_ipc.py","-v"]]
    if suite == "backend-unit": return [[sys.executable,"-B","-m","pytest","-c","backend/pyproject.toml","backend/tests","tests","--basetemp",str(temp/"pytest"),"-p","no:cacheprovider"]]
    if suite == "backend-format": return [[sys.executable,"-m","ruff","format","--check","backend","--config","backend/pyproject.toml"]]
    if suite == "backend-static": return [[sys.executable,"-m","ruff","check","backend","--config","backend/pyproject.toml"]]
    if suite == "contracts": return [[sys.executable,"-B","scripts/export_openapi.py","--check"]]
    if suite == "frontend": return [["pnpm","--dir","web",s] for s in ["typecheck","lint","test:navigation","test:run-access","test:platform-data","test:agent-wire","test:hydration","contracts:check","build"]]
    if suite == "postgres-integration":
        return [[sys.executable,"-B","-m","unittest","discover","-s","backend/tests","-p","test_file_retention_guard.py","-v"]]
    raise ValueError("UNKNOWN_SUITE")

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--suite",required=True,choices=["native-artifacts","ar-source-synthetic","ar-synthetic","backend-format","linux-ipc","safety","backend-unit","backend-static","frontend","contracts","postgres-integration","all"]);parser.add_argument("--timeout",type=int,default=600);parser.add_argument("--continue-on-collection-errors", action="store_true", help="Collect remaining baseline evidence; collection errors still fail the suite");args=parser.parse_args()
    # No dotenv or production environment inheritance; no project import here.
    with tempfile.TemporaryDirectory(prefix="financial-refactor-") as temporary:
        temp=Path(temporary);(temp/".refactor-isolated").write_text("synthetic-only-v1")
        env={k:v for k,v in os.environ.items() if not k.startswith(("FINANCIAL_","AGENT_","PI_")) and k not in {"DATABASE_URL","OPENAI_API_KEY","ANTHROPIC_API_KEY"}}
        env.update(REFACTOR_TEST_ROOT=str(temp),FINANCIAL_ENV="test",FINANCIAL_PROJECT_ROOT=str(ROOT),FINANCIAL_DATA_DIR=str(temp/"data"),FINANCIAL_SKILL_DIR=str(ROOT/"skills"),FINANCIAL_DATABASE_URL="sqlite:///"+str(temp/"test.db"),FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED="false",FINANCIAL_TASK_DISCOVERY_ENABLED="false",REFACTOR_REAL_CONNECTORS="disabled",FINANCIAL_BOOTSTRAP_ADMIN_PASSWORD="synthetic-test-only",PYTHONPATH=str(ROOT/"backend"),PYTHONDONTWRITEBYTECODE="1",TMPDIR=str(temp),NEXT_TELEMETRY_DISABLED="1",AR_HEXIAO_TEST_DATA=str(temp/"synthetic-source-data"))
        verify(env)
        results=[]
        for suite in (["safety","linux-ipc","ar-synthetic","ar-source-synthetic","native-artifacts","backend-format","backend-static","backend-unit","contracts","postgres-integration","frontend"] if args.suite=="all" else [args.suite]):
            try:
                suite_env = dict(env)
                if suite == "postgres-integration":
                    suite_env["FINANCIAL_DATABASE_URL"] = os.environ.get("REFACTOR_POSTGRES_URL", "")
                    suite_env["FILE_RETENTION_ISOLATED_TEST"] = "1"
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
