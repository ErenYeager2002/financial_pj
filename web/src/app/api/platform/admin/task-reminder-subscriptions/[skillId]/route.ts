import { NextResponse } from 'next/server';
import {
  getTaskReminderSubscription,
  saveTaskReminderSubscription
} from '@/features/task-reminders/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET(_request: Request, { params }: { params: Promise<{ skillId: string }> }) {
  try {
    return NextResponse.json(await getTaskReminderSubscription((await params).skillId));
  } catch (error) {
    return platformRouteError(error, '任务提醒负责人加载失败。');
  }
}

export async function PUT(request: Request, { params }: { params: Promise<{ skillId: string }> }) {
  try {
    return NextResponse.json(
      await saveTaskReminderSubscription((await params).skillId, await request.json())
    );
  } catch (error) {
    return platformRouteError(error, '任务提醒负责人保存失败。');
  }
}
