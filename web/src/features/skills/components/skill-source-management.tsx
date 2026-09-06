'use client';

import { type FormEvent, useEffect, useState } from 'react';
import { IconGitBranch, IconPlayerPause, IconPlayerPlay, IconRefresh } from '@tabler/icons-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import type {
  SkillAvailability,
  SkillActiveWork,
  SkillSourceBinding,
  SkillSourceDiscovery
} from '@/features/platform-api/types';

interface Props {
  initialBindings: SkillSourceBinding[];
  initialAvailability: Record<string, SkillAvailability>;
}

interface AvailabilityAction {
  skillId: string;
  operation: 'disable' | 'enable';
}

type SkillSourceCandidate = SkillSourceDiscovery['candidates'][number];

interface SkillManagementRow {
  key: string;
  skillId: string;
  availability?: SkillAvailability;
  binding?: SkillSourceBinding;
  candidate?: SkillSourceCandidate;
}

const REPOSITORY = 'https://gitee.com/Lee157/finance-skills.git';

export function SkillSourceManagement({ initialBindings, initialAvailability }: Props) {
  const [bindings, setBindings] = useState(initialBindings);
  const [discovery, setDiscovery] = useState<SkillSourceDiscovery | null>(null);
  const [availability, setAvailability] = useState(initialAvailability);
  const [availabilityAction, setAvailabilityAction] = useState<AvailabilityAction | null>(null);
  const [busyKey, setBusyKey] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    const draining = Object.values(availability).some((item) => item.state === 'draining');
    if (!draining) return;
    const timer = window.setInterval(() => {
      for (const item of Object.values(availability)) {
        if (item.state === 'draining') void loadAvailability(item.skill_id);
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [availability]);

  async function discover() {
    setBusyKey('discover');
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/platform/admin/skill-sources/discover', {
        method: 'POST'
      });
      if (!response.ok) {
        setError(await responseMessage(response, 'Gitee Skill 发现失败。'));
      } else {
        setDiscovery((await response.json()) as SkillSourceDiscovery);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Gitee Skill 发现失败。');
    } finally {
      setBusyKey('');
    }
  }

  async function bind(candidate: SkillSourceDiscovery['candidates'][number]) {
    if (!discovery || !candidate.platform_skill_id) return;
    setBusyKey(`bind:${candidate.platform_skill_id}`);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/platform/admin/skill-sources/bindings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          skill_id: candidate.platform_skill_id,
          source_path: candidate.source_path,
          expected_commit: discovery.commit
        })
      });
      if (!response.ok) {
        setError(await responseMessage(response, 'Skill 源码绑定失败。'));
      } else {
        const binding = (await response.json()) as SkillSourceBinding;
        setBindings((current) => [
          binding,
          ...current.filter((item) => item.skill_id !== binding.skill_id)
        ]);
        setDiscovery({
          ...discovery,
          candidates: discovery.candidates.map((item) =>
            item.platform_skill_id === binding.skill_id ? { ...item, match_state: 'bound' } : item
          )
        });
        await loadAvailability(binding.skill_id);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Skill 源码绑定失败。');
    } finally {
      setBusyKey('');
    }
  }

  async function updateDisabledSkill(skillId: string) {
    setBusyKey(`update:${skillId}`);
    setError('');
    setMessage('');
    try {
      const response = await fetch(
        `/api/platform/admin/skills/${encodeURIComponent(skillId)}/update`,
        { method: 'POST' }
      );
      if (!response.ok) {
        setError(await responseMessage(response, 'Skill 更新失败。'));
      } else {
        const release = (await response.json()) as { skill_id: string; version: string };
        setMessage(`${release.skill_id} 已更新到 ${release.version}，并重新启用。`);
        await loadAvailability(skillId);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Skill 更新失败。');
    } finally {
      setBusyKey('');
    }
  }

  async function loadAvailability(skillId: string) {
    const response = await fetch(
      `/api/platform/admin/skills/${encodeURIComponent(skillId)}/availability`
    );
    if (!response.ok) {
      setError(await responseMessage(response, 'Skill 可用状态读取失败。'));
      return null;
    }
    const next = (await response.json()) as SkillAvailability;
    setAvailability((current) => ({ ...current, [skillId]: next }));
    return next;
  }

  async function transitionAvailability(
    skillId: string,
    targetState: 'enabled' | 'draining' | 'disabled',
    confirmation: string,
    reason: string
  ) {
    const response = await fetch(
      `/api/platform/admin/skills/${encodeURIComponent(skillId)}/availability`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_state: targetState,
          confirmation,
          reason
        })
      }
    );
    if (!response.ok) {
      throw new Error(await responseMessage(response, 'Skill 可用状态变更失败。'));
    }
    const next = (await response.json()) as SkillAvailability;
    setAvailability((current) => ({ ...current, [skillId]: next }));
    return next;
  }

  async function submitAvailabilityAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!availabilityAction) return;
    const form = new FormData(event.currentTarget);
    const confirmation = String(form.get('confirmation') ?? '');
    const { skillId, operation } = availabilityAction;
    setBusyKey(`availability:${skillId}`);
    setError('');
    setMessage('');
    try {
      if (operation === 'enable') {
        await transitionAvailability(skillId, 'enabled', confirmation, '管理员通过管理页启用');
        setMessage(`${skillId} 已重新启用，可以接收新任务。`);
      } else {
        const current = availability[skillId];
        const draining =
          current?.state === 'draining'
            ? current
            : await transitionAvailability(
                skillId,
                'draining',
                confirmation,
                '管理员通过管理页禁用'
              );
        if (draining.active_work_count === 0) {
          await transitionAvailability(
            skillId,
            'disabled',
            confirmation,
            '管理员通过管理页完成禁用'
          );
          setMessage(`${skillId} 已禁用，不再接收新任务。`);
        } else {
          setMessage(`${skillId} 已停止接收新任务，正在等待现有任务结束。`);
        }
      }
      setAvailabilityAction(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Skill 可用状态变更失败。');
    } finally {
      setBusyKey('');
    }
  }

  const rows = buildSkillManagementRows(availability, bindings, discovery);

  return (
    <section className='space-y-4' aria-labelledby='skill-source-title'>
      <Card>
        <CardHeader>
          <CardTitle id='skill-source-title' className='flex items-center gap-2 text-base'>
            <IconGitBranch className='size-5' />
            Skill 管理
          </CardTitle>
          <CardDescription>禁用会先停止接收新任务，并等待现有任务结束。</CardDescription>
        </CardHeader>
        <CardContent className='space-y-4'>
          <div className='flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/50 p-3 text-sm'>
            <div className='min-w-0'>
              <p className='font-medium'>Gitee 源码</p>
              <code className='break-all text-xs text-muted-foreground'>{REPOSITORY}</code>
              {discovery && (
                <p className='mt-1 text-xs text-muted-foreground'>
                  当前固定提交：{discovery.commit}
                </p>
              )}
            </div>
            <Button
              type='button'
              variant='outline'
              onClick={() => void discover()}
              disabled={Boolean(busyKey)}
            >
              <IconRefresh />
              {busyKey === 'discover' ? '正在读取…' : '按名称发现'}
            </Button>
          </div>

          <div className='hidden rounded-md border bg-muted/20 px-4 py-2 text-xs font-medium text-muted-foreground lg:grid lg:grid-cols-[minmax(12rem,1.1fr)_minmax(10rem,.8fr)_minmax(16rem,1.5fr)_auto] lg:gap-4'>
            <span>Skill</span>
            <span>可用状态</span>
            <span>源码绑定</span>
            <span className='text-right'>操作</span>
          </div>

          {rows.length === 0 ? (
            <p className='rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground'>
              当前没有可管理的 Skill。
            </p>
          ) : (
            <PaginatedCollection ariaLabel='Skill 管理列表' contentClassName='space-y-3'>
              {rows.map((row) => {
                const item = row.availability;
                const binding = row.binding;
                const candidate = row.candidate;
                const isCandidate = candidate?.match_state === 'candidate' && !binding;
                return (
                  <div key={row.key} className='rounded-lg border p-4 text-sm'>
                    <div className='grid gap-4 lg:grid-cols-[minmax(12rem,1.1fr)_minmax(10rem,.8fr)_minmax(16rem,1.5fr)_auto] lg:items-start'>
                      <div className='min-w-0'>
                        <p className='break-words font-medium'>{row.skillId}</p>
                        {candidate && candidate.source_name !== row.skillId && (
                          <p className='mt-1 text-xs text-muted-foreground'>
                            远端名称：{candidate.source_name}
                          </p>
                        )}
                      </div>

                      <div className='space-y-1'>
                        <p className='text-xs text-muted-foreground lg:hidden'>可用状态</p>
                        {item ? (
                          <>
                            <Badge variant={availabilityBadgeVariant(item.state)}>
                              {availabilityStateLabel(item.state)}
                            </Badge>
                            <p className='text-xs text-muted-foreground'>
                              活动任务 {item.active_work_count}
                            </p>
                            <p className='text-xs text-muted-foreground'>
                              当前运行版本：{item.current_version ? `v${item.current_version}` : '未记录'}
                            </p>
                            {!!item.active_work?.length && (
                              <details className='mt-2 rounded border p-2 text-xs'>
                                <summary className='cursor-pointer font-medium'>
                                  查看活动任务明细
                                </summary>
                                <div className='mt-2 space-y-2'>
                                  {item.active_work?.map((work) => (
                                    <div
                                      key={`${work.reference_type}:${work.reference_id}`}
                                      className='rounded bg-muted/50 p-2'
                                    >
                                      <div className='flex flex-wrap items-center justify-between gap-2'>
                                        <span className='font-medium'>
                                          {work.display_id || work.reference_id}
                                        </span>
                                        <Badge variant='outline'>{activeWorkStateLabel(work.state)}</Badge>
                                      </div>
                                      <p className='mt-1 text-muted-foreground'>
                                        {work.progress_message || work.original_state}
                                        {work.stage ? ` · ${work.stage}` : ''}
                                      </p>
                                      <p className='mt-1 text-muted-foreground'>
                                        等待约 {activeWorkAge(work)}
                                        {work.blocks_disable ? ' · 当前会阻止停用' : ''}
                                      </p>
                                      {work.waiting_reason && (
                                        <p className='mt-1 text-muted-foreground'>
                                          {work.waiting_reason}
                                        </p>
                                      )}
                                    </div>
                                  ))}
                                  {item.active_work_truncated && (
                                    <p className='text-muted-foreground'>
                                      仅显示最近 200 条，仍有 {item.active_work_count - (item.active_work?.length ?? 0)}{' '}
                                      条活动任务未展开。
                                    </p>
                                  )}
                                </div>
                              </details>
                            )}
                          </>
                        ) : (
                          <Badge variant='outline'>平台未登记</Badge>
                        )}
                      </div>

                      <div className='min-w-0 space-y-1'>
                        <p className='text-xs text-muted-foreground lg:hidden'>源码绑定</p>
                        {binding ? (
                          <>
                            <Badge
                              variant={
                                binding.binding_status === 'bound' ? 'default' : 'destructive'
                              }
                            >
                              {bindingStateLabel(binding.binding_status)}
                            </Badge>
                            <p className='break-all text-xs text-muted-foreground'>
                              {binding.source_path}
                            </p>
                            <p className='text-xs text-muted-foreground'>
                              已安装源码提交：{shortCommit(binding.published_commit)} · 上游最近发现：{' '}
                              {shortCommit(binding.last_seen_commit)}
                            </p>
                          </>
                        ) : candidate ? (
                          <>
                            <div className='flex flex-wrap items-center gap-2'>
                              <Badge variant={isCandidate ? 'default' : 'outline'}>
                                {candidateStateLabel(candidate.match_state)}
                              </Badge>
                              {isCandidate && (
                                <Button
                                  type='button'
                                  onClick={() => void bind(candidate)}
                                  disabled={Boolean(busyKey)}
                                >
                                  {busyKey === `bind:${candidate.platform_skill_id}`
                                    ? '绑定中…'
                                    : '确认绑定'}
                                </Button>
                              )}
                            </div>
                            <p className='break-all text-xs text-muted-foreground'>
                              {candidate.source_path}
                            </p>
                            {candidate.reason && (
                              <p className='text-xs text-muted-foreground'>{candidate.reason}</p>
                            )}
                          </>
                        ) : (
                          <p className='text-xs text-muted-foreground'>尚未发现源码绑定</p>
                        )}
                      </div>

                      <div className='flex flex-wrap items-center gap-2 lg:justify-end'>
                        {item?.state === 'enabled' && (
                          <Button
                            type='button'
                            variant='destructive'
                            onClick={() =>
                              setAvailabilityAction({
                                skillId: item.skill_id,
                                operation: 'disable'
                              })
                            }
                            disabled={Boolean(busyKey)}
                          >
                            <IconPlayerPause />
                            禁用 Skill
                          </Button>
                        )}
                        {item?.state === 'disabled' && (
                          <>
                            <Button
                              type='button'
                              onClick={() =>
                                setAvailabilityAction({
                                  skillId: item.skill_id,
                                  operation: 'enable'
                                })
                              }
                              disabled={Boolean(busyKey)}
                            >
                              <IconPlayerPlay />
                              重新启用
                            </Button>
                            {binding?.binding_status === 'bound' && (
                              <Button
                                type='button'
                                variant='outline'
                                onClick={() => void updateDisabledSkill(item.skill_id)}
                                disabled={Boolean(busyKey)}
                              >
                                {busyKey === `update:${item.skill_id}`
                                  ? '正在从 Gitee 更新…'
                                  : '拉取最新代码并更新'}
                              </Button>
                            )}
                          </>
                        )}
                        {item?.state === 'draining' && (
                          <>
                            <Button
                              type='button'
                              variant='outline'
                              onClick={() => void loadAvailability(item.skill_id)}
                              disabled={Boolean(busyKey)}
                            >
                              刷新状态
                            </Button>
                            {item.active_work_count === 0 && (
                              <Button
                                type='button'
                                variant='destructive'
                                onClick={() =>
                                  setAvailabilityAction({
                                    skillId: item.skill_id,
                                    operation: 'disable'
                                  })
                                }
                                disabled={Boolean(busyKey)}
                              >
                                完成禁用
                              </Button>
                            )}
                            <Button
                              type='button'
                              variant='ghost'
                              onClick={() =>
                                setAvailabilityAction({
                                  skillId: item.skill_id,
                                  operation: 'enable'
                                })
                              }
                              disabled={Boolean(busyKey)}
                            >
                              取消禁用
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                    {item?.state === 'draining' && (
                      <p className='mt-3 rounded bg-amber-50 p-3 text-amber-950 dark:bg-amber-950/30 dark:text-amber-100'>
                        等待现有任务结束，当前还有 {item.active_work_count} 个活动任务。
                      </p>
                    )}
                    {item?.state === 'failed_disabled' && (
                      <p className='mt-3 rounded bg-destructive/10 p-3 text-destructive'>
                        发布恢复失败，保持禁用。请先核对生产目录和发布记录，不能直接重新启用。
                      </p>
                    )}
                  </div>
                );
              })}
            </PaginatedCollection>
          )}
        </CardContent>
      </Card>
      {message && (
        <p role='status' className='text-sm text-emerald-700'>
          {message}
        </p>
      )}
      {error && (
        <p role='alert' className='text-sm text-destructive'>
          {error}
        </p>
      )}
      <Dialog
        open={Boolean(availabilityAction)}
        onOpenChange={(open) => !open && setAvailabilityAction(null)}
      >
        <DialogContent>
          {availabilityAction && (
            <form onSubmit={(event) => void submitAvailabilityAction(event)} className='space-y-4'>
              <DialogHeader>
                <DialogTitle>
                  {availabilityAction.operation === 'disable' ? '禁用 Skill' : '重新启用 Skill'}
                </DialogTitle>
                <DialogDescription>
                  {availabilityAction.operation === 'disable'
                    ? '平台会先停止接收新任务。已有任务结束后才能完成禁用。'
                    : '启用后，该 Skill 将立即恢复接收新任务。'}
                </DialogDescription>
              </DialogHeader>
              <p className='rounded bg-muted p-3 text-sm'>
                请输入确认文字：
                <strong>
                  {availabilityAction.operation === 'disable'
                    ? `禁用 ${availabilityAction.skillId}`
                    : `启用 ${availabilityAction.skillId}`}
                </strong>
              </p>
              <Input name='confirmation' required autoComplete='off' />
              <DialogFooter>
                <Button
                  type='submit'
                  variant={availabilityAction.operation === 'disable' ? 'destructive' : 'default'}
                  disabled={Boolean(busyKey)}
                >
                  {busyKey ? '处理中…' : '确认执行'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}

function buildSkillManagementRows(
  availability: Record<string, SkillAvailability>,
  bindings: SkillSourceBinding[],
  discovery: SkillSourceDiscovery | null
): SkillManagementRow[] {
  const rows = new Map<string, SkillManagementRow>();

  for (const item of Object.values(availability)) {
    rows.set(item.skill_id, {
      key: item.skill_id,
      skillId: item.skill_id,
      availability: item
    });
  }

  for (const binding of bindings) {
    const row = rows.get(binding.skill_id);
    rows.set(binding.skill_id, {
      key: row?.key ?? binding.skill_id,
      skillId: binding.skill_id,
      availability: row?.availability,
      binding,
      candidate: row?.candidate
    });
  }

  for (const candidate of discovery?.candidates ?? []) {
    const rowKey = candidate.platform_skill_id || `source:${candidate.source_path}`;
    const skillId = candidate.platform_skill_id || candidate.source_name;
    const row = rows.get(rowKey);
    rows.set(rowKey, {
      key: row?.key ?? rowKey,
      skillId: row?.skillId ?? skillId,
      availability: row?.availability,
      binding: row?.binding,
      candidate
    });
  }

  return [...rows.values()].toSorted((left, right) => left.skillId.localeCompare(right.skillId));
}

function bindingStateLabel(state: SkillSourceBinding['binding_status']) {
  return {
    candidate: '待确认',
    bound: '已绑定',
    broken: '绑定异常',
    excluded: '已排除'
  }[state];
}

function shortCommit(commit: string) {
  return commit ? commit.slice(0, 12) : '未记录';
}

function availabilityStateLabel(state: SkillAvailability['state']) {
  return {
    enabled: '已启用',
    draining: '正在排空',
    disabled: '已禁用',
    failed_disabled: '异常禁用'
  }[state];
}

function availabilityBadgeVariant(state: SkillAvailability['state']) {
  if (state === 'enabled') return 'default' as const;
  if (state === 'failed_disabled') return 'destructive' as const;
  return 'outline' as const;
}

function candidateStateLabel(state: SkillSourceDiscovery['candidates'][number]['match_state']) {
  return {
    candidate: '待确认',
    bound: '已绑定',
    conflict: '冲突',
    unmatched: '平台无同名项',
    excluded: '已排除'
  }[state];
}

function activeWorkStateLabel(state: SkillActiveWork['state']): string {
  return {
    queued: '排队中',
    running: '执行中',
    waiting_material: '等待材料',
    waiting_confirmation: '等待确认',
    unknown: '状态待核实'
  }[state];
}

function activeWorkAge(work: SkillActiveWork): string {
  const start = work.queued_at || work.updated_at;
  const timestamp = Date.parse(start);
  if (!Number.isFinite(timestamp)) return '待核实';
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  return `${Math.floor(seconds / 3600)} 小时`;
}

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  return typeof body?.detail === 'string' ? body.detail : fallback;
}
