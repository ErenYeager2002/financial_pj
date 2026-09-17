import type { WorkflowReusableFilesRead } from '@/features/platform-api/types';

export type WorkflowMaterialFile = {
  id: string;
  name: string;
  source: 'saved' | 'uploaded';
  selected?: boolean;
  candidate?: boolean;
  year?: number;
};

export function reusableMaterialSelection(
  response: WorkflowReusableFilesRead | null,
  skillId: string
): Record<string, WorkflowMaterialFile[]> {
  if (!response || response.skill_id !== skillId) return {};
  const selection: Record<string, WorkflowMaterialFile[]> = {};
  for (const [role, rawEntries] of Object.entries(response.files ?? {})) {
    if (!Array.isArray(rawEntries)) continue;
    const entries = rawEntries.flatMap((entry): WorkflowMaterialFile[] => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return [];
      const fileId = 'file_id' in entry && typeof entry.file_id === 'string' ? entry.file_id : '';
      const name = 'name' in entry && typeof entry.name === 'string' ? entry.name : '已保存文件';
      return fileId ? [{ id: fileId, name, source: 'saved',
        ...('selected' in entry && typeof entry.selected === 'boolean' ? { selected: entry.selected, candidate: entry.selected === false } : {}),
        ...('year' in entry && typeof entry.year === 'number' ? { year: entry.year } : {})
      }] : [];
    });
    if (entries.length) selection[role] = entries;
  }
  return selection;
}

export function selectedMaterialIds(
  materials: Record<string, WorkflowMaterialFile[]>
): Record<string, string[]> {
  return Object.fromEntries(
    Object.entries(materials).map(([role, entries]) => [role, entries.filter((item) => item.selected !== false).map((item) => item.id)])
  );
}

export function selectedMaterialUpdates(
  materials: Record<string, WorkflowMaterialFile[]>,
  dirtyRoles: ReadonlySet<string>
): { files: Record<string, string[]>; replace_roles: string[] } {
  const selected = selectedMaterialIds(materials);
  const replaceRoles = [...dirtyRoles].toSorted();
  return {
    files: Object.fromEntries(replaceRoles.map((role) => [role, selected[role] ?? []])),
    replace_roles: replaceRoles
  };
}

export function materialYear(file: Pick<WorkflowMaterialFile, 'name' | 'year'>): number | undefined {
  if (file.year && Number.isInteger(file.year)) return file.year;
  const years = [...file.name.matchAll(/(?<!\d)((?:19|20)\d{2})(?!\d)/g)].map((match) => Number(match[1]));
  const unique = [...new Set(years)];
  return unique.length === 1 ? unique[0] : undefined;
}

export function materialGroups(role: string, entries: WorkflowMaterialFile[]): [string, WorkflowMaterialFile[]][] {
  if (role !== 'profit_loss_ledgers') return [['到账流转表（选一份）', entries]];
  const groups = new Map<string, WorkflowMaterialFile[]>();
  for (const file of entries) {
    const year = materialYear(file);
    const label = year ? `${year} 年（最多选一份）` : '年份未识别（文件名需包含四位年份）';
    groups.set(label, [...(groups.get(label) ?? []), file]);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export function toggleMaterialSelection(role: string, entries: WorkflowMaterialFile[], id: string): WorkflowMaterialFile[] {
  const target = entries.find((file) => file.id === id);
  if (!target || (role === 'profit_loss_ledgers' && !materialYear(target))) return entries;
  const selected = target.selected === false;
  return entries.map((file) => {
    if (file.id === id) return { ...file, selected };
    const sameGroup = role !== 'profit_loss_ledgers' || materialYear(file) === materialYear(target);
    return selected && sameGroup ? { ...file, selected: false } : file;
  });
}

export function validateMaterialSelection(materials: Record<string, WorkflowMaterialFile[]>): string {
  const ledgers = (materials.profit_loss_ledgers ?? []).filter((file) => file.selected !== false);
  const flows = (materials.receipt_flow_table ?? []).filter((file) => file.selected !== false);
  if (!ledgers.length) return '请至少勾选一份盈亏核算表。';
  const years = ledgers.map(materialYear);
  if (years.some((year) => !year)) return '盈亏核算表年份不明确，请使用包含四位年份的文件名重新上传。';
  if (new Set(years).size !== years.length) return '同一年只能选一份盈亏核算表。';
  if (flows.length !== 1) return '请勾选一份到账流转表。';
  return '';
}
