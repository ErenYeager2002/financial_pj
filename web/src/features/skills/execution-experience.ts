export type SkillClassification = 'foundation' | 'supporting' | 'business';

export type SkillExperienceFamily =
  | 'foundation'
  | 'workflow'
  | 'comparison'
  | 'workbook'
  | 'batch'
  | 'report'
  | 'advisory'
  | 'diagnostic'
  | 'conversation';

export interface SkillExecutionExperience {
  key: string;
  skillId: string;
  classification: SkillClassification;
  family: SkillExperienceFamily;
  creationTitle: string;
  purpose: string;
  inputHeading: string;
  inputHint: string;
  reviewTitle: string;
  reviewItems: string[];
  workerChecks: string[];
  resultHighlights: string[];
  fileRoleLabels?: Record<string, string>;
  parameterLabels?: Record<string, string>;
  orderedFileRole?: string;
  supportHref?: string;
}

const foundation = (skillId: string, creationTitle: string): SkillExecutionExperience => ({
  key: `foundation-${skillId}`,
  skillId,
  classification: 'foundation',
  family: 'foundation',
  creationTitle,
  purpose: '处理单个办公文件，并保留原始文件。',
  inputHeading: '选择文件',
  inputHint: '上传待处理文件，再按当前任务填写参数。',
  reviewTitle: '处理前核对',
  reviewItems: ['原始文件不会被覆盖', '结果会作为新的任务文件保存'],
  workerChecks: ['文件可读性和格式检查在任务执行时完成'],
  resultHighlights: ['处理后的文件', '执行说明']
});

const experiences: SkillExecutionExperience[] = [
  foundation('xlsx', '处理 Excel 文件'),
  foundation('docx', '处理 Word 文件'),
  foundation('pdf', '处理 PDF 文件'),
  foundation('pptx', '处理 PowerPoint 文件'),
  {
    key: 'support-env-doctor',
    skillId: 'env-doctor',
    classification: 'supporting',
    family: 'diagnostic',
    creationTitle: '检查运行环境',
    purpose: '检查平台运行环境和依赖状态，不创建普通财务任务。',
    inputHeading: '诊断范围',
    inputHint: '诊断页会按权限展示可执行的检查项。',
    reviewTitle: '诊断说明',
    reviewItems: ['不会执行财务写入', '敏感配置只返回是否已配置'],
    workerChecks: ['服务和依赖状态由诊断接口实时检查'],
    resultHighlights: ['检查状态', '修复建议'],
    supportHref: '/dashboard/overview#environment-health'
  },
  {
    key: 'support-task-clarifier',
    skillId: 'task-clarifier',
    classification: 'supporting',
    family: 'conversation',
    creationTitle: '说明要处理的财务任务',
    purpose: '通过对话补齐任务目标、文件和限制，再生成可核对的任务草稿。',
    inputHeading: '任务说明',
    inputHint: '在 AI 助手中描述目标并附上已有文件。',
    reviewTitle: '草稿核对',
    reviewItems: ['生成草稿后仍需核对文件和参数', '对话不会绕过执行权限'],
    workerChecks: ['具体 Skill 的输入检查在对应执行体验中完成'],
    resultHighlights: ['结构化任务草稿'],
    supportHref: '/dashboard/ai-chat'
  },
  {
    key: 'workflow-ar-hexiao-daily',
    skillId: 'ar-hexiao-daily',
    classification: 'business',
    family: 'workflow',
    creationTitle: '创建应收核销任务',
    purpose: '按核销日期准备材料、检查智云数据并执行日清流程。',
    inputHeading: '核销范围与材料',
    inputHint: '该 Skill 使用分阶段工作流，并支持单日和连续日期批次。',
    reviewTitle: '执行前检查',
    reviewItems: ['核销日期和工作副本', '智云取数结果', '写前校验结果'],
    workerChecks: ['实际写入仍受部署开关和后端安全策略限制'],
    resultHighlights: ['核销日清', '差异报告', '工作副本写入结果']
  },
  {
    key: 'bank-reconciliation',
    skillId: 'reconcile-bank',
    classification: 'business',
    family: 'comparison',
    creationTitle: '核对银行流水与财务总账',
    purpose: '按金额和日期容差逐笔匹配两份账表，并列出双方未匹配记录。',
    inputHeading: '两侧对账材料',
    inputHint: '左侧上传银行流水，右侧上传财务总账。参考号缺失不会阻止对账。',
    reviewTitle: '匹配规则',
    reviewItems: [
      '确认银行流水和财务总账没有传反',
      '确认金额容差和日期容差符合本次口径',
      '多条候选会按日期差、金额差和原始行号选择'
    ],
    workerChecks: ['日期列和金额列识别', '有效记录和跳过记录统计', '匹配与未匹配数量'],
    resultHighlights: ['匹配明细', '银行未匹配', '总账未匹配'],
    fileRoleLabels: { bank_file: '银行流水', ledger_file: '财务总账' },
    parameterLabels: { amount_tolerance: '金额容差', date_tolerance_days: '日期容差天数' }
  },
  {
    key: 'labor-invoice-reconciliation',
    skillId: 'labor-invoice-check',
    classification: 'business',
    family: 'comparison',
    creationTitle: '核对劳务清单与发票台账',
    purpose: '按证件号优先、姓名兜底的规则核对开票和付款条件。',
    inputHeading: '人员清单与发票台账',
    inputHint: '材料可能包含个人敏感信息，页面只展示文件名和脱敏统计。',
    reviewTitle: '核对口径',
    reviewItems: [
      '开票门槛和金额容差使用当前业务规则',
      '实习生和外国人按规则豁免',
      '公司和对公记录进入人工复核'
    ],
    workerChecks: ['关键列识别', '清单人数和发票记录数', '无效金额和待人工数量'],
    resultHighlights: ['主核对表', '催票名单', '可付名单', '运行报告'],
    fileRoleLabels: { labor_list: '劳务清单', invoice_ledger: '发票台账' }
  },
  {
    key: 'project-detail-supplement',
    skillId: 'project-detail-to-ledger',
    classification: 'business',
    family: 'workbook',
    creationTitle: '把项目明细补入盈亏核算表',
    purpose: '识别项目明细与目标工作簿，按 SO 和 SOD 去重后生成新的核算表副本。',
    inputHeading: '来源与目标工作簿',
    inputHint: '项目明细是来源，盈亏核算表是目标模板。平台不会覆盖上传原件。',
    reviewTitle: '补录前核对',
    reviewItems: [
      '确认两份工作簿角色正确',
      '重复的 SO 和 SOD 组合会跳过',
      '结果写入新副本，不修改原件'
    ],
    workerChecks: ['目标 Sheet 和必需字段识别', '预计新增与重复数量', '数字转换和输出结构校验'],
    resultHighlights: ['补录结果工作簿', '补录报告', '新增和跳过统计'],
    fileRoleLabels: { project_detail: '项目明细表', ledger: '盈亏核算表' }
  },
  {
    key: 'receivables-consolidation',
    skillId: 'receivables-merge',
    classification: 'business',
    family: 'workbook',
    creationTitle: '合并本期应收账款',
    purpose: '合并年度数据、计算账龄、回填历史标注并生成完整和权限隔离结果。',
    inputHeading: '本期台账与上一版应收 all',
    inputHint: '非首次建表应提供上一版应收 all，用于标注回填和老坏账结转。',
    reviewTitle: '合并口径',
    reviewItems: ['确认本周销售归属是否变化', '确认账龄基准月', '确认本期源台账和上一版文件角色'],
    workerChecks: ['年度 Sheet 和关键列', '销售归属及名称变体', '未匹配、离职残留和年度一致性'],
    resultHighlights: ['完整版应收 all', '领导部分版', '归属与未匹配复核'],
    fileRoleLabels: { source: '本期应收源台账', reference: '上一版应收 all' },
    parameterLabels: { base_month: '账龄基准月' }
  },
  {
    key: 'department-expense-allocation',
    skillId: 'dept-expense-alloc',
    classification: 'business',
    family: 'workbook',
    creationTitle: '归集并分摊部门费用',
    purpose: '盘点费用材料，按人员、收入和科目规则形成部门科目余额及利润表。',
    inputHeading: '本次分摊材料包',
    inputHint: '至少应包含主体余额、人员归属和收入底稿，其他费用明细按本期情况补充。',
    reviewTitle: '材料与核对要求',
    reviewItems: ['关键材料必须齐全', '人员和科目未匹配需要先处理', '分摊结果必须在配置容差内'],
    workerChecks: ['材料角色和主体识别', '人员映射与未匹配统计', '主体合计和部门合计核对'],
    resultHighlights: ['部门科目余额表', '利润表', '运行报告'],
    fileRoleLabels: { materials: '费用分摊材料' }
  },
  {
    key: 'receivables-sales-split',
    skillId: 'split-by-sales',
    classification: 'business',
    family: 'batch',
    creationTitle: '按销售人员拆分应收 all',
    purpose: '按销售人员和接手规则生成独立工作簿，并打包为一个 ZIP。',
    inputHeading: '应收 all 与文件日期',
    inputHint: '日期会用于结果文件命名。无法从文件名识别时，请明确填写月日。',
    reviewTitle: '拆分规则',
    reviewItems: [
      '确认数据 Sheet 和日期标签',
      '空销售记录会单独生成待人工文件',
      '拆分后会核对输入行数与分出行数'
    ],
    workerChecks: ['目标列和销售人员识别', '忽略桶和接手规则', '拆分数量对账'],
    resultHighlights: ['销售人员工作簿 ZIP', '空销售待人工文件', '拆分对账统计'],
    fileRoleLabels: { receivables: '应收 all' },
    parameterLabels: { date_label: '结果文件日期' }
  },
  {
    key: 'withholding-report-batch-rename',
    skillId: 'withholding-report-rename',
    classification: 'business',
    family: 'batch',
    creationTitle: '整理代扣代缴申报表文件名',
    purpose: '批量识别申报表 PDF，并在保留原件的前提下生成规范命名副本。',
    inputHeading: '申报表 PDF',
    inputHint: '可一次上传多份 PDF。任务使用复制模式，不会修改上传原件。',
    reviewTitle: '批量整理说明',
    reviewItems: ['核对待处理 PDF 清单', '原始文件保持不变', '规范命名副本统一打包下载'],
    workerChecks: ['PDF 可读性和申报表信息识别', '重名和待人工确认情况'],
    resultHighlights: ['重命名结果 ZIP'],
    fileRoleLabels: { reports: '申报表 PDF' }
  },
  {
    key: 'dreame-ar-version-comparison',
    skillId: 'dreame-ar-progress-diff',
    classification: 'business',
    family: 'comparison',
    creationTitle: '比较追觅应收进度版本',
    purpose: '按旧到新的顺序比较数值、底色、预计付款备注和列结构变化。',
    inputHeading: '版本时间线',
    inputHint: '至少上传两份文件，并确认顺序从旧版到最新版。',
    reviewTitle: '对比方向',
    reviewItems: ['第一份作为旧版基线', '最后一份作为最新版', '文件顺序会直接决定变化方向'],
    workerChecks: ['期间并集和人员对齐', '值变化、颜色变化和列结构变化', '对齐存疑项'],
    resultHighlights: ['值变化', '颜色变化', '追觅应收进度对比报告'],
    fileRoleLabels: { versions: '应收进度版本' },
    orderedFileRole: 'versions'
  },
  {
    key: 'offline-order-daily-summary',
    skillId: 'order-daily-summary',
    classification: 'business',
    family: 'report',
    creationTitle: '生成九点下单统计',
    purpose: '使用九点导出的离线下单明细，按统计基准日生成汇总结果。',
    inputHeading: '离线下单明细',
    inputHint: '平台不会登录智云。请先从九点导出目标范围的下单明细。',
    reviewTitle: '统计范围',
    reviewItems: ['确认统计基准日', '确认是否对上传数据再次按日期过滤', '确认报告是否包含订单明细'],
    workerChecks: ['日期范围和有效订单', '部门汇总和未匹配销售', '断档提示'],
    resultHighlights: ['九点下单统计 ZIP', '汇总和可选明细'],
    fileRoleLabels: { orders: '九点下单明细' },
    parameterLabels: {
      today: '统计基准日',
      include_detail: '报告包含订单明细',
      no_date_filter: '直接统计上传表全部行'
    }
  },
  {
    key: 'compliance-sampling-advice',
    skillId: 'compliance-spot-check',
    classification: 'business',
    family: 'advisory',
    creationTitle: '生成本周合规抽查建议',
    purpose: '依据应收账龄、金额、销售覆盖和历史反馈生成内部抽查建议。',
    inputHeading: '应收数据与抽查历史',
    inputHint: '历史文件可用于排除已处理记录并提高未反馈记录优先级。',
    reviewTitle: '建议口径',
    reviewItems: [
      '核对当前应收 all 和可选历史文件',
      '结果仅为抽查建议，最终对象由人工决定',
      '不会自动发邮件或判断合同是否合规'
    ],
    workerChecks: [
      '必要列、有效订单和销售人数',
      '历史文件有效记录和反馈状态',
      '抽样上限与销售覆盖'
    ],
    resultHighlights: ['本周抽查建议 Excel', '建议文本', '覆盖与无候选提示'],
    fileRoleLabels: { receivables: '应收 all', history: '抽查历史' }
  }
];

const registry = new Map(experiences.map((experience) => [experience.skillId, experience]));

export function executionExperienceForSkill(skillId: string): SkillExecutionExperience | null {
  return registry.get(skillId) ?? null;
}

export function registeredBusinessSkillIds(): string[] {
  return experiences
    .filter((experience) => experience.classification === 'business')
    .map((experience) => experience.skillId);
}

export function isFoundationSkill(skillId: string): boolean {
  return registry.get(skillId)?.classification === 'foundation';
}
