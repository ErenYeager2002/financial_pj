import { isArSkill } from '@/features/workflow-agent/ar-skill-identity';

export type TaskCenterEmptyState = {
  title: string;
  description: string;
  action: string;
};

const TYPE_LABELS: Record<string, string> = {
  run: '普通任务',
  workflow: '日期任务',
  workflow_batch: '批次任务'
};

const STATE_LABELS: Record<string, string> = {
  pending: '待处理',
  running: '执行中',
  failed: '失败',
  succeeded: '已完成',
  cancelled: '已取消'
};

export function taskCenterTypeLabel(referenceType: string, skillId: string): string {
  if (isArSkill(skillId)) {
    return referenceType === 'workflow_batch' ? '应收核销批次' : '应收核销日期';
  }
  return TYPE_LABELS[referenceType] ?? '任务';
}

export function taskCenterStateLabel(viewState: string): string {
  return STATE_LABELS[viewState] ?? '状态待确认';
}

export function taskCenterActionLabel(viewState: string): string {
  if (viewState === 'pending') return '继续处理';
  if (viewState === 'running') return '查看进度';
  if (viewState === 'failed') return '查看失败原因';
  if (viewState === 'succeeded') return '查看结果';
  return '查看详情';
}

export function taskCenterResultAnnouncement(
  itemCount: number,
  total: number,
  page: number
): string {
  return `第 ${page} 页显示 ${itemCount} 条任务，共 ${total} 条任务。`;
}

export function taskCenterEmptyState(hasAnyTasks: boolean): TaskCenterEmptyState {
  if (!hasAnyTasks) {
    return {
      title: '暂无正式任务',
      description: '从 Skill 目录选择已开放的能力并创建任务。',
      action: '创建任务'
    };
  }
  return {
    title: '当前页没有任务',
    description: '任务页码可能已经变化，请返回第一页查看。',
    action: '返回第一页'
  };
}
