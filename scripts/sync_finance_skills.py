from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_SKILLS = PROJECT_ROOT / "skills"
SOURCE_SKILLS = PROJECT_ROOT / "sources" / "finance-skills" / "skills"
BRIDGE_TEMPLATE = PROJECT_ROOT / "scripts" / "legacy_skill_bridge.py"
UNAVAILABLE_TEMPLATE = PROJECT_ROOT / "scripts" / "unavailable_skill.py"
ZHIYUN_FETCH_TEMPLATE = PROJECT_ROOT / "scripts" / "secure_zhiyun_fetch.py"

COMMON_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["status", "summary", "output_files", "warnings"],
    "properties": {
        "status": {"const": "success"},
        "summary": {"type": "object"},
        "output_files": {"type": "array"},
        "warnings": {"type": "array"},
    },
}

DISPLAY_METADATA: dict[str, dict[str, Any]] = {
    "labor-invoice-check": {
        "output_summary": "核对结果和差异清单",
        "action_label": "开始核对",
        "estimated_minutes": 2,
        "popular": True,
    },
    "receivables-merge": {
        "output_summary": "合并后的应收台账",
        "action_label": "开始合并",
        "estimated_minutes": 3,
        "popular": True,
    },
    "dept-expense-alloc": {
        "output_summary": "部门和科目分摊结果",
        "action_label": "开始分摊",
        "estimated_minutes": 3,
        "popular": True,
    },
    "withholding-report-rename": {
        "output_summary": "规范命名的 PDF 副本",
        "action_label": "开始整理",
        "estimated_minutes": 1,
        "popular": True,
    },
    "ar-hexiao-daily": {
        "output_summary": "写入后的到账流转表、年度盈亏核算表和整合核销日清",
        "action_label": "开始核销",
        "estimated_minutes": 10,
        "popular": False,
    },
    "jdy-cashflow-reconcile": {
        "output_summary": "现金流量差异明细",
        "action_label": "开始核对",
        "estimated_minutes": 3,
        "popular": False,
    },
}

DEFAULT_PROGRESS_STAGES = [
    {"key": "reading_files", "label": "正在读取文件"},
    {"key": "validating_fields", "label": "正在检查字段"},
    {"key": "processing", "label": "正在处理数据"},
    {"key": "generating_output", "label": "正在生成结果文件"},
]


def file_spec(
    role: str,
    name: str,
    extensions: list[str],
    *,
    description: str = "",
    required: bool = True,
    multiple: bool = False,
    min_files: int = 1,
) -> dict[str, Any]:
    return {
        "role": role,
        "name": name,
        "description": description,
        "required": required,
        "multiple": multiple,
        "min_files": min_files,
        "extensions": extensions,
        "max_size_mb": 100,
    }


def manifest(
    skill_id: str,
    name: str,
    category: str,
    description: str,
    tags: list[str],
    file_inputs: list[dict[str, Any]],
    input_schema: dict[str, Any],
    *,
    status: str = "published",
    adapter: str = "python",
    risk: str = "read_only",
    confirmation: bool = False,
    change_review: bool = False,
    approval: bool = False,
    timeout: int = 600,
    network_access: bool = False,
    network_targets: list[str] | None = None,
    version: str = "1.0.0",
    blocked_reason: str = "",
) -> dict[str, Any]:
    display = DISPLAY_METADATA.get(skill_id, {})
    value = {
        "schema_version": 1,
        "id": skill_id,
        "name": name,
        "version": version,
        "status": status,
        "category": category,
        "description": description,
        "ui": {
            "employee_name": name,
            "short_description": description,
            "categories": [category],
            "estimated_minutes": display.get("estimated_minutes", max(1, timeout // 300)),
            "output_summary": display.get("output_summary", "处理结果文件和业务摘要"),
            "action_label": display.get("action_label", "开始处理"),
            "popular": display.get("popular", False),
        },
        "tags": tags,
        "file_inputs": file_inputs,
        "input_schema": input_schema,
        "output_schema": COMMON_OUTPUT_SCHEMA,
        "handler": (
            {"adapter": "workflow", "worker_pool": "workflow"}
            if adapter == "workflow"
            else {
                "adapter": adapter,
                "entrypoint": "scripts/entry.py",
                "worker_pool": "rpa" if adapter == "rpa" else "python",
            }
        ),
        "runtime": {
            "timeout_seconds": timeout,
            "memory_mb": 2048,
            "concurrency_limit": 1,
            "network_access": network_access or adapter == "rpa",
            "network_targets": network_targets or [],
        },
        "risk": {
            "level": risk,
            "requires_confirmation": confirmation or status == "published",
            "requires_change_review": change_review,
            "requires_approval": approval,
            "modifies_uploaded_files": False,
        },
        "permissions": {"run": "finance_user", "manage": "skill_admin"},
        "safety_constraints": {},
        "progress_stages": DEFAULT_PROGRESS_STAGES,
        "result_presentation": {"metrics": []},
        "upstream": {
            "repository": "https://gitee.com/Lee157/finance-skills.git",
            "path": f"skills/{skill_id}",
        },
    }
    if blocked_reason:
        value["blocked_reason"] = blocked_reason
    return value


EXECUTABLES: dict[str, dict[str, Any]] = {
    "project-detail-to-ledger": {
        "manifest": manifest(
            "project-detail-to-ledger",
            "项目明细补录",
            "经营报表",
            "自动识别项目明细表和盈亏核算表，按固定字段映射追加到轻量副本；"
            "数量、单价和应收金额转为数字，按 SO+SOD 跳过重复记录，"
            "并移除历史外链和打开时强制完整重算。",
            ["Excel", "项目明细", "盈亏核算", "字段映射", "副本"],
            [
                file_spec("project_detail", "项目明细表", ["xlsx"]),
                file_spec("ledger", "盈亏核算表", ["xlsx"]),
            ],
            {"type": "object", "additionalProperties": False, "properties": {}},
            status="published",
            adapter="python",
            risk="read_only",
            confirmation=False,
            timeout=600,
            network_access=False,
            version="1.1.0",
        ),
        "bridge": {
            "name": "项目明细补录",
            "command": "vendor/scripts/append_project_detail.py",
            "arguments": [
                {"kind": "file", "role": "project_detail", "flag": "--project"},
                {"kind": "file", "role": "ledger", "flag": "--ledger"},
            ],
            "output": {
                "type": "file",
                "flag": "--output",
                "path": "项目明细补录结果.xlsx",
                "additional_globs": ["*_补录报告.json"],
            },
            "success_message": "项目明细已经映射追加，结果表和校验报告已生成。",
        },
    },
    "receivables-merge": {
        "manifest": manifest(
            "receivables-merge",
            "应收账款合并",
            "应收管理",
            "合并应收源台账并按上一版台账回填，生成新的应收 all 工作簿。",
            ["Excel", "应收", "合并", "离线"],
            [
                file_spec("source", "本期应收源台账", ["xlsx", "xls"]),
                file_spec("reference", "上一版应收 all", ["xlsx", "xls"], required=False),
            ],
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "base_month": {
                        "type": "string",
                        "title": "账龄基准月",
                        "description": "可留空自动识别；补历史月份时填写 YYYYMM。",
                        "pattern": "^$|^\\d{6}$",
                        "default": "",
                    }
                },
            },
        ),
        "bridge": {
            "name": "应收账款合并",
            "command": "vendor/scripts/merge.py",
            "arguments": [
                {"kind": "file", "role": "source", "flag": "--source"},
                {"kind": "file", "role": "reference", "flag": "--ref"},
                {"kind": "parameter", "name": "base_month", "flag": "--base-month"},
            ],
            "output": {"type": "file", "flag": "--out", "path": "应收账款合并结果.xlsx"},
            "success_message": "应收 all 工作簿已经生成。",
        },
    },
    "split-by-sales": {
        "manifest": manifest(
            "split-by-sales",
            "应收按销售人员拆分",
            "应收管理",
            "按照维护规则将应收 all 拆分成销售人员独立工作簿。",
            ["Excel", "应收", "销售拆分", "离线"],
            [file_spec("receivables", "应收 all", ["xlsx", "xls"])],
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "date_label": {
                        "type": "string",
                        "title": "文件日期标签",
                        "description": "可留空自动识别；手工填写时使用 MMDD。",
                        "pattern": "^$|^\\d{4}$",
                        "default": "",
                    }
                },
            },
        ),
        "bridge": {
            "name": "应收按销售人员拆分",
            "command": "vendor/scripts/split.py",
            "arguments": [
                {"kind": "file", "role": "receivables", "flag": "--input"},
                {"kind": "parameter", "name": "date_label", "flag": "--date"},
            ],
            "output": {
                "type": "directory",
                "flag": "--out-dir",
                "path": "拆分结果",
                "archive": True,
                "archive_name": "应收按销售拆分结果.zip",
            },
            "success_message": "销售人员拆分文件已经打包。",
        },
    },
    "labor-invoice-check": {
        "manifest": manifest(
            "labor-invoice-check",
            "劳务发票核对",
            "发票核对",
            "按业务规则核对劳务清单与发票台账，输出支付前核对结果。",
            ["Excel", "劳务", "发票", "核对"],
            [
                file_spec("labor_list", "劳务清单", ["xlsx", "xls"]),
                file_spec("invoice_ledger", "发票台账", ["xlsx", "xls"]),
            ],
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
        "bridge": {
            "name": "劳务发票核对",
            "command": "vendor/scripts/check.py",
            "arguments": [
                {"kind": "file", "role": "labor_list", "flag": "--list"},
                {"kind": "file", "role": "invoice_ledger", "flag": "--invoice"},
            ],
            "output": {"type": "file", "flag": "--out", "path": "劳务发票核对结果.xlsx"},
            "success_message": "劳务发票核对结果已经生成。",
        },
    },
    "withholding-report-rename": {
        "manifest": manifest(
            "withholding-report-rename",
            "代扣代缴申报表批量重命名",
            "文件整理",
            "识别申报表 PDF 内容并生成规范命名的副本，平台不会修改上传原件。",
            ["PDF", "申报表", "批量重命名", "副本"],
            [
                file_spec(
                    "reports",
                    "申报表 PDF",
                    ["pdf"],
                    multiple=True,
                    description="可一次上传多份 PDF。",
                )
            ],
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
        "bridge": {
            "name": "代扣代缴申报表批量重命名",
            "command": "vendor/scripts/rename.py",
            "arguments": [
                {"kind": "input_dir", "role": "reports", "flag": "--input"},
                {"kind": "static", "values": ["--mode", "copy"]},
            ],
            "output": {
                "type": "directory",
                "flag": "--out-dir",
                "path": "重命名结果",
                "required_globs": ["*.pdf"],
                "archive": True,
                "archive_name": "代扣代缴申报表重命名结果.zip",
            },
            "success_message": "规范命名的申报表副本已经打包。",
        },
    },
    "compliance-spot-check": {
        "manifest": manifest(
            "compliance-spot-check",
            "合规文件抽查建议",
            "合规检查",
            "依据应收 all 和可选历史记录生成本周合规抽查建议清单。",
            ["Excel", "合规", "抽查", "建议"],
            [
                file_spec("receivables", "应收 all", ["xlsx", "xls"]),
                file_spec("history", "抽查历史", ["csv"], required=False),
            ],
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
        "bridge": {
            "name": "合规文件抽查建议",
            "command": "vendor/scripts/recommend.py",
            "arguments": [
                {"kind": "file", "role": "receivables", "flag": "--input"},
                {"kind": "file", "role": "history", "flag": "--history"},
            ],
            "output": {
                "type": "file",
                "flag": "--out",
                "path": "本周合规抽查建议.xlsx",
                "additional_globs": ["*.txt"],
            },
            "success_message": "本周合规抽查建议已经生成。",
        },
    },
    "dreame-ar-progress-diff": {
        "manifest": manifest(
            "dreame-ar-progress-diff",
            "追觅应收进度对比",
            "应收管理",
            "对两份及以上追觅应收进度表做期间并集、人名对齐和变化对比。",
            ["Excel", "应收", "多版本对比", "追觅"],
            [
                file_spec(
                    "versions",
                    "应收进度版本",
                    ["xlsx", "xlsm"],
                    multiple=True,
                    min_files=2,
                    description="请按旧到新顺序上传至少两份。",
                )
            ],
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
        "bridge": {
            "name": "追觅应收进度对比",
            "command": "vendor/scripts/compare.py",
            "arguments": [{"kind": "files", "role": "versions", "flag": "--files"}],
            "output": {"type": "file", "flag": "--out", "path": "追觅应收进度对比报告.xlsx"},
            "success_message": "多版本应收进度对比报告已经生成。",
        },
    },
    "dept-expense-alloc": {
        "manifest": manifest(
            "dept-expense-alloc",
            "部门费用归集分摊",
            "费用管理",
            "读取费用材料并按配置规则归集、分摊到部门和科目。",
            ["Excel", "费用", "部门", "分摊"],
            [
                file_spec(
                    "materials",
                    "费用分摊材料",
                    ["xlsx", "xls", "csv"],
                    multiple=True,
                    description="上传本次归集所需的全部材料。",
                )
            ],
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
        "bridge": {
            "name": "部门费用归集分摊",
            "command": "vendor/scripts/allocate.py",
            "arguments": [{"kind": "input_dir", "role": "materials", "flag": "--input-dir"}],
            "output": {"type": "file", "flag": "--out", "path": "部门费用归集分摊结果.xlsx"},
            "success_message": "部门费用归集分摊表已经生成。",
        },
    },
    "order-daily-summary": {
        "manifest": manifest(
            "order-daily-summary",
            "九点下单统计（离线）",
            "经营报表",
            "使用九点导出的下单明细生成部门汇总和明细表；平台版不登录业务系统。",
            ["Excel", "订单", "日报", "离线"],
            [file_spec("orders", "九点下单明细", ["xlsx", "xls"])],
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "today": {
                        "type": "string",
                        "title": "统计运行日",
                        "description": "可留空使用当天；指定时填写 YYYY-MM-DD。",
                        "pattern": "^$|^\\d{4}-\\d{2}-\\d{2}$",
                        "default": "",
                    },
                    "include_detail": {
                        "type": "boolean",
                        "title": "输出明细 Sheet",
                        "default": True,
                    },
                    "no_date_filter": {
                        "type": "boolean",
                        "title": "不按日期二次过滤",
                        "description": "补断档或上传已筛选导出表时建议开启。",
                        "default": True,
                    },
                },
            },
        ),
        "bridge": {
            "name": "九点下单统计（离线）",
            "command": "vendor/scripts/run.py",
            "arguments": [
                {"kind": "file", "role": "orders", "flag": "--from-xlsx"},
                {"kind": "parameter", "name": "today", "flag": "--today"},
                {
                    "kind": "parameter",
                    "name": "include_detail",
                    "flag": "--detail",
                    "boolean": True,
                },
                {
                    "kind": "parameter",
                    "name": "no_date_filter",
                    "flag": "--no-date-filter",
                    "boolean": True,
                },
            ],
            "output": {
                "type": "directory",
                "flag": "--out",
                "path": "下单统计结果",
                "archive": True,
                "archive_name": "九点下单统计结果.zip",
            },
            "success_message": "九点下单统计结果已经打包。",
        },
    },
}


CATALOG_ONLY: dict[str, dict[str, Any]] = {
    "ar-hexiao-daily": manifest(
        "ar-hexiao-daily",
        "应收核销日清",
        "应收管理",
        "应收核销多阶段流程，自动登录智云取数，按核销记录身份审计并纠正可解释的系统重复核销；日清与写前校验通过后直接安全写入副本，并按真实单元格坐标归一化公式差异。",
        ["应收核销", "自动写入", "多阶段"],
        [
            file_spec(
                "profit_loss_ledgers",
                "年度盈亏核算表",
                ["xlsx", "xlsm", "xls"],
                multiple=True,
                min_files=1,
                description=(
                    "可上传多个年度的盈亏核算表，每个年度保留一份；首次上传后后续任务会自动复用，"
                    "也可以按需增加或替换。"
                ),
            ),
            file_spec(
                "receipt_flow_table",
                "到账流转表",
                ["xlsx", "xlsm", "xls"],
                description="只保留一份到账流转表；首次上传后后续任务会自动复用，需要更换时再上传新表。",
            ),
        ],
        {"type": "object", "additionalProperties": False, "properties": {}},
        status="published",
        adapter="workflow",
        risk="write",
        confirmation=True,
        change_review=True,
        approval=True,
        timeout=1800,
        network_access=True,
        network_targets=["http://192.168.10.167:18880"],
        version="1.6.10",
    ),
    "jdy-cashflow-export": manifest(
        "jdy-cashflow-export",
        "金蝶云现金流量调整导出",
        "RPA",
        "登录金蝶云并逐项导出现金流量调整明细。",
        ["RPA", "金蝶云", "现金流量"],
        [],
        {"type": "object", "additionalProperties": True, "properties": {}},
        status="draft",
        adapter="rpa",
        risk="external_action",
        confirmation=True,
        timeout=3600,
        blocked_reason="需先接入独立凭据保管和受控浏览器会话，禁止把账号密码写入任务参数。",
    ),
    "jdy-cashflow-reconcile": manifest(
        "jdy-cashflow-reconcile",
        "现金流量明细核对",
        "对账核对",
        "按现金流量项目和凭证号核对明细表与整合表并标记差异。",
        ["Excel", "现金流量", "凭证核对"],
        [],
        {"type": "object", "additionalProperties": True, "properties": {}},
        status="disabled",
        blocked_reason="现有实现缺少会计期间维度，同号凭证跨月时会错误合并，修复前禁止发布。",
    ),
    "task-clarifier": manifest(
        "task-clarifier",
        "财务任务澄清器",
        "基础能力",
        "通过对话补齐输入、口径、输出和风险边界的 Agent 指南。",
        ["Agent", "需求澄清"],
        [],
        {"type": "object", "additionalProperties": True, "properties": {}},
        status="disabled",
        blocked_reason="属于 Agent 行为指南，需要模型型执行适配器，不是独立 CLI。",
    ),
    "env-doctor": manifest(
        "env-doctor",
        "财务运行环境诊断",
        "基础能力",
        "检查 Python、Office、LibreOffice、依赖和目录条件的 Agent 指南。",
        ["环境诊断", "Agent"],
        [],
        {"type": "object", "additionalProperties": True, "properties": {}},
        status="disabled",
        blocked_reason="属于 Agent 行为指南，需要受控系统诊断适配器。",
    ),
    "xlsx": manifest(
        "xlsx",
        "Excel 基础能力",
        "文档能力",
        "Excel 创建、编辑、公式重算和视觉检查的 Agent 基础指南。",
        ["Excel", "基础能力"],
        [],
        {"type": "object", "additionalProperties": True, "properties": {}},
        status="disabled",
        blocked_reason="基础能力包不是单一业务工具，需要文档型 Agent 运行时。",
    ),
    "pdf": manifest(
        "pdf",
        "PDF 基础能力",
        "文档能力",
        "PDF 读取、表单填写、渲染和版面校验的 Agent 基础指南。",
        ["PDF", "基础能力"],
        [],
        {"type": "object", "additionalProperties": True, "properties": {}},
        status="disabled",
        blocked_reason="基础能力包不是单一业务工具，需要文档型 Agent 运行时。",
    ),
    "docx": manifest(
        "docx",
        "Word 基础能力",
        "文档能力",
        "Word 文档创建、修订、批注和版面验证的 Agent 基础指南。",
        ["Word", "基础能力"],
        [],
        {"type": "object", "additionalProperties": True, "properties": {}},
        status="disabled",
        blocked_reason="基础能力包不是单一业务工具，需要文档型 Agent 运行时。",
    ),
    "pptx": manifest(
        "pptx",
        "PowerPoint 基础能力",
        "文档能力",
        "演示文稿创建、编辑、缩略图检查和版式修复的 Agent 基础指南。",
        ["PPT", "基础能力"],
        [],
        {"type": "object", "additionalProperties": True, "properties": {}},
        status="disabled",
        blocked_reason="基础能力包不是单一业务工具，需要文档型 Agent 运行时。",
    ),
}


IGNORED_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "工作区",
    "tests",
    "evals",
    "agents",
    "node_modules",
}
ROOT_SUFFIXES = {".md", ".json", ".xlsx", ".xls", ".txt", ".csv", ".ps1", ".mjs"}
NORMALIZED_TEXT_SUFFIXES = {".md", ".json", ".txt", ".csv", ".yaml", ".yml"}


def normalize_text(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    normalized = "\n".join(line.rstrip() for line in text.splitlines())
    if text.endswith(("\n", "\r")):
        normalized += "\n"
    path.write_text(normalized, encoding="utf-8")


def safe_copy_source(source: Path, vendor: Path) -> None:
    vendor.mkdir(parents=True, exist_ok=True)
    for directory_name in ("scripts", "config", "references"):
        source_dir = source / directory_name
        if source_dir.is_dir():
            shutil.copytree(
                source_dir,
                vendor / directory_name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    ".pytest_cache",
                    "工作区",
                    "output",
                    "*.pyc",
                    "config.local.json",
                    "config.local.example.json",
                ),
            )
    for path in source.iterdir():
        if (
            path.is_file()
            and path.name not in {"SKILL.md", "README.md", "config.local.json"}
            and path.suffix.lower() in ROOT_SUFFIXES
        ):
            shutil.copy2(path, vendor / path.name)
    for path in vendor.rglob("*"):
        if path.is_file() and path.suffix.lower() in NORMALIZED_TEXT_SUFFIXES:
            normalize_text(path)


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def source_skill_name(source: Path) -> str:
    manifest = source / "SKILL.md"
    if not manifest.is_file():
        raise FileNotFoundError(f"源 Skill 缺少 SKILL.md：{source}")
    content = manifest.read_text(encoding="utf-8").replace("\r\n", "\n")
    parts = content.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(f"源 Skill 的 SKILL.md front matter 无效：{source}")
    payload = yaml.safe_load(parts[1]) or {}
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError(f"源 Skill 的 SKILL.md 缺少 name：{source}")
    return name


def sync_one(source_root: Path, skill_id: str, item: dict[str, Any], executable: bool) -> None:
    source = source_root / skill_id
    if not source.is_dir():
        raise FileNotFoundError(f"源 Skill 不存在：{source}")
    if source_skill_name(source) != skill_id:
        raise ValueError(f"源 Skill 的 name 与请求的 Skill ID 不一致：{skill_id}")
    target = (PLATFORM_SKILLS / skill_id).resolve()
    if not target.is_relative_to(PLATFORM_SKILLS.resolve()):
        raise RuntimeError(f"目标目录越界：{target}")
    if target.exists():
        shutil.rmtree(target)
    (target / "scripts").mkdir(parents=True)

    for name in ("SKILL.md", "README.md"):
        if (source / name).is_file():
            shutil.copy2(source / name, target / name)
            normalize_text(target / name)
    if executable or skill_id == "ar-hexiao-daily":
        safe_copy_source(source, target / "vendor")
    if skill_id == "ar-hexiao-daily":
        shutil.copy2(
            ZHIYUN_FETCH_TEMPLATE,
            target / "vendor" / "scripts" / "fetch_secure.py",
        )
    write_yaml(target / "tool.yaml", item["manifest"] if executable else item)
    if executable:
        shutil.copy2(BRIDGE_TEMPLATE, target / "scripts" / "entry.py")
        write_yaml(target / "bridge.yaml", item["bridge"])
    else:
        shutil.copy2(UNAVAILABLE_TEMPLATE, target / "scripts" / "entry.py")


def main() -> None:
    global PLATFORM_SKILLS
    parser = argparse.ArgumentParser(description="将 finance-skills 安全同步到平台 Skill Registry")
    parser.add_argument(
        "--source",
        type=Path,
        default=SOURCE_SKILLS,
        help="finance-skills/skills 目录；默认使用仓库内 sources/finance-skills/skills",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=PLATFORM_SKILLS,
        help="目标 Skill 目录；默认写入平台 skills，自动同步时可指定隔离暂存目录",
    )
    parser.add_argument(
        "--skill-id",
        action="append",
        default=[],
        help="只同步指定 Skill；可重复使用。未提供时同步全部。",
    )
    parser.add_argument("--repository-url", default="", help="已确认绑定的 Git 仓库地址")
    parser.add_argument("--source-path", default="", help="已确认绑定的仓库内 Skill 目录")
    parser.add_argument("--source-commit", default="", help="固定的 40 位 Git commit")
    parser.add_argument("--version", default="", help="本次平台发布版本")
    args = parser.parse_args()
    source_root = args.source.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    PLATFORM_SKILLS = args.target.resolve()
    PLATFORM_SKILLS.mkdir(parents=True, exist_ok=True)

    requested = set(args.skill_id)
    known = set(EXECUTABLES) | set(CATALOG_ONLY)
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError("未知 Skill：" + ", ".join(unknown))
    source_metadata = {
        "repository_url": args.repository_url.strip(),
        "source_path": args.source_path.strip().replace("\\", "/"),
        "source_commit": args.source_commit.strip().lower(),
        "version": args.version.strip(),
    }
    if any(source_metadata.values()):
        if len(requested) != 1 or not all(source_metadata.values()):
            raise ValueError("绑定来源参数必须完整提供，且一次只能同步一个 Skill。")
        selected = next(iter(requested))
        if source_metadata["repository_url"] != "https://gitee.com/Lee157/finance-skills.git":
            raise ValueError("仓库地址不是已配置的财务 Skill Gitee 仓库。")
        if source_metadata["source_path"] != f"skills/{selected}":
            raise ValueError("源码目录与请求的 Skill ID 不一致。")
        if not re.fullmatch(r"[0-9a-f]{40}", source_metadata["source_commit"]):
            raise ValueError("源码 commit 必须是 40 位小写十六进制。")
        if not re.fullmatch(
            r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", source_metadata["version"]
        ):
            raise ValueError("发布版本必须使用语义化版本格式。")
    executable_items = {
        key: value for key, value in EXECUTABLES.items() if not requested or key in requested
    }
    catalog_items = {
        key: value for key, value in CATALOG_ONLY.items() if not requested or key in requested
    }

    for skill_id, item in executable_items.items():
        sync_one(source_root, skill_id, item, True)
    skipped = []
    for skill_id, item in catalog_items.items():
        if not (source_root / skill_id).is_dir():
            skipped.append(skill_id)
            continue
        sync_one(source_root, skill_id, item, False)
    if source_metadata["repository_url"]:
        selected = next(iter(requested))
        manifest_path = PLATFORM_SKILLS / selected / "tool.yaml"
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        payload["version"] = source_metadata["version"]
        payload["upstream"] = {
            "repository": source_metadata["repository_url"],
            "path": source_metadata["source_path"],
            "commit": source_metadata["source_commit"],
        }
        write_yaml(manifest_path, payload)
    print(
        f"已同步 {len(executable_items)} 个可执行 Skill、"
        f"{len(catalog_items) - len(skipped)} 个目录级 Skill。"
    )
    if skipped:
        print("远端缺少目录级 Skill，已保留平台现有版本：" + ", ".join(skipped))


if __name__ == "__main__":
    main()
