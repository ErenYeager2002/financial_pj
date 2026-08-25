import { NextResponse } from 'next/server';
import {
  deleteTaskReminderOwnerCredential,
  getTaskReminderOwnerCredential,
  saveTaskReminderOwnerCredential
} from '@/features/task-reminders/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Context = { params: Promise<{ skillId: string }> };

export async function GET(_request: Request, { params }: Context) {
  try {
    return NextResponse.json(await getTaskReminderOwnerCredential((await params).skillId));
  } catch (error) {
    return platformRouteError(error, '负责人凭据状态加载失败。');
  }
}

export async function PUT(request: Request, { params }: Context) {
  try {
    return NextResponse.json(
      await saveTaskReminderOwnerCredential((await params).skillId, await request.json())
    );
  } catch (error) {
    return platformRouteError(error, '负责人凭据保存失败。');
  }
}

export async function DELETE(_request: Request, { params }: Context) {
  try {
    await deleteTaskReminderOwnerCredential((await params).skillId);
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return platformRouteError(error, '负责人凭据删除失败。');
  }
}
