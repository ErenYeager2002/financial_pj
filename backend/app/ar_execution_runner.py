"""Post-fetch AR orchestration, pinned to a task-owned execution contract.

Financial decisions stay in the pinned Skill scripts. This adapter owns phase
preconditions and checkpoints; it never turns a model explanation into a write.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import select
from fastapi import HTTPException

from .ar_execution_contract import CONTRACT_VERSION, PHASES, TOOL_PHASE, GUARDED_TOOLS, ExecutionCancelled, ExecutionLeaseLost, next_phase, require_phase
from .ar_execution_service import read_evidence_page, require_evidence_coverage
from .models import WorkflowAction, WorkflowSession
from .resource_policy import workflow_root
from .ar_annual_materials import fixed_annual_ledgers, annual_ledgers_in_copy


def lock_execution(db: Session, action: WorkflowAction, workflow: WorkflowSession) -> None:
    """Fence an action under the same lock used by claims and cancellation.

    The caller must not have pending writes: publication and completion both
    remain in this transaction until the outer Worker commits the whole outcome.
    """
    from .scheduler import acquire_claim_lock

    expected_worker = getattr(action, "_ar_claim_worker_id", action.worker_id)
    db.commit()
    acquire_claim_lock(db)
    db.refresh(action)
    db.refresh(workflow)
    deadline = action.lease_expires_at
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if (
        action.state != "running" or not expected_worker
        or action.worker_id != expected_worker or deadline is None
        or deadline <= datetime.now(UTC)
        or workflow.state not in {"running", "cancelling"}
    ):
        raise ExecutionLeaseLost("执行租约或任务状态已失效，旧 Worker 无权写入完成记录或发布材料")
    db.info["ar_execution_lock"] = action.id


def execution_version(workflow: WorkflowSession) -> str:
    from .ar_snapshot_contract import snapshot_execution_version

    root = workflow_root(workflow.owner_id, workflow.id) / "skill"
    if workflow.batch_id:
        batch = workflow.batch
        if batch is None or not batch.workflows:
            raise ValueError("任务所属批次或固定首日快照不存在")
        primary = min(batch.workflows, key=lambda item: item.batch_sequence)
        if any(getattr(primary, key) != getattr(workflow, key) for key in (
            "owner_id", "department_id", "skill_id", "skill_hash", "execution_mode",
        )):
            raise ValueError("批次日期与首日固定 Skill 身份不一致")
        source = workflow_root(primary.owner_id, primary.id) / "skill"
        version = snapshot_execution_version(source)
        # Later dates get their own copy only when execution starts. Claims must
        # already use the batch's immutable contract, including Agent claims.
        if root.exists() and snapshot_execution_version(root) != version:
            raise ValueError("本日 Skill 执行契约与批次固定快照不一致")
    else:
        version = snapshot_execution_version(root)
    context = json.loads(workflow.context_json or "{}")
    recorded = (context.get("ar_execution") or {}).get("schema_version")
    if recorded and recorded != version:
        raise ValueError("任务固定执行清单与已记录的执行契约不一致")
    return version


def initialize_execution(
    db: Session, workflow: WorkflowSession, business: Path,
    ledgers: dict[int, Path], flow_file: Path,
) -> dict[str, Any]:
    from . import workflow_service as service

    if execution_version(workflow) != CONTRACT_VERSION:
        raise ValueError("任务没有声明新的核销执行契约")
    context = json.loads(workflow.context_json or "{}")
    if context.get("ar_execution"):
        raise ValueError("取数后的执行流程已初始化，不能覆盖现有检查点")
    if (context.get("fetched_data") or {}).get("review_status") != "confirmed":
        raise ValueError("必须先确认取数包")
    material = workflow.material_set
    if material is None:
        raise ValueError("任务缺少固定业务材料版本")
    service.workflow_owner_context(db, workflow)
    from .ar_formal_ledger_service import inherit_formal_ledgers
    from .ar_agent_budget import initial_budget

    ledgers = fixed_annual_ledgers(business, ledgers)
    inherited = inherit_formal_ledgers(db, workflow, business)
    return {
        "workspace": str(business),
        "ledger_years": {str(year): str(path) for year, path in ledgers.items()},
        "flow_file": str(flow_file), "artifacts": [],
        "inherited_formal_ledgers": inherited,
        "ar_agent_budget": initial_budget(),
        "ar_execution": {
            "schema_version": CONTRACT_VERSION, "completed": [], "steps": {},
            "reconciliation_date": workflow.reconciliation_date,
            "material_set_id": material.id, "material_version": material.version,
            "ledger_years": {str(year): str(path) for year, path in ledgers.items()},
            "skill_hash": workflow.skill_hash, "next_tool": PHASES[0].tool,
            "publication": "not_published",
        },
    }


class ArExecution:
    def __init__(self, db: Session, action: WorkflowAction, workflow: WorkflowSession):
        from . import workflow_service as service

        self.service = service
        self.db = db
        self.action = action
        self.action._ar_claim_worker_id = action.worker_id
        self.workflow = workflow
        self.context = json.loads(workflow.context_json or "{}")
        self.execution = self.context.get("ar_execution") or {}
        if self.execution.get("schema_version") != CONTRACT_VERSION or execution_version(workflow) != CONTRACT_VERSION:
            raise ValueError("核销执行契约未初始化或与任务快照不一致")
        self.workspace = service._controlled_context_workspace(
            service._workflow_storage_root(db, workflow), workflow,
        )
        self.scripts = workflow_root(workflow.owner_id, workflow.id) / "skill" / "vendor" / "scripts"
        self.date = workflow.reconciliation_date
        self.tag = self.date.replace("-", "")
        self.output = self.workspace / "04_产出"
        # Classification, recovery and investigation share the original mapping.
        self.ledgers = fixed_annual_ledgers(self.workspace, self.context.get("ledger_years"))
        if self.execution.get("ledger_years") != {str(year): str(path) for year, path in self.ledgers.items()}:
            raise ValueError("年度盈亏映射与核销初始化时的固定记录不一致，不能继续原计划。")
        self.ledger_args = service._annual_ledger_arguments(self.ledgers)

    def script(self, name: str, arguments: list[str], *, accepted=(0,)) -> str:
        from .ar_process_evidence import run_recorded_script
        from .ar_lab_execution import cached_command

        lock_execution(self.db, self.action, self.workflow)
        self.verify_input_binding()
        latest_context = json.loads(self.workflow.context_json or "{}")
        if (self.workflow.state == "cancelling" or latest_context.get("stop_after_action")) and self.action.name != "ar_complete_reconciliation":
            raise ExecutionCancelled("任务已请求取消，未启动下一脚本")
        self.db.commit()
        self.db.info.pop("ar_execution_lock", None)
        name, arguments = cached_command(self, name, arguments)
        return run_recorded_script(self.scripts, name, arguments, action=self.action, workflow=self.workflow,
                                   accepted_returncodes=accepted)

    def verify_input_binding(self) -> None:
        from .workflow_material_service import current_material_set

        self.service.workflow_owner_context(self.db, self.workflow)
        current = current_material_set(
            self.db, self.workflow.owner_id, self.workflow.department_id, self.workflow.skill_id,
        )
        expected = (self.execution.get("steps", {}).get("publish_reconciliation")
                    if self.execution.get("publication") == "verified" else self.execution) or {}
        if (
            self.execution.get("reconciliation_date") != self.date
            or self.execution.get("skill_hash") != self.workflow.skill_hash
            or current is None
            or current.id != expected.get("material_set_id")
            or current.version != expected.get("material_version")
        ):
            raise ValueError("日期、Skill 或业务材料版本已改变，禁止沿用旧执行计划")

    def inspect_materials(self) -> dict[str, Any]:
        if self.workflow.batch_id and self.workflow.batch_sequence == 1:
            dates = self.service._load(self.workflow.batch.reconciliation_dates_json, [])
            if dates:
                self.service._run_shifted_details_audit(self.scripts, str(self.workspace), dates, script_runner=self.script)
        self.script("inspect_inputs.py", ["--workspace", str(self.workspace)])
        self.script("verify_sources.py", ["snapshot", "--workspace", str(self.workspace)])
        from .ar_lab_execution import AR_LAB_SKILL_ID, build_cache
        if self.workflow.skill_id == AR_LAB_SKILL_ID:
            return {"inputs_checked": True, "ar_read_cache": build_cache(self, self.workspace, self.ledgers)}
        return {"inputs_checked": True}

    def classify_receipts(self) -> dict[str, Any]:
        self.script("verify_sources.py", ["verify", "--workspace", str(self.workspace)])
        arguments = ["--workspace", str(self.workspace), "--hexiao-date", self.date]
        self.script("classify_hexiao.py", [*arguments, *self.ledger_args])
        self.script("build_flow_plan.py", arguments)
        self.script("build_execution_evidence.py", arguments)
        evidence = self.output / f"逐单证据_{self.tag}.json"
        raw = evidence.read_bytes()
        payload = json.loads(raw)
        return {"ar_evidence": {"fingerprint": hashlib.sha256(raw).hexdigest(),
                                "record_ids": [item["record_id"] for item in payload["records"]]}}

    def _review_evidence(self, *, final: bool = False) -> dict[str, Any]:
        page = read_evidence_page(self.db, self.workflow, limit=1)
        if not page.available:
            raise ValueError("逐单证据尚未生成")
        path = self.output / f"逐单证据_{self.tag}.json"
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != page.fingerprint:
            raise ValueError("读取期间逐单证据发生变化，请重新读取")
        evidence = json.loads(raw)
        expected = {item["record_id"] for item in evidence["records"]}
        mode = self.workflow.execution_mode
        if mode == "pi_harness" and expected:
            require_evidence_coverage(self.context, page.fingerprint, expected, final=final)
        for relative, fingerprint in evidence["sources"].items():
            path = (self.workspace / relative).resolve()
            if (
                not path.is_relative_to(self.workspace) or not path.is_file()
                or self.service.sha256_file(path) != fingerprint
            ):
                raise ValueError("逐单核对期间来源发生变化，不能继续校验写入计划")
        return {
            "mode": "agent_read_coverage" if mode == "pi_harness" else "deterministic_evidence_check",
            "fingerprint": page.fingerprint, "record_count": len(expected),
        }

    def review_order_evidence(self) -> dict[str, Any]:
        return {"evidence_review": self._review_evidence()}

    def validate_reconciliation(self) -> dict[str, Any]:
        self.script("verify_sources.py", ["verify", "--workspace", str(self.workspace)])
        checked = self.output / f"写入计划_校验后_{self.tag}.json"
        self.script("validate_plan.py", ["--workspace", str(self.workspace), "--hexiao-date", self.date,
                                         "--out", str(checked), *self.ledger_args], accepted=(0, 1))
        if not checked.is_file():
            raise ValueError("未生成当前日期的校验后计划")
        plan = json.loads(checked.read_text(encoding="utf-8"))
        return {"checked_plan": str(checked), "plan_fingerprint": self.service.sha256_file(checked),
                "validation_counts": plan.get("counts") or {},
                "pi_harness_write_guard": {
                    "reconciliation_date": self.date, "material_set_id": self.execution["material_set_id"],
                    "material_version": self.execution["material_version"],
                    "plan_fingerprint": self.service.sha256_file(checked),
                }}

    def build_initial_report(self) -> dict[str, Any]:
        report = self.output / f"核销日清_{self.tag}.xlsx"
        stdout = self.script("build_worklist.py", ["--workspace", str(self.workspace), "--hexiao-date", self.date,
                                                  "--checked", self.context["checked_plan"], "--out", str(report)])
        if not report.is_file():
            raise ValueError("未生成当前核销日期的首次日清")
        return {"summary": self.service._worklist_summary(stdout),
                "initial_report": {"path": str(report), "fingerprint": self.service.sha256_file(report)}}

    def stage_reconciliation(self) -> dict[str, Any]:
        checked = Path(self.context["checked_plan"]).resolve()
        if not checked.is_relative_to(self.workspace) or self.service.sha256_file(checked) != self.context["plan_fingerprint"]:
            raise ValueError("首次校验后计划已变化，拒绝创建写入暂存")
        self.script("verify_sources.py", ["verify", "--workspace", str(self.workspace)])
        stage = self.service._create_write_staging(self.workspace, self.action.id)
        for folder in ("04_产出", "03_台账"):
            for path in (stage / folder).glob("*.json"):
                if not path.name.startswith("逐单证据_"):
                    self.service._rewrite_staged_checked_plan(path, self.workspace, stage)
        staged_checked = self.service._staged_workspace_path(self.workspace, stage, checked)
        initial_report = stage / "04_产出" / f"首次核销日清_{self.tag}.xlsx"
        shutil.copy2(stage / "04_产出" / f"核销日清_{self.tag}.xlsx", initial_report)
        if self.service.sha256_file(initial_report) != self.context["initial_report"]["fingerprint"]:
            raise ValueError("暂存首次日清与已登记日清不一致")
        self.script("verify_sources.py", ["snapshot", "--workspace", str(stage)])
        files = self._workbook_fingerprints(stage)
        manifest = {
            "schema_version": CONTRACT_VERSION, "workflow_id": self.workflow.id,
            "material_set_id": self.execution["material_set_id"],
            "initial_plan_fingerprint": self.context["plan_fingerprint"],
            "checked_plan": str(staged_checked),
            "staged_plan_fingerprint": self.service.sha256_file(staged_checked),
            "files": files,
            "protected_inputs": {
                path.relative_to(stage).as_posix(): self.service.sha256_file(path)
                for path in (staged_checked, initial_report,
                             stage / "04_产出" / f"判定结果_{self.tag}.json",
                             stage / "04_产出" / "流转写入计划_校验后.json")
            },
        }
        self.service._write_publish_manifest(stage / "execution-manifest.json", manifest)
        return {"staging_workspace": str(stage), "manifest": manifest}

    def staging(self) -> tuple[Path, Path]:
        step = self.execution.get("steps", {}).get("stage_reconciliation") or {}
        stage = Path(str(step.get("staging_workspace") or "")).resolve()
        parent = (self.workspace / self.service.WRITE_STAGING_DIR).resolve()
        if not stage.is_dir() or stage == parent or not stage.is_relative_to(parent):
            raise ValueError("受控写入暂存不存在或超出当前任务")
        manifest = json.loads((stage / "execution-manifest.json").read_text(encoding="utf-8"))
        if manifest != step.get("manifest") or manifest.get("workflow_id") != self.workflow.id:
            raise ValueError("写入暂存清单与任务检查点不一致")
        for relative, fingerprint in manifest.get("protected_inputs", {}).items():
            source = (stage / relative).resolve()
            if (not source.is_relative_to(stage) or not source.is_file()
                    or self.service.sha256_file(source) != fingerprint):
                raise ValueError("首次判定、校验计划、流转计划或首次日清发生变化")
        checked = Path(manifest["checked_plan"]).resolve()
        if not checked.is_relative_to(stage) or self.service.sha256_file(checked) != manifest["staged_plan_fingerprint"]:
            raise ValueError("暂存校验后计划已变化")
        return stage, checked

    def _workbook_fingerprints(self, workspace: Path) -> dict[str, str]:
        return {
            path.relative_to(workspace).as_posix(): self.service.sha256_file(path)
            for path in sorted((workspace / "02_我的表副本").glob("*.xls*"))
            if path.is_file() and "便携版" not in path.name and not path.name.startswith(".")
        }

    def _require_staged_fingerprints(self, stage: Path, phase: str) -> None:
        previous = self.execution["steps"][phase]
        expected = previous.get("files") or previous.get("manifest", {}).get("files")
        if not isinstance(expected, dict) or self._workbook_fingerprints(stage) != expected:
            raise ValueError("暂存工作簿与上一阶段指纹不一致，禁止继续执行")

    def write_ledger(self) -> dict[str, Any]:
        if "ar_linked_recovery" in self.context:
            from .ar_recovery_adoption import adopt_ledger

            return adopt_ledger(self)
        stage, checked = self.staging()
        self._require_staged_fingerprints(stage, "stage_reconciliation")
        # validate_reconciliation accepts plans containing conflicts. The writer's
        # --force selects only plan.write; fingerprint and row prechecks still run.
        # Keep conflicts in the plan for the final report and hold rescan.
        stdout = self.script("apply_all.py", ["--checked", str(checked), "--workspace", str(stage),
                                              "--in-place", "--ledger-only", "--force"])
        markers = [line.removeprefix("AR_WRITE_RESULT ") for line in stdout.splitlines()
                   if line.startswith("AR_WRITE_RESULT ")]
        result = json.loads(markers[-1]) if markers else None
        plan = json.loads(checked.read_text(encoding="utf-8"))
        if (not isinstance(result, dict) or result.get("ledger_verified") is not True
                or result.get("publication_pending") is not True
                or result.get("ledger_written") is not bool(plan.get("write"))):
            raise ValueError("盈亏写入器未返回执行事实，不能认为写入成功")
        return {"ledger_written": result["ledger_written"], "ledger_verified": True,
                "files": self._workbook_fingerprints(stage)}

    def write_receipt_flow(self) -> dict[str, Any]:
        if "ar_linked_recovery" in self.context:
            from .ar_recovery_adoption import require_unstarted_flow

            require_unstarted_flow(self)
        stage, checked = self.staging()
        self._require_staged_fingerprints(stage, "write_ledger")
        self.script("execution_flow_stage.py", ["--checked", str(checked), "--workspace", str(stage)])
        path = stage / "04_产出" / "流转阶段执行结果.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("schema_version") != "ar-flow-result-v1":
            raise ValueError("流转阶段缺少结构化执行结果")
        if not result.get("flow_written"):
            original = Path(self.context["flow_file"]).resolve()
            if not original.is_file() or not original.is_relative_to(self.workspace):
                raise ValueError("流转失败后无法找到受控原流转副本")
            baseline = self.execution["steps"]["stage_reconciliation"]["manifest"]["files"]
            relative = original.relative_to(self.workspace).as_posix()
            if self.service.sha256_file(original) != baseline.get(relative):
                raise ValueError("流转失败且原副本已变化，不能发布或恢复")
            # Only this staged copy is restored. The original and ledger stay untouched.
            self.service._assert_valid_xlsx_package(original)
            shutil.copy2(original, stage / relative)
            if self.service.sha256_file(stage / relative) != baseline[relative]:
                raise ValueError("流转原副本恢复后指纹不一致，禁止发布")
            for phase_result in result.get("phases", {}).values():
                phase_result["attempted_changed_count"] = phase_result.get("changed_count", 0)
                phase_result["attempted_changes"] = phase_result.get("changes", [])
                phase_result["changed_count"] = 0
                phase_result["changes"] = []
                if phase_result.get("state") == "verified":
                    phase_result["state"] = "rolled_back"
                    phase_result["reason"] = "本阶段尝试的改动因后续流转失败已恢复，最终材料未保留这些改动。"
            result["restored_baseline"] = True
            result["reason"] = "流转阶段未全部完成，发布材料使用本任务已验证原流转副本；盈亏写入保留。"
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"flow_written": bool(result["flow_written"]), "flow_result": result,
                "files": self._workbook_fingerprints(stage)}

    def verify_reconciliation(self) -> dict[str, Any]:
        from .ar_lab_execution import AR_LAB_SKILL_ID, build_cache

        optimized = self.workflow.skill_id == AR_LAB_SKILL_ID
        stage, checked = self.staging()
        self._require_staged_fingerprints(stage, "write_receipt_flow")
        review = stage / "execution-review"
        if review.exists():
            recovered_from = (self.service._load(self.action.input_json, {}) or {}).get("recovered_from")
            failure = self.context.get("ar_failure") or {}
            if (not recovered_from or failure.get("action_id") != recovered_from
                    or failure.get("process_exit_confirmed") is not True or review.is_symlink()):
                raise ValueError("写后复核空间已存在，需核查检查点，不能自动重跑")
            archive = stage / f"execution-review-attempt-{recovered_from}"
            if archive.exists() or not review.resolve().is_relative_to(stage):
                raise ValueError("历史复核空间归属不明或已经归档，禁止覆盖")
            review.rename(archive)
        review.mkdir()
        for folder in ("01_智云导出", "02_我的表副本", "03_台账"):
            if optimized and folder == "02_我的表副本":
                # Lab classifiers receive explicit read-only workbook paths.
                # Actual writes and readback retain the normal staged files.
                (review / folder).mkdir()
                continue
            source = stage / folder
            if source.exists():
                shutil.copytree(source, review / folder, ignore=shutil.ignore_patterns("备份"))
        (review / "04_产出").mkdir()
        # Readback uses the actual applied row references saved by the writer.
        self.script("verify_execution_write.py", ["--workspace", str(stage), "--baseline", str(self.workspace),
                                                   "--checked", str(checked), "--flow-file",
                                                   str(self.service._staged_workspace_path(
                                                       self.workspace, stage, Path(self.context["flow_file"]))),
                                                   *self.service._annual_ledger_arguments(
                                                       annual_ledgers_in_copy(self.workspace, stage, self.ledgers))])
        arguments = ["--workspace", str(review), "--hexiao-date", self.date]
        ledgers = annual_ledgers_in_copy(self.workspace, stage if optimized else review, self.ledgers)
        if optimized:
            self.context["ar_read_cache"] = build_cache(self, stage, ledgers)
        ledger_args = self.service._annual_ledger_arguments(ledgers)
        flow_source = ["--flow-source-workspace", str(stage)] if optimized else []
        self.script("classify_hexiao.py", [*arguments, *ledger_args, *flow_source])
        rechecked = review / "04_产出" / f"写入计划_校验后_{self.tag}.json"
        self.script("validate_plan.py", [*arguments, "--out", str(rechecked), *ledger_args], accepted=(0, 1))
        plan = json.loads(rechecked.read_text(encoding="utf-8"))
        if plan.get("write"):
            raise ValueError("写后复核仍有待写项目；已停止发布，不自动执行第二轮写入")
        original = json.loads(checked.read_text(encoding="utf-8"))
        allowed_conflicts = {item.get("case_id") for item in original.get("conflict") or []}
        if any(item.get("case_id") not in allowed_conflicts for item in plan.get("conflict") or []):
            raise ValueError("写后复核出现新增冲突，需核对实际执行结果")
        self._require_staged_fingerprints(stage, "write_receipt_flow")
        return {"review_workspace": str(review), "counts": plan.get("counts") or {},
                **({"ar_read_cache": self.context["ar_read_cache"]} if optimized else {}),
                "checked_fingerprint": self.service.sha256_file(rechecked),
                "files": self._workbook_fingerprints(stage)}

    def rescan_holds(self) -> dict[str, Any]:
        stage, _ = self.staging()
        self._require_staged_fingerprints(stage, "verify_reconciliation")
        self.script("rescan_execution_holds.py", ["--workspace", str(stage), "--result",
                                       str(stage / "04_产出" / f"判定结果_{self.tag}.json"),
                                       *self.service._annual_ledger_arguments(annual_ledgers_in_copy(self.workspace, stage, self.ledgers))])
        self._require_staged_fingerprints(stage, "verify_reconciliation")
        return {"holds_rescanned": True, "files": self._workbook_fingerprints(stage)}

    def build_final_report(self) -> dict[str, Any]:
        stage, checked = self.staging()
        self._require_staged_fingerprints(stage, "rescan_holds")
        self.script("build_execution_report.py", ["--workspace", str(stage), "--checked", str(checked)])
        path = stage / "04_产出" / f"最终核销结果_{self.tag}.json"
        from .ar_result_summary import metrics_from_report

        report_bytes = path.read_bytes()
        payload = json.loads(report_bytes)
        report_fingerprint = hashlib.sha256(report_bytes).hexdigest()
        metrics = metrics_from_report(payload, self.date)
        ledgers = annual_ledgers_in_copy(self.workspace, stage, self.ledgers)
        flow = self.service._staged_workspace_path(self.workspace, stage, Path(self.context["flow_file"]))
        self.service._validate_staged_delivery(stage, ledgers, flow)
        self._require_staged_fingerprints(stage, "rescan_holds")
        return {"final_result": {"path": str(path), "fingerprint": report_fingerprint,
                                  "counts": payload["counts"], "metrics": metrics,
                                  "metrics_schema_version": "ar-final-metrics-v1", "metrics_fingerprint": report_fingerprint},
                "files": self._workbook_fingerprints(stage)}

    def review_final_report(self) -> dict[str, Any]:
        stage, _ = self.staging()
        self._require_staged_fingerprints(stage, "build_final_report")
        final = self.execution["steps"]["build_final_report"]["final_result"]
        path = Path(final["path"]).resolve()
        if not path.is_relative_to(stage) or self.service.sha256_file(path) != final["fingerprint"]:
            raise ValueError("最终清单版本发生变化，不能确认检查完成")
        review = self._review_evidence(final=True)
        return {"final_evidence_review": {**review, "final_fingerprint": final["fingerprint"]},
                "files": self._workbook_fingerprints(stage)}

    def publish_reconciliation(self) -> dict[str, Any]:
        stage, _ = self.staging()
        self._require_staged_fingerprints(stage, "review_final_report")
        final = self.execution["steps"]["build_final_report"]["final_result"]
        final_path = Path(final["path"]).resolve()
        if not final_path.is_relative_to(stage) or self.service.sha256_file(final_path) != final["fingerprint"]:
            raise ValueError("最终核销结果与已复核版本不一致")
        lock_execution(self.db, self.action, self.workflow)
        self.verify_input_binding()
        if self.workflow.state in {"cancelling", "cancelled"}:
            raise ExecutionCancelled("任务已请求取消，未发布暂存材料")
        ledgers = annual_ledgers_in_copy(self.workspace, stage, self.ledgers)
        flow = self.service._staged_workspace_path(self.workspace, stage, Path(self.context["flow_file"]))
        self.service._validate_staged_delivery(stage, ledgers, flow)
        self._require_staged_fingerprints(stage, "build_final_report")
        deliverables = [(self.service.ANNUAL_LEDGER_ROLE, path, year) for year, path in sorted(ledgers.items())]
        deliverables.append((self.service.RECEIPT_FLOW_ROLE, flow, None))
        bindings = {self.service.ANNUAL_LEDGER_ROLE: [], self.service.RECEIPT_FLOW_ROLE: []}
        annual_years = {}
        artifacts = []
        try:
            with self.db.begin_nested():
                for role, path, year in deliverables:
                    artifact = self.service._register_artifact(self.db, self.workflow, path, self.action.id)
                    artifacts.append(artifact)
                    bindings[role].append(artifact)
                    if year is not None:
                        annual_years[artifact["file_id"]] = year
                for path in (stage / "04_产出" / f"核销日清_{self.tag}.xlsx", final_path):
                    artifacts.append(self.service._register_artifact(self.db, self.workflow, path, self.action.id))
                material, next_files = self.service._publish_verified_material_set(
                    self.db, self.workflow, bindings, annual_years=annual_years)
        except Exception:
            self.service._discard_registered_artifacts(self.db, self.workflow, artifacts, self.action.id)
            raise
        self.workflow.material_set_id = material.id
        self.workflow.material_set = material
        self.workflow.files_json = self.service._json(next_files)
        return {"publication": "verified", "material_set_id": material.id,
                "material_version": material.version, "next_files": next_files,
                "artifacts": artifacts, "published_workspace": str(stage),
                "flow_written": self.execution["steps"]["write_receipt_flow"]["flow_written"],
                "final_result": final}

    def complete_reconciliation(self) -> dict[str, Any]:
        from .ar_publication import publication_manifest

        stage, checked = self.staging()
        self._require_staged_fingerprints(stage, "build_final_report")
        published = self.execution["steps"].get("publish_reconciliation") or {}
        if self.execution.get("publication") != "verified":
            raise ValueError("材料发布尚未确认，不能登记正式台账")
        publication = publication_manifest(self.db, self.workflow)
        reference = stage / "publication-confirmed.json"
        self.service._write_publish_manifest(reference, publication)
        self.db.commit()
        self.script("complete_execution.py", ["--workspace", str(stage), "--checked", str(checked),
                                               "--publication", str(reference), "--attempt", self.action.id])
        bundle = stage / "formal-ledger-build" / self.action.id / f"核销辅助台账_{self.tag}.json"
        payload = json.loads(bundle.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "ar-formal-ledgers-v1" or payload.get("publication") != publication:
            raise ValueError("正式辅助台账与已核实的材料发布记录不一致")
        self._require_staged_fingerprints(stage, "build_final_report")
        return {"formal_ledger_candidate": {"path": str(bundle), "fingerprint": self.service.sha256_file(bundle)},
                "publication": "verified", "material_set_id": published["material_set_id"],
                "material_version": published["material_version"], "next_files": published["next_files"]}


def execute_phase(db: Session, action: WorkflowAction, workflow: WorkflowSession) -> dict[str, Any]:
    from .ar_process_evidence import SCHEMA_VERSION

    action._ar_process_exit_confirmed = True  # No phase script has been launched yet.
    action._ar_process_records = []
    action._ar_process_evidence_version = SCHEMA_VERSION
    lock_execution(db, action, workflow)
    if workflow.state == "cancelling":
        raise ExecutionCancelled("任务已请求取消，未启动新的执行阶段")
    execution = ArExecution(db, action, workflow)
    requested = action.name.removeprefix("ar_")
    phase = require_phase(execution.execution.get("completed") or [], requested)
    execution.verify_input_binding()
    context = json.loads(workflow.context_json or "{}")
    context.update(current_step=phase.name, current_step_label=phase.label)
    context["ar_process_journal"] = {"schema_version": SCHEMA_VERSION, "action_id": action.id,
                                     "phase": phase.name, "attempt": action.attempt_count}
    context.pop("step_error", None)
    context.pop("error_detail", None)
    workflow.context_json = execution.service._json(context)
    workflow.progress = max(workflow.progress, phase.progress)
    workflow.progress_message = phase.label
    db.commit()
    db.info.pop("ar_execution_lock", None)
    handler = getattr(execution, phase.name, None)
    if handler is None:
        raise ValueError("当前 Worker 缺少此执行阶段，禁止退回旧流程")
    result = handler()
    result["process_records"] = list(action._ar_process_records)
    result["process_evidence_version"] = SCHEMA_VERSION
    completed = [*execution.execution.get("completed", []), phase.name]
    following = next_phase(completed)
    state = {
        **execution.execution, "completed": completed,
        "steps": {**execution.execution.get("steps", {}), phase.name: result},
        "next_tool": following.tool if following else "",
        "publication": result.get("publication", execution.execution.get("publication", "not_published")),
    }
    return {**result, "ar_execution": state}


def queue_execution_phase(
    db: Session, workflow: WorkflowSession, tool: str, arguments: dict[str, Any], *,
    harness_action_id: str, worker_id: str,
) -> WorkflowAction:
    from . import workflow_service as service
    from .scheduler import acquire_claim_lock

    db.commit()
    acquire_claim_lock(db)
    db.refresh(workflow)
    harness = db.get(WorkflowAction, harness_action_id)
    if harness is not None:
        db.refresh(harness)
    deadline = harness.lease_expires_at if harness else None
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if (harness is None or harness.workflow_id != workflow.id or harness.name != "pi_harness_execute"
            or harness.state != "running" or harness.worker_id != worker_id
            or deadline is None or deadline <= datetime.now(UTC)):
        raise HTTPException(status_code=409, detail="Agent 执行租约已失效，未派发新阶段。")
    if workflow.state in {"failed", "succeeded", "cancelled", "cancelling"}:
        raise HTTPException(status_code=409, detail="当前任务已停止，不能派发执行阶段。")
    service.workflow_owner_context(db, workflow)
    context = json.loads(workflow.context_json or "{}")
    state = context.get("ar_execution") or {}
    if state.get("schema_version") != CONTRACT_VERSION or execution_version(workflow) != CONTRACT_VERSION:
        raise HTTPException(status_code=409, detail="当前任务未初始化新版执行流程。")
    requested = TOOL_PHASE[tool]
    action_name = f"ar_{requested}"
    completed = state.get("completed") or []
    guard = {
        "reconciliation_date": workflow.reconciliation_date,
        "material_set_id": state.get("material_set_id"),
        "material_version": state.get("material_version"),
        "plan_fingerprint": context.get("plan_fingerprint"),
    }
    if (arguments != (guard if tool in GUARDED_TOOLS else {})
            or (tool in GUARDED_TOOLS and type(arguments.get("material_version")) is not int)):
        raise HTTPException(status_code=409, detail="阶段参数与任务固定写入条件不一致。")
    if requested in completed:
        existing = db.scalar(select(WorkflowAction).where(
            WorkflowAction.workflow_id == workflow.id, WorkflowAction.name == action_name,
            WorkflowAction.state == "succeeded",
        ).order_by(WorkflowAction.queued_at.desc()))
        if existing is None:
            raise HTTPException(status_code=409, detail="阶段检查点缺少对应执行事实。")
        return existing
    try:
        require_phase(completed, requested)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if requested in {"review_order_evidence", "review_final_report"}:
        evidence = context.get("ar_evidence") or {}
        if not isinstance(evidence.get("record_ids"), list):
            raise HTTPException(status_code=409, detail="当前逐单证据缺少固定记录索引，不能确认检查完成。")
        try:
            require_evidence_coverage(context, evidence.get("fingerprint", ""), set(evidence["record_ids"]),
                                      final=requested == "review_final_report")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if tool in GUARDED_TOOLS:
        current = service.current_material_set(db, workflow.owner_id, workflow.department_id, workflow.skill_id)
        checked = Path(str(context.get("checked_plan") or "")).resolve()
        root = service._workflow_storage_root(db, workflow).resolve()
        if (current is None or current.id != guard["material_set_id"] or current.version != guard["material_version"]
                or not checked.is_file() or not checked.is_relative_to(root)
                or service.sha256_file(checked) != guard["plan_fingerprint"]):
            raise HTTPException(status_code=409, detail="材料版本或校验计划已变化，未派发写入阶段。")
    pending = db.scalar(select(WorkflowAction).where(
        WorkflowAction.workflow_id == workflow.id, WorkflowAction.name == action_name,
        WorkflowAction.state.in_(("queued", "running")),
    ))
    if pending is not None:
        return pending
    failed = db.scalar(select(WorkflowAction.id).where(
        WorkflowAction.workflow_id == workflow.id, WorkflowAction.name == action_name,
        WorkflowAction.state == "failed",
    ))
    if failed:
        raise HTTPException(status_code=409, detail="该阶段执行失败，必须核对恢复条件，不能自动重试。")
    action = service._queue_action(db, workflow, action_name, {"pi_harness_tool": tool})
    db.commit()
    return action


def transition_phase(db: Session, action: WorkflowAction, workflow: WorkflowSession, result: dict[str, Any]) -> None:
    from . import workflow_service as service

    # Publication, checkpoint, cancellation and next action share one transaction.
    # Do not refresh/commit a publication that is pending in this same transaction.
    if db.info.get("ar_execution_lock") != action.id:
        lock_execution(db, action, workflow)
    initial = result.get("initial_report")
    if initial:
        report = Path(initial["path"]).resolve()
        if service.sha256_file(report) != initial["fingerprint"]:
            raise ValueError("首次日清在登记前发生变化")
        result["artifacts"] = [service._register_artifact(db, workflow, report, action.id)]
    formal = result.get("formal_ledger_candidate")
    if formal:
        # A pending bundle becomes authoritative atomically with the completed
        # phase. A lost response therefore cannot require another workbook write.
        execution = ArExecution(db, action, workflow)
        execution.verify_input_binding()
        bundle = Path(formal["path"]).resolve()
        if service.sha256_file(bundle) != formal["fingerprint"]:
            raise ValueError("正式辅助台账在登记前发生变化")
        artifact = service._register_artifact(db, workflow, bundle, action.id)
        result["artifacts"] = [artifact]
        result["formal_ledgers"] = {"file_id": artifact["file_id"], "sha256": artifact["sha256"]}
    action.result_json = service._json(result)
    action.state = "succeeded"
    action.finished_at = service.datetime.now(service.UTC)
    context = json.loads(workflow.context_json or "{}")
    context.update(result)
    workflow.context_json = service._json(context)
    state = result["ar_execution"]
    phase = next_phase(state.get("completed") or [])
    artifacts = service._load(workflow.artifacts_json, [])
    artifacts.extend(result.get("artifacts") or [])
    workflow.artifacts_json = service._json(artifacts)
    needs_formal_completion = phase is not None and phase.name == "complete_reconciliation"
    if (context.get("stop_after_action") or workflow.state in {"cancelling", "cancelled"}) and not needs_formal_completion:
        workflow.state = "cancelled"
        workflow.stage = "cancelled"
        workflow.progress_message = "当前步骤已结束，按取消请求停止后续执行"
        return
    if phase is not None:
        workflow.stage = "preparing" if phase.progress < 58 else "applying"
        workflow.state = "running"
        workflow.progress_message = f"等待{phase.label}"
        if workflow.execution_mode == "workflow" or needs_formal_completion:
            service._new_action(db, workflow, f"ar_{phase.name}")
        return
    # No terminal success is inferred from an empty next step without publication.
    if state.get("publication") != "verified" or not context.get("formal_ledgers"):
        raise ValueError("执行步骤已结束但正式发布尚未核实，不能标记任务完成")
    workflow.state = "succeeded"
    workflow.stage = "completed"
    workflow.progress = 100
    workflow.progress_message = "核销及最终复核完成，结果已发布"
    if workflow.fetched_bundle_id and not workflow.batch_id:
        service.finalize_bundle(db, bundle_id=workflow.fetched_bundle_id, outcome="succeeded")
    service._advance_batch(db, workflow, result, action)
