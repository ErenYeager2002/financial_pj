import type { SkillDetail } from '@/features/platform-api/types';

export interface SafeSkill {
  id: string;
  name: string;
  description: string;
  version: string;
  input_schema: Record<string, unknown>;
  file_inputs: SkillDetail['file_inputs'];
}

export function safeCatalog(skills: SkillDetail[]): SafeSkill[] {
  return skills
    .filter(
      (skill) =>
        skill.status === 'published' &&
        skill.execution_mode === 'standard' &&
        skill.risk.level === 'read_only' &&
        !skill.risk.modifies_uploaded_files
    )
    .map((skill) => ({
      id: skill.id,
      name: skill.name,
      description: skill.description,
      version: skill.version,
      input_schema: skill.input_schema ?? {},
      file_inputs: skill.file_inputs ?? []
    }));
}
