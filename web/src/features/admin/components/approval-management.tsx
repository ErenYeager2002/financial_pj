'use client';

import { type FormEvent, useMemo, useState } from 'react';
import { IconChecks, IconClock, IconFileDescription } from '@tabler/icons-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import type { ApprovalRecord, PlatformSession } from '@/features/platform-api/types';
import { formatDate } from '@/lib/format';

interface Props {
  session: PlatformSession;
  initialApprovals: ApprovalRecord[];
}

const STATE_LABELS: Record<ApprovalRecord['status'], string> = {
  pending: '等待审批',
  approved: '已批准',
  rejected: '已拒绝',
  expired: '已过期',
  revoked: '已失效'
};

function summaries(preview: Record<string, unknown>): Array<[string, string]> {
  const value = preview.summary;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, String(item)]);
}

function artifacts(preview: Record<string, unknown>): Array<Record<string, unknown>> {
  return Array.isArray(preview.artifacts)
    ? preview.artifacts.filter((item): item is Record<string, unknown> =>
        Boolean(item && typeof item === 'object')
      )
    : [];
}

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null;
  return body?.detail ?? fallback;
}

export function ApprovalManagement({ session, initialApprovals }: Props) {
  const [items, setItems] = useState(initialApprovals);
  const [filter, setFilter] = useState('pending');
  const [selected, setSelected] = useState<ApprovalRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const visible = useMemo(
    () => items.filter((item) => !filter || item.status === filter),
    [filter, items]
  );

  async function submitDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError('');
    const form = new FormData(event.currentTarget);
    const response = await fetch(`/api/platform/admin/approvals/${selected.id}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision: form.get('decision'), reason: form.get('reason') })
    });
    if (!response.ok) {
      setError(await responseMessage(response, '审批提交失败。'));
      setBusy(false);
      return;
    }
    const updated = (await response.json()) as ApprovalRecord;
    setItems((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    setSelected(null);
    setBusy(false);
  }

  return (
    <section className='space-y-4'>
      <Card>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <IconChecks className='size-5' />
            写入任务审批
          </CardTitle>
          <CardDescription>
            批准只对当前预览、输入文件、Skill 快照和有效期生效；任何内容变化都会使审批失效。
          </CardDescription>
        </CardHeader>
        <CardContent className='flex flex-wrap items-center gap-3'>
          <label htmlFor='approval-filter' className='text-sm font-medium'>
            状态
          </label>
          <select
            id='approval-filter'
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            className='h-9 rounded-md border bg-background px-3 text-sm'
          >
            <option value='pending'>等待审批</option>
            <option value=''>全部记录</option>
            <option value='approved'>已批准</option>
            <option value='rejected'>已拒绝</option>
            <option value='expired'>已过期</option>
            <option value='revoked'>已失效</option>
          </select>
          <p className='text-sm text-muted-foreground'>共 {visible.length} 条</p>
        </CardContent>
      </Card>

      {visible.length === 0 ? (
        <Card>
          <CardContent className='py-10 text-center text-sm text-muted-foreground'>
            当前筛选条件下没有审批记录。
          </CardContent>
        </Card>
      ) : (
        <div className='grid gap-4 xl:grid-cols-2'>
          {visible.map((approval) => {
            const preview = approval.preview as Record<string, unknown>;
            const selfRequested = approval.requested_by === session.user_id;
            return (
              <Card key={approval.id}>
                <CardHeader>
                  <div className='flex items-start justify-between gap-3'>
                    <div>
                      <CardTitle className='text-base'>
                        {String(preview.skill_name ?? approval.skill_id)}
                      </CardTitle>
                      <CardDescription>
                        核销日期 {String(preview.reconciliation_date ?? '未提供')} · 发起人{' '}
                        {approval.requested_by_name || approval.requested_by}
                      </CardDescription>
                    </div>
                    <Badge variant={approval.status === 'pending' ? 'default' : 'outline'}>
                      {STATE_LABELS[approval.status]}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className='space-y-3 text-sm'>
                  <div className='flex items-center gap-2 text-muted-foreground'>
                    <IconClock className='size-4' />
                    申请 {formatDate(approval.created_at)} · 到期{' '}
                    {approval.expires_at ? formatDate(approval.expires_at) : '未设置'}
                  </div>
                  <div className='grid grid-cols-2 gap-2 rounded border p-3'>
                    {summaries(preview).map(([label, value]) => (
                      <div key={label}>
                        <p className='text-xs text-muted-foreground'>{label}</p>
                        <p className='font-medium'>{value}</p>
                      </div>
                    ))}
                  </div>
                  <div className='space-y-2'>
                    {artifacts(preview).map((item) => (
                      <div
                        key={String(item.file_id)}
                        className='flex items-center gap-2 rounded bg-muted p-2'
                      >
                        <IconFileDescription className='size-4' />
                        <span className='min-w-0 flex-1 truncate'>{String(item.name)}</span>
                        <span className='text-xs text-muted-foreground'>
                          {String(item.sha256).slice(0, 12)}…
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className='text-xs text-muted-foreground'>
                    执行快照 {approval.snapshot_sha256.slice(0, 16)}… · 预览{' '}
                    {approval.preview_sha256.slice(0, 16)}…
                  </p>
                  {approval.reason && (
                    <p className='rounded bg-muted p-2'>审批意见：{approval.reason}</p>
                  )}
                  {approval.status === 'pending' && (
                    <div className='space-y-1'>
                      <Button
                        type='button'
                        onClick={() => {
                          setError('');
                          setSelected(approval);
                        }}
                        disabled={selfRequested}
                      >
                        处理审批
                      </Button>
                      {selfRequested && (
                        <p className='text-xs text-destructive'>发起人不能审批自己的写入任务。</p>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent>
          {selected && (
            <form onSubmit={(event) => void submitDecision(event)} className='space-y-4'>
              <DialogHeader>
                <DialogTitle>处理写入审批</DialogTitle>
                <DialogDescription>
                  批准后 Worker 仍会重新校验执行快照、审批有效期和原始文件哈希。
                </DialogDescription>
              </DialogHeader>
              <label htmlFor='approval-decision' className='grid gap-1 text-sm'>
                审批结果
                <select
                  id='approval-decision'
                  name='decision'
                  className='h-9 rounded-md border bg-background px-3'
                >
                  <option value='approve'>批准写入</option>
                  <option value='reject'>拒绝写入</option>
                </select>
              </label>
              <label htmlFor='approval-reason' className='grid gap-1 text-sm'>
                审批意见
                <Textarea
                  id='approval-reason'
                  name='reason'
                  minLength={2}
                  maxLength={2000}
                  required
                />
              </label>
              {error && (
                <p role='alert' className='text-sm text-destructive'>
                  {error}
                </p>
              )}
              <DialogFooter>
                <Button type='submit' disabled={busy}>
                  {busy ? '提交中…' : '提交审批决定'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}
