"""Release lab FX accrual and its declared BOC proxy access, preserving other services."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import yaml
import ar_current_balance_readonly_release as base
from ar_current_workbook_lab_release import ToolDeployment
from maintenance_flow import DeploymentFailure

BACKEND_NAME="ar_process_evidence.py"
PREVIOUS_BACKEND_SHA="33bcc5b08b41452c18a2a557795b8d73ff8aa5b8878821f567c8bdc243734a94"
BOC="https://www.boc.cn:443"
SOURCE=Path(__file__).resolve().parents[1]
backend_source=SOURCE/"backend/app"/BACKEND_NAME
backend_sha=hashlib.sha256(backend_source.read_bytes()).hexdigest()
original_atomic=base.atomic_text
original_run=base.run
build_root=None
candidate_image=None
adapter_instance=None


def publish_text(path,content):
    global build_root
    if path.name=="Dockerfile":
        build_root=path.parent
        for service in base.PLAN.services:
            actual=original_run(["docker","exec",base.PROJECT+"-"+service+"-1","sha256sum","/app/backend/app/"+BACKEND_NAME]).split()[0]
            if actual!=PREVIOUS_BACKEND_SHA:
                raise DeploymentFailure("AR process environment baseline changed; preserve concurrent release")
        backend=build_root/"backend";backend.mkdir()
        shutil.copy2(backend_source,backend/BACKEND_NAME)
        shutil.copy2(SOURCE/"backend/tests/test_ar_fx_network.py",backend/"test_ar_fx_network.py")
        content+="COPY --chown=10001:10001 backend/"+BACKEND_NAME+" /app/backend/app/"+BACKEND_NAME+"\n"
    elif path.name==".dockerignore":
        content+="!backend/\n!backend/**\n"
    elif path==base.ROOT/"compose.yaml" and adapter_instance:
        data=yaml.safe_load(content)
        if data["services"]["api"]["image"]!=adapter_instance.original_api_image:
            targets=data["services"]["egress-proxy"]["environment"]["FINANCIAL_EGRESS_PROXY_TARGETS"].split(",")
            if BOC not in targets:
                pattern=r"(?m)^(      FINANCIAL_EGRESS_PROXY_TARGETS: )([^\n]+)$"
                content,count=re.subn(pattern,lambda m:m.group(1)+m.group(2)+","+BOC,content,count=1)
                if count!=1:raise DeploymentFailure("Proxy target configuration not unique")
    return original_atomic(path,content)


def release_run(args,**kwargs):
    global candidate_image
    result=original_run(args,**kwargs)
    if args[:3]==["docker","image","inspect"] and "ar-current-balance-" in args[-1]:
        candidate_image=result
    return result


class FxToolDeployment(ToolDeployment):
    def manifest(self,data):
        value=super().manifest(data)
        # This entry explicitly evaluates and deploys the one approved runtime
        # contract delta. All other manifest changes keep the base hard guard.
        runtime=value.get("runtime") or {}
        runtime["network_targets"]=[target for target in runtime.get("network_targets") or []
                                    if target not in {"https://www.boc.cn",BOC}]
        return value


class FxAdapter(base.Adapter):
    def __init__(self):
        global adapter_instance
        super().__init__();adapter_instance=self
        current=self.inspect()
        self.original_api_image=current["/"+base.PROJECT+"-api-1"]["Image"]
        self.original_proxy_image=current["/"+base.PROJECT+"-egress-proxy-1"]["Image"]

    def backup(self):
        if not candidate_image or not build_root:raise DeploymentFailure("Candidate FX image missing")
        original_run(["docker","run","--rm","--network","none","--read-only","--tmpfs","/tmp",
            "-e","PYTHONDONTWRITEBYTECODE=1","-w","/app/skills/ar-hexiao-daily-lab/vendor/scripts",
            "--entrypoint","python",candidate_image,"-m","unittest","test_fx_accrual","test_fx_quote_workflow",
            "test_fx_current_receipts","test_fx_plan_validation","test_boc_fx_quotes","-q"])
        original_run(["docker","run","--rm","--network","none","--read-only","--tmpfs","/tmp",
            "-e","PYTHONDONTWRITEBYTECODE=1","-e","PYTHONPATH=/check:/app/backend",
            "-v",str(build_root/"backend")+":/check:ro","-w","/app/backend","--entrypoint","python",candidate_image,
            "-m","unittest","test_ar_fx_network","-q"])
        print(json.dumps({"fx_candidate_tests":"passed","backend_network_tests":"passed"}),flush=True)
        return super().backup()

    def cutover(self,plan,_expected):
        super().cutover(plan,_expected)
        name="/"+base.PROJECT+"-egress-proxy-1"
        current=self.inspect()[name]
        desired=yaml.safe_load((base.ROOT/"compose.yaml").read_text())["services"]["egress-proxy"]["environment"]["FINANCIAL_EGRESS_PROXY_TARGETS"]
        actual=next(value.split("=",1)[1] for value in current["Config"]["Env"] if value.startswith("FINANCIAL_EGRESS_PROXY_TARGETS="))
        if desired!=actual:
            # Tool and workers are drained before this stage; proxy changes
            # only this project's declared origin and keeps its original image.
            self.command(self.compose()+["up","-d","--no-deps","--force-recreate","egress-proxy"])
            current=self.inspect()[name]
        if current["Image"]!=self.original_proxy_image:
            raise DeploymentFailure("Proxy image changed unexpectedly")
        self.protected[name]=(current["Id"],current["State"]["StartedAt"])

    def wait_healthy(self,plan):
        result=super().wait_healthy(plan)
        current=self.inspect()
        if current["/"+base.PROJECT+"-api-1"]["Image"]==self.original_api_image:return result
        for service in base.PLAN.services:
            actual=original_run(["docker","exec",base.PROJECT+"-"+service+"-1","sha256sum","/app/backend/app/"+BACKEND_NAME]).split()[0]
            if actual!=backend_sha:raise DeploymentFailure("Live FX network module hash mismatch")
        # Read-only public page fetch through the exact controlled child env.
        code="""import sys,os,json,urllib.request,yaml
from app.registry import RuntimeSpec
from app.network_policy import skill_subprocess_environment
runtime=yaml.safe_load(open('/app/skills/ar-hexiao-daily-lab/tool.yaml'))['runtime']
env=skill_subprocess_environment(RuntimeSpec(**runtime));os.environ.clear();os.environ.update(env)
sys.path.insert(0,'/app/skills/ar-hexiao-daily-lab/vendor/scripts')
import boc_fx_quotes as Q
with urllib.request.urlopen(Q.OFFICIAL_URL,timeout=10) as response:
    html=response.read(1048576).decode('utf-8')
quotes=Q.parse_boc_html(html)
assert any(q.currency=='USD' for q in quotes)
print(json.dumps({'worker_controlled_boc_read':'passed','quotes':len(quotes)}))
"""
        import subprocess
        check=subprocess.run(["docker","exec","-i",base.PROJECT+"-worker-standard-1","python","-"],input=code,
                             text=True,capture_output=True,timeout=30)
        if check.returncode:raise DeploymentFailure("Worker controlled BOC read failed")
        print(check.stdout.strip(),flush=True)
        return result


def release():
    base.SKILLS=("ar-hexiao-daily-lab",)
    base.ToolDeployment=FxToolDeployment
    base.Adapter=FxAdapter
    base.atomic_text=publish_text
    base.run=release_run
    base.release()

if __name__=="__main__":release()
