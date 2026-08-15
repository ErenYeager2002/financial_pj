import { mutationOptions } from '@tanstack/react-query';
import {
  confirmRun,
  confirmTaskDraft,
  createRun,
  deleteSkillFile,
  uploadSkillFile
} from './service';

export const uploadSkillFileMutation = mutationOptions({ mutationFn: uploadSkillFile });
export const deleteSkillFileMutation = mutationOptions({ mutationFn: deleteSkillFile });
export const createRunMutation = mutationOptions({ mutationFn: createRun });
export const confirmRunMutation = mutationOptions({ mutationFn: confirmRun });
export const confirmTaskDraftMutation = mutationOptions({ mutationFn: confirmTaskDraft });
