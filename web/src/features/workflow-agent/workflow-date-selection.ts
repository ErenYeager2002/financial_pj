import { differenceInCalendarDays, format, startOfDay } from 'date-fns';

export interface WorkflowDateRangeSelection {
  dates: Date[];
  error: string;
}

export function workflowInitialDateSelectionKey(skillId: string, initialDates: string[]): string {
  return `${skillId}:${initialDates.join(',')}`;
}

export function workflowInitialDateSelection(
  initialDates: string[],
  skillId: string,
  initialSkillId: string,
  maximum: Date,
  appliedSelectionKey: string
): Date[] | null {
  if (skillId !== initialSkillId) return [];
  if (appliedSelectionKey === workflowInitialDateSelectionKey(initialSkillId, initialDates)) {
    return null;
  }
  return initialDates
    .map(workflowDateFromInput)
    .filter((item): item is Date => item !== null && item <= startOfDay(maximum));
}

export function workflowDateKey(value: Date): string {
  return format(startOfDay(value), 'yyyy-MM-dd');
}

export function addWorkflowDate(selected: Date[], target: Date, maximum: Date): Date[] {
  const checkedTarget = startOfDay(target);
  if (checkedTarget > startOfDay(maximum)) return selected;
  const key = workflowDateKey(checkedTarget);
  if (selected.some((item) => workflowDateKey(item) === key)) return selected;
  return [...selected, checkedTarget].toSorted((left, right) => left.getTime() - right.getTime());
}

export function toggleWorkflowDate(selected: Date[], target: Date, maximum: Date): Date[] {
  const checkedTarget = startOfDay(target);
  if (checkedTarget > startOfDay(maximum)) return selected;
  const key = workflowDateKey(checkedTarget);
  if (selected.some((item) => workflowDateKey(item) === key)) {
    return selected.filter((item) => workflowDateKey(item) !== key);
  }
  return addWorkflowDate(selected, checkedTarget, maximum);
}

export function workflowDateFromInput(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split('-').map(Number);
  const result = new Date(year, month - 1, day);
  return result.getFullYear() === year &&
    result.getMonth() === month - 1 &&
    result.getDate() === day
    ? startOfDay(result)
    : null;
}

export function workflowDateRangeSelection(
  startValue: string,
  endValue: string,
  maximum: Date
): WorkflowDateRangeSelection {
  if (!startValue && !endValue) return { dates: [], error: '' };
  if (!startValue || !endValue) {
    const single = workflowDateFromInput(startValue || endValue);
    if (!single) return { dates: [], error: '请输入有效的开始日期和结束日期。' };
    if (single > startOfDay(maximum)) {
      return { dates: [], error: '日期不能晚于今天。' };
    }
    return { dates: [single], error: '' };
  }
  const start = workflowDateFromInput(startValue);
  const end = workflowDateFromInput(endValue);
  if (!start || !end) return { dates: [], error: '请输入有效的开始日期和结束日期。' };
  if (start > end) return { dates: [], error: '开始日期不能晚于结束日期。' };
  if (end > startOfDay(maximum)) return { dates: [], error: '日期不能晚于今天。' };

  const dates: Date[] = [];
  let cursor = start;
  while (cursor <= end) {
    dates.push(cursor);
    cursor = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() + 1);
  }
  return { dates, error: '' };
}

export function workflowDateRangeSummary(selected: Date[]): {
  dateCount: number;
} {
  return { dateCount: selected.length };
}

export function validateWorkflowDateRange(selected: Date[]): string {
  if (selected.length <= 1) return '';
  const dates = selected
    .map((item) => startOfDay(item))
    .toSorted((left, right) => left.getTime() - right.getTime());
  const last = dates.at(-1) as Date;
  return differenceInCalendarDays(last, dates[0]) + 1 > 31
    ? '单个批次的最早日期到最晚日期跨度最多 31 个自然日。'
    : '';
}
