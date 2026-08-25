export type TaskReminderBoardMode = 'idle' | 'pending' | 'failure';

export type TaskReminderBoardVisibility = {
  mode: TaskReminderBoardMode;
  showIdle: boolean;
  showPending: boolean;
  showFailures: boolean;
};

export function taskReminderBoardMode(
  reminders: ReadonlyArray<unknown>,
  failures: ReadonlyArray<unknown>
): TaskReminderBoardMode {
  if (reminders.length) return 'pending';
  if (failures.length) return 'failure';
  return 'idle';
}

export function taskReminderBoardVisibility(
  reminders: ReadonlyArray<unknown>,
  failures: ReadonlyArray<unknown>
): TaskReminderBoardVisibility {
  const mode = taskReminderBoardMode(reminders, failures);
  return {
    mode,
    showIdle: mode === 'idle',
    showPending: reminders.length > 0,
    showFailures: failures.length > 0
  };
}

function localDateValue(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function manualCheckDateBounds(today = new Date()): { min: string; max: string } {
  const min = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 31);
  const max = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  return { min: localDateValue(min), max: localDateValue(max) };
}
