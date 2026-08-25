export function taskReminderWorkflowHref(skillId: string, dates: string[]): string {
  const params = new URLSearchParams();
  params.set('skill', skillId);
  for (const date of dates) params.append('date', date);
  params.set('reminder', '1');
  return `/dashboard/workflows?${params.toString()}`;
}

export function actionableReminderDates(
  reminders: Array<{ business_date: string; state: string }>
): string[] {
  return reminders
    .filter((item) => item.state === 'pending' || item.state === 'reopened')
    .map((item) => item.business_date);
}
