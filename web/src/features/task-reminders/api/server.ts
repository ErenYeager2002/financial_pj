import 'server-only';

import { platformServerRequest } from '@/features/platform-api/server-client';
import type {
  TaskDiscoveryCheckQueued,
  TaskDiscoveryCheckRequest,
  TaskReminderBoard,
  TaskReminderSubscription,
  TaskReminderSubscriptionWrite,
  ServiceCredentialRead
} from '@/features/platform-api/types';

export function getTaskReminderBoard(): Promise<TaskReminderBoard> {
  return platformServerRequest<TaskReminderBoard>('/api/task-reminders');
}

export function queueTaskDiscoveryCheck(
  body: TaskDiscoveryCheckRequest
): Promise<TaskDiscoveryCheckQueued> {
  return platformServerRequest<TaskDiscoveryCheckQueued>('/api/task-reminders/checks', {
    method: 'POST',
    body: JSON.stringify(body)
  });
}

export function retryTaskDiscoveryCheck(checkId: string): Promise<TaskDiscoveryCheckQueued> {
  return platformServerRequest<TaskDiscoveryCheckQueued>(
    `/api/task-reminders/checks/${encodeURIComponent(checkId)}/retry`,
    { method: 'POST' }
  );
}

export function getTaskReminderSubscription(skillId: string): Promise<TaskReminderSubscription> {
  return platformServerRequest<TaskReminderSubscription>(
    `/api/admin/task-reminder-subscriptions/${encodeURIComponent(skillId)}`
  );
}

export function saveTaskReminderSubscription(
  skillId: string,
  body: TaskReminderSubscriptionWrite
): Promise<TaskReminderSubscription> {
  return platformServerRequest<TaskReminderSubscription>(
    `/api/admin/task-reminder-subscriptions/${encodeURIComponent(skillId)}`,
    { method: 'PUT', body: JSON.stringify(body) }
  );
}

export function getTaskReminderOwnerCredential(skillId: string): Promise<ServiceCredentialRead> {
  return platformServerRequest<ServiceCredentialRead>(
    `/api/admin/task-reminder-subscriptions/${encodeURIComponent(skillId)}/credential`
  );
}

export function saveTaskReminderOwnerCredential(
  skillId: string,
  body: { account: string; password: string }
): Promise<ServiceCredentialRead> {
  return platformServerRequest<ServiceCredentialRead>(
    `/api/admin/task-reminder-subscriptions/${encodeURIComponent(skillId)}/credential`,
    { method: 'PUT', body: JSON.stringify(body) }
  );
}

export function deleteTaskReminderOwnerCredential(skillId: string): Promise<void> {
  return platformServerRequest<void>(
    `/api/admin/task-reminder-subscriptions/${encodeURIComponent(skillId)}/credential`,
    { method: 'DELETE' }
  );
}
