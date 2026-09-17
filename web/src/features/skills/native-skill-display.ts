type NativeSkillDisplay = { name: string; description: string };

// Presentation only: keys remain the repository directory and execution identifiers.
const DISPLAY: Readonly<Record<string, NativeSkillDisplay>> = {
  "ar-hexiao-daily": {
    "name": "应收核销日清",
    "description": "按回款核对应收，生成核销清单和结果。"
  },
  "compliance-spot-check": {
    "name": "合规抽查建议",
    "description": "根据应收台账生成本周合规抽查名单。"
  },
  "consolidated-statements": {
    "name": "合并报表",
    "description": "汇总多主体财务报表，生成合并结果。"
  },
  "dept-expense-alloc": {
    "name": "部门费用归集分摊",
    "description": "将费用归集到部门，生成费用表和利润表。"
  },
  "docx": {
    "name": "Word 文档处理",
    "description": "创建、编辑和检查 Word 文档。"
  },
  "dreame-ar-progress-diff": {
    "name": "追觅应收进度对比",
    "description": "对比不同版本的应收数据，标记进度变化。"
  },
  "kingdee-gl-import": {
    "name": "序时账转金蝶凭证",
    "description": "将序时账转换为金蝶凭证引入表。"
  },
  "kingdee-posting": {
    "name": "金蝶入账制表",
    "description": "根据发票、付款或收款材料生成凭证引入表。"
  },
  "labor-invoice-check": {
    "name": "劳务发票核对",
    "description": "按人员核对劳务费用与发票，生成月度统计。"
  },
  "order-daily-summary": {
    "name": "九点下单统计",
    "description": "汇总下单数据，生成每日统计表。"
  },
  "pdf": {
    "name": "PDF 文件处理",
    "description": "读取、编辑、合并和整理 PDF 文件。"
  },
  "pl-dept-report": {
    "name": "月度损益与利润表",
    "description": "汇总各主体和部门数据，生成月度损益与利润表。"
  },
  "pptx": {
    "name": "演示文稿处理",
    "description": "创建、编辑和检查 PowerPoint 演示文稿。"
  },
  "project-detail-to-ledger": {
    "name": "项目明细补录",
    "description": "将项目明细补入盈亏核算表，保留原件。"
  },
  "receivables-merge": {
    "name": "应收账款合并",
    "description": "合并应收台账，生成透视汇总和催收参考。"
  },
  "split-by-sales": {
    "name": "应收按销售拆分",
    "description": "按销售拆分应收台账，保留反馈字段并核对总额。"
  },
  "withholding-report-rename": {
    "name": "代扣代缴报告表重命名",
    "description": "按公司名和金额批量重命名申报表 PDF。"
  },
  "xlsx": {
    "name": "Excel 表格处理",
    "description": "创建、编辑、分析和检查 Excel 工作簿。"
  }
};

export function nativeSkillDisplay(id: string, name = id, description = ''): NativeSkillDisplay {
  const key = id.startsWith('native--') ? id.slice(8) : id;
  if (Object.hasOwn(DISPLAY, key)) return DISPLAY[key];
  const sentence = description.replace(/\s+/g, ' ').trim().split(/[。！？]/u)[0];
  return { name, description: sentence ? sentence.slice(0, 48) + (sentence.length > 48 ? '…' : '。') : '按 Skill 说明处理上传的材料。' };
}
