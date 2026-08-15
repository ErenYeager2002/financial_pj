interface RunnableSkill {
  status?: string;
  execution_mode?: string;
  risk?: {
    level?: string;
    modifies_uploaded_files?: boolean;
  };
}

export function isRunnableSkill(skill: RunnableSkill): boolean {
  return (
    skill.status === 'published' &&
    skill.execution_mode === 'standard' &&
    skill.risk?.level === 'read_only' &&
    skill.risk.modifies_uploaded_files !== true
  );
}
