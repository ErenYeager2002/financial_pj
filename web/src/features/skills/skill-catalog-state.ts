import type { SkillDedication, SkillSummary } from '@/features/platform-api/types';
import { executionExperienceForSkill } from './execution-experience';

export type SkillRiskFilter = 'all' | SkillSummary['risk']['level'];

export interface SkillCatalogFilters {
  query: string;
  category: string;
  risk: SkillRiskFilter;
  popularOnly: boolean;
  dedicationUserId: string;
}

export interface SkillCatalogDedicationOption {
  userId: string;
  displayName: string;
  disabled: boolean;
}

export type SkillCatalogAction =
  | { kind: 'workflow' | 'run' | 'supporting'; href: string; label: string }
  | { kind: 'unavailable'; href: null; label: '暂不可运行' };

export const DEFAULT_SKILL_CATALOG_FILTERS: SkillCatalogFilters = {
  query: '',
  category: '',
  risk: 'all',
  popularOnly: false,
  dedicationUserId: ''
};

const RISK_LABELS: Record<SkillSummary['risk']['level'], string> = {
  read_only: '只读',
  write: '写入操作',
  external_action: '外部操作'
};

export function normalizeSkillCatalogQuery(value: string): string {
  return value.trim().toLocaleLowerCase('zh-CN');
}

export function skillRiskLabels(skill: Pick<SkillSummary, 'id' | 'risk'>): string[] {
  const labels = [RISK_LABELS[skill.risk.level]];
  if (skill.risk.requires_confirmation) labels.push('需要确认');
  // ar-hexiao-daily follows the current controlled auto-write path after its
  // pre-write checks; it does not enter an administrator approval stage.
  if (skill.risk.requires_approval && skill.id !== 'ar-hexiao-daily') labels.push('需要审批');
  return labels;
}

export function skillCatalogCategories(skills: readonly SkillSummary[]): string[] {
  return Array.from(new Set(skills.flatMap((skill) => skill.categories))).toSorted((left, right) =>
    left.localeCompare(right, 'zh-CN')
  );
}

export function skillCatalogDedicationOptions(
  dedications?: Record<string, SkillDedication>
): SkillCatalogDedicationOption[] {
  const unique = new Map<string, SkillCatalogDedicationOption>();
  for (const dedication of Object.values(dedications ?? {})) {
    unique.set(dedication.user_id, {
      userId: dedication.user_id,
      displayName: dedication.user_display_name,
      disabled: dedication.user_status === 'disabled'
    });
  }
  return Array.from(unique.values()).toSorted((left, right) =>
    left.displayName.localeCompare(right.displayName, 'zh-CN')
  );
}

function skillSearchValues(skill: SkillSummary): string[] {
  return [
    skill.name,
    skill.description,
    ...(skill.tags ?? []),
    ...skill.categories,
    ...skill.operation_labels
  ];
}

export function filterSkillCatalog(
  skills: readonly SkillSummary[],
  filters: SkillCatalogFilters,
  dedications?: Record<string, SkillDedication>
): SkillSummary[] {
  const query = normalizeSkillCatalogQuery(filters.query);
  return skills.filter((skill) => {
    const matchesQuery =
      !query ||
      skillSearchValues(skill).some((value) =>
        value.toLocaleLowerCase('zh-CN').includes(query)
      );
    const matchesCategory = !filters.category || skill.categories.includes(filters.category);
    const matchesRisk = filters.risk === 'all' || skill.risk.level === filters.risk;
    const matchesPopular = !filters.popularOnly || skill.popular;
    const matchesDedication =
      !filters.dedicationUserId ||
      dedications?.[skill.id]?.user_id === filters.dedicationUserId;
    return matchesQuery && matchesCategory && matchesRisk && matchesPopular && matchesDedication;
  });
}

function categorySortValue(skill: SkillSummary): string {
  return [...skill.categories]
    .toSorted((left, right) => left.localeCompare(right, 'zh-CN'))
    .join('\u0000');
}

export function sortSkillCatalog(skills: readonly SkillSummary[]): SkillSummary[] {
  return [...skills].toSorted((left, right) => {
    if (left.popular !== right.popular) return left.popular ? -1 : 1;
    const categoryOrder = categorySortValue(left).localeCompare(
      categorySortValue(right),
      'zh-CN'
    );
    if (categoryOrder !== 0) return categoryOrder;
    const nameOrder = left.name.localeCompare(right.name, 'zh-CN');
    return nameOrder !== 0 ? nameOrder : left.id.localeCompare(right.id, 'en');
  });
}

export function filterAndSortSkillCatalog(
  skills: readonly SkillSummary[],
  filters: SkillCatalogFilters,
  dedications?: Record<string, SkillDedication>
): SkillSummary[] {
  return sortSkillCatalog(filterSkillCatalog(skills, filters, dedications));
}

export function clearSkillCatalogFilters(): SkillCatalogFilters {
  return { ...DEFAULT_SKILL_CATALOG_FILTERS };
}

export function hasSkillCatalogFilters(filters: SkillCatalogFilters): boolean {
  return Boolean(
    normalizeSkillCatalogQuery(filters.query) ||
      filters.category ||
      filters.risk !== 'all' ||
      filters.popularOnly ||
      filters.dedicationUserId
  );
}

export function skillCatalogDetailHref(skillId: string): string {
  return `/dashboard/skills/${encodeURIComponent(skillId)}`;
}

export function skillCatalogActionFor(
  skill: Pick<SkillSummary, 'id' | 'action_label' | 'execution_mode'>
): SkillCatalogAction {
  const experience = executionExperienceForSkill(skill.id);
  if (!experience) return { kind: 'unavailable', href: null, label: '暂不可运行' };

  if (skill.execution_mode === 'guided_workflow' || experience.family === 'workflow') {
    return {
      kind: 'workflow',
      href: `/dashboard/workflows?skill=${encodeURIComponent(skill.id)}`,
      label: skill.action_label
    };
  }

  if (experience.classification === 'supporting') {
    return experience.supportHref
      ? { kind: 'supporting', href: experience.supportHref, label: skill.action_label }
      : { kind: 'unavailable', href: null, label: '暂不可运行' };
  }

  return {
    kind: 'run',
    href: `/dashboard/skills/${encodeURIComponent(skill.id)}/run`,
    label: skill.action_label
  };
}
