import { NextResponse } from 'next/server';
import {
  dismissResolvedTaskReminders,
  getTaskReminderBoard,
  queueTaskDiscoveryCheck
} from '@/features/task-reminders/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await getTaskReminderBoard());
  } catch (error) {
    return platformRouteError(error, '任务提醒加载失败。');
  }
}

export async function POST(request: Request) {
  try {
    return NextResponse.json(await queueTaskDiscoveryCheck(await request.json()), { status: 202 });
  } catch (error) {
    return platformRouteError(error, '任务检查排队失败。');
  }
}

export async function DELETE() {
  try {
    return NextResponse.json(await dismissResolvedTaskReminders());
  } catch (error) {
    return platformRouteError(error, '已处理成功提醒清理失败。');
  }
}
