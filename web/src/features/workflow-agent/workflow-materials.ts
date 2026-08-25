import type { WorkflowReusableFilesRead } from '@/features/platform-api/types';

export type WorkflowMaterialFile = {
  id: string;
  name: string;
  source: 'saved' | 'uploaded';
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
      return fileId ? [{ id: fileId, name, source: 'saved' }] : [];
    });
    if (entries.length) selection[role] = entries;
  }
  return selection;
}

export function selectedMaterialIds(
  materials: Record<string, WorkflowMaterialFile[]>
): Record<string, string[]> {
  return Object.fromEntries(
    Object.entries(materials).map(([role, entries]) => [role, entries.map((item) => item.id)])
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
