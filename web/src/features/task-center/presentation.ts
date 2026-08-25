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
  if (skillId === 'ar-hexiao-daily') {
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
  page: number,
  queryContext: string
): string {
  return `${queryContext}。第 ${page} 页显示 ${itemCount} 条任务，共 ${total} 条匹配结果。`;
}

export function taskCenterQueryContext(query: TaskCenterQuery): string {
  const filters = [
    query.state ? `状态 ${taskCenterStateLabel(query.state)}` : '',
    query.type ? `类型 ${TYPE_LABELS[query.type] ?? '任务'}` : '',
    query.skill ? `Skill ${query.skill}` : '',
    query.businessFrom ? `业务日期从 ${query.businessFrom}` : '',
    query.businessTo ? `业务日期到 ${query.businessTo}` : '',
    query.updatedFrom ? `更新时间从 ${query.updatedFrom}` : '',
    query.updatedTo ? `更新时间到 ${query.updatedTo}` : ''
  ].filter(Boolean);
  return filters.length ? filters.join('，') : '全部任务';
}

export function taskCenterEmptyState(
  hasAnyTasks: boolean,
  hasFilters: boolean
): TaskCenterEmptyState {
  if (hasAnyTasks && hasFilters) {
    return {
      title: '当前筛选没有匹配任务',
      description: '调整筛选条件，或清除筛选查看全部正式任务。',
      action: '清除筛选'
    };
  }
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
import type { TaskCenterQuery } from './query.ts';
