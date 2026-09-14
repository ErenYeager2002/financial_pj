"""Consolidation business records. Platform Run remains the only job state machine."""
from __future__ import annotations
import json
from pathlib import Path
from sqlalchemy import text

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS consolidation;
REVOKE ALL ON SCHEMA consolidation FROM PUBLIC;
CREATE TABLE IF NOT EXISTS consolidation.company (
 code text PRIMARY KEY, name text NOT NULL, legal_name text NOT NULL, mother_member boolean NOT NULL);
CREATE TABLE IF NOT EXISTS consolidation.report_item (
 template_version text NOT NULL, report_kind text NOT NULL CHECK(report_kind IN ('bs','is','cf')),
 item_code integer NOT NULL, label text NOT NULL, display_row integer NOT NULL, display_col integer NOT NULL,
 PRIMARY KEY(template_version,report_kind,item_code));
CREATE TABLE IF NOT EXISTS consolidation.report_template (
 version text NOT NULL, report_kind text NOT NULL, definition jsonb NOT NULL,
 PRIMARY KEY(version,report_kind));
CREATE TABLE IF NOT EXISTS consolidation.report_metric (
 report_kind text NOT NULL, metric integer NOT NULL, code text NOT NULL, label text NOT NULL,
 PRIMARY KEY(report_kind,metric));
CREATE TABLE IF NOT EXISTS consolidation.item_mapping (
 version text NOT NULL, report_kind text NOT NULL, source_template text NOT NULL,
 target_item integer NOT NULL, source_items jsonb NOT NULL,
 PRIMARY KEY(version,report_kind,source_template,target_item));
CREATE TABLE IF NOT EXISTS consolidation.rule_version (
 version text PRIMARY KEY, description text NOT NULL, definition jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS consolidation.run_snapshot (
 run_id varchar(36) PRIMARY KEY REFERENCES public.runs(id),
 owner_id varchar(36) NOT NULL, department_id varchar(36) NOT NULL,
 period char(6) NOT NULL, rule_version text NOT NULL REFERENCES consolidation.rule_version(version),
 template_version text NOT NULL, complete boolean NOT NULL, coverage jsonb NOT NULL,
 issues jsonb NOT NULL, parent_run_id varchar(36) REFERENCES public.runs(id));
CREATE TABLE IF NOT EXISTS consolidation.report_record (
 run_id varchar(36) NOT NULL REFERENCES consolidation.run_snapshot(run_id),
 company_code text NOT NULL REFERENCES consolidation.company(code),
 report_kind text NOT NULL CHECK(report_kind IN ('bs','is','cf')), source_file_id text,
 source_name text NOT NULL, source_sheet text NOT NULL, source_sha256 char(64) NOT NULL,
 source_template text NOT NULL, issues jsonb NOT NULL, checks jsonb NOT NULL,
 PRIMARY KEY(run_id,company_code,report_kind));
CREATE TABLE IF NOT EXISTS consolidation.report_value (
 run_id varchar(36) NOT NULL, company_code text NOT NULL, report_kind text NOT NULL,
 stage text NOT NULL CHECK(stage IN ('raw','classified')), item_code integer NOT NULL,
 metric integer NOT NULL CHECK(metric IN(0,1)), amount numeric(24,2) NOT NULL,
 value_state text NOT NULL, source_cells jsonb NOT NULL,
 PRIMARY KEY(run_id,company_code,report_kind,stage,item_code,metric),
 FOREIGN KEY(run_id,company_code,report_kind) REFERENCES consolidation.report_record(run_id,company_code,report_kind));
REVOKE ALL ON ALL TABLES IN SCHEMA consolidation FROM PUBLIC;
"""

def migrate(connection, skill_dir: Path):
    for statement in SCHEMA_SQL.split(";"):
        if statement.strip():connection.execute(text(statement))
    catalog=json.loads((skill_dir/"templates/catalog.json").read_text("utf-8"))
    companies=json.loads((skill_dir/"templates/companies.json").read_text("utf-8"))
    for code,(name,legal,mother) in companies.items():
        connection.execute(text("INSERT INTO consolidation.company VALUES(:code,:name,:legal,:mother) ON CONFLICT DO NOTHING"),dict(code=code,name=name,legal=legal,mother=mother))
    for kind,spec in catalog["standard"].items():
        connection.execute(text("INSERT INTO consolidation.report_template VALUES(:version,:kind,CAST(:definition AS jsonb)) ON CONFLICT DO NOTHING"),dict(version=catalog["version"],kind=kind,definition=json.dumps(spec)))
        metrics=[("closing","期末余额"),("year_opening","年初余额")] if kind=="bs" else [("current_month","本月金额"),("year_to_date","本年累计金额")]
        for index,(metric,label) in enumerate(metrics):
            connection.execute(text("INSERT INTO consolidation.report_metric VALUES(:kind,:index,:metric,:label) ON CONFLICT DO NOTHING"),dict(kind=kind,index=index,metric=metric,label=label))
    for kind,spec in catalog["standard"].items():
        for row in spec["rows"]:
            if row["id"]:
                connection.execute(text("INSERT INTO consolidation.report_item VALUES(:version,:kind,:item,:label,:row,:col) ON CONFLICT DO NOTHING"),dict(version=catalog["version"],kind=kind,item=row["id"],label=row["label"],row=row["row"],col=row["col"]))
    connection.execute(text("INSERT INTO consolidation.rule_version VALUES('sd-management-to-cost-v1','山东管理费用计入营业成本',CAST(:rule AS jsonb)) ON CONFLICT DO NOTHING"),dict(rule=json.dumps({"company":"SHANDONG","cost":"source_cost+source_management","management":"0"})))

def persist(ctx, result):
    path=(ctx.workspace/"outputs/报表来源与核验记录.json").resolve()
    if not path.is_relative_to((ctx.workspace/"outputs").resolve()) or not path.is_file():
        raise RuntimeError("报表核验记录不存在")
    audit=json.loads(path.read_text("utf-8"))
    parameters=json.loads(ctx.run.parameters_json)
    parent=parameters.get("parent_run_id") or None
    ctx.db.execute(text("""INSERT INTO consolidation.run_snapshot
      VALUES(:run,:owner,:department,:period,:rule,:template,:complete,CAST(:coverage AS jsonb),CAST(:issues AS jsonb),:parent)"""),
      dict(run=ctx.run.id,owner=ctx.run.owner_id,department=ctx.run.department_id,period=audit["period"],rule=audit["rules_version"],template=audit["template_version"],complete=audit["complete"],coverage=json.dumps(audit["coverage"]),issues=json.dumps(audit["issues"]),parent=parent))
    for report in audit["reports"]:
        common=dict(run=ctx.run.id,company=report["company"],kind=report["kind"])
        ctx.db.execute(text("""INSERT INTO consolidation.report_record
          VALUES(:run,:company,:kind,:file,:name,:sheet,:sha,:template,CAST(:issues AS jsonb),CAST(:checks AS jsonb))"""),
          dict(**common,file=report["source_file_id"] or None,name=report["file_name"],sheet=report["sheet"],sha=report["file_hash"],template=report["template"],issues=json.dumps(report["issues"]),checks=json.dumps(report["checks"])))
        for stage,key in [("raw","raw_values"),("classified","classified_values")]:
            rows=[dict(**common,stage=stage,item=v["item"],metric=v["metric"],amount=v["amount"],state=v["state"],refs=json.dumps(v["refs"])) for v in report[key]]
            ctx.db.execute(text("""INSERT INTO consolidation.report_value VALUES
              (:run,:company,:kind,:stage,:item,:metric,:amount,:state,CAST(:refs AS jsonb))"""),rows)

def inherited_metadata(ctx):
    from sqlalchemy import select
    from .models import FileRecord, RunRecord
    from .storage import sha256_file
    parameters=json.loads(ctx.run.parameters_json)
    parent_id=parameters.get("parent_run_id")
    if not parent_id:return {"confirmed_bs_hashes": []}
    parent=ctx.db.get(RunRecord,parent_id)
    if not parent or parent.owner_id!=ctx.run.owner_id or parent.skill_id!=ctx.run.skill_id:
        raise RuntimeError("补充版本来源权限校验失败")
    record=ctx.db.scalar(select(FileRecord).where(
        FileRecord.run_id==parent_id,FileRecord.owner_id==ctx.run.owner_id,
        FileRecord.original_name=="报表来源与核验记录.json"))
    if not record:return {"confirmed_bs_hashes": []}
    path=Path(record.stored_path)
    if not path.is_file() or sha256_file(path)!=record.sha256:
        raise RuntimeError("上次来源核验记录不完整")
    audit=json.loads(path.read_text("utf-8"))
    return {"confirmed_bs_hashes": [r["file_hash"] for r in audit["reports"] if r.get("bs_reclassified")]}

def link_sources(ctx):
    from sqlalchemy import select
    from .models import FileRecord
    path=ctx.workspace/"outputs/报表来源与核验记录.json"
    audit=json.loads(path.read_text("utf-8"))
    records=ctx.db.scalars(select(FileRecord).where(FileRecord.run_id==ctx.run.id,FileRecord.owner_id==ctx.run.owner_id)).all()
    sources={record.sha256: record.id for record in records}
    for report in audit["reports"]:
        if not report.get("source_file_id"):
            report["source_file_id"]=sources.get(report["file_hash"])
            if not report["source_file_id"]:
                raise RuntimeError("采集来源尚未登记为平台文件")
    path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
