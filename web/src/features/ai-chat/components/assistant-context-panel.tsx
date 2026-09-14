import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Icons } from '@/components/icons';
import type { TaskDraft } from '@/features/platform-api/types';

interface AssistantContextPanelProps {
  selectedFileNames: string[];
  pendingMessage: string;
  draft: TaskDraft | null;
  onOpenTask: () => void;
}

export function AssistantContextPanel({
  selectedFileNames,
  pendingMessage,
  draft,
  onOpenTask
}: AssistantContextPanelProps) {
  if (!selectedFileNames.length && !pendingMessage && !draft) return null;

  return (
    <aside
      className='min-w-0 space-y-4'
      aria-label='任务上下文'
    >
      {selectedFileNames.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>已选文件</CardTitle>
            <CardDescription>{selectedFileNames.length} 个任务输入文件</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className='space-y-1 text-sm'>
              {selectedFileNames.slice(0, 6).map((name, index) => (
                <li key={`${name}-${index}`} className='break-words' title={name}>
                  {name}
                </li>
              ))}
            </ul>
            {selectedFileNames.length > 6 && (
              <p className='mt-2 text-xs text-muted-foreground'>
                另外 {selectedFileNames.length - 6} 个文件
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {pendingMessage && (
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>待确认信息</CardTitle>
          </CardHeader>
          <CardContent>
            <p className='text-sm text-muted-foreground' role='status'>
              {pendingMessage}
            </p>
          </CardContent>
        </Card>
      )}

      {draft && (
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>已生成任务草稿</CardTitle>
            <CardDescription>
              {draft.skill_name} · {draft.skill_version}
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            <Badge variant={draft.state === 'ready' ? 'default' : 'secondary'}>
              {draft.state}
            </Badge>
            {draft.clarification && (
              <p className='text-sm text-muted-foreground'>{draft.clarification}</p>
            )}
            <Button type='button' onClick={onOpenTask} disabled={draft.state !== 'ready'}>
              <Icons.check className='size-4' /> 打开任务
            </Button>
          </CardContent>
        </Card>
      )}
    </aside>
  );
}
