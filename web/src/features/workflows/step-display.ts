const STEP_TYPE_LABELS: Readonly<Record<string, string>> = {
  parameter_validation: '参数校验',
  file_validation: '文件校验',
  read_only_http: '只读 HTTP',
  python: 'Python 执行',
  rpa: 'RPA 执行',
  result_preview: '结果预览',
  human_confirmation: '人工确认',
  admin_approval: '管理员审批',
  controlled_write: '受控写入',
  post_write_verification: '写后复核',
  artifact_archive: '产物归档'
};

export function stepTypeLabel(stepType: string): string {
  return STEP_TYPE_LABELS[stepType] ?? stepType;
}
