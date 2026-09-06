'use client';

import { type FormEvent, useState } from 'react';
import { IconGitBranch, IconPackageImport } from '@tabler/icons-react';
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
import { Textarea } from '@/components/ui/textarea';
import type {
  SkillAvailability,
  SkillRelease,
  SkillReleaseInboxItem,
  SkillRollout,
  SkillSourceBinding
} from '@/features/platform-api/types';
import { formatDate } from '@/lib/format';

interface Props {
  initialReleases?: SkillRelease[];
  initialInbox?: SkillReleaseInboxItem[];
  initialAvailability?: SkillAvailability[];
  initialBindings?: SkillSourceBinding[];
  view: 'inbox' | 'records';
}

const STATE_LABELS: Record<SkillRelease['state'], string> = {
  validated: '已生成',
  reviewed: '可发布',
  rejected: '已退回',
  published: '当前发布',
  superseded: '历史版本',
  rolled_back: '历史版本'
};

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null;
  return body?.detail ?? fallback;
}

export function SkillReleaseManagement({
  initialReleases = [],
  initialInbox = [],
  initialAvailability = [],
  initialBindings = [],
  view
}: Props) {
  const [releases, setReleases] = useState(initialReleases);
  const [inbox, setInbox] = useState(initialInbox);
  const [editing, setEditing] = useState<SkillRelease | null>(null);
  const [reviewing, setReviewing] = useState<SkillRelease | null>(null);
  const [publishing, setPublishing] = useState<SkillRelease | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [rolloutState, setRolloutState] = useState<SkillRollout['state'] | ''>('');
  const [availability, setAvailability] = useState(initialAvailability);
  const availabilityBySkill = new Map(availability.map((item) => [item.skill_id, item]));
  const bindingBySkill = new Map(initialBindings.map((item) => [item.skill_id, item]));

  function replaceRelease(updated: SkillRelease) {
    setReleases((current) => {
      const found = current.some((item) => item.id === updated.id);
      const next = found
        ? current.map((item) => (item.id === updated.id ? updated : item))
        : [updated, ...current];
      return next.toSorted((left, right) => right.created_at.localeCompare(left.created_at));
    });
  }

  async function importPackage(packageName: string) {
    setBusy(true);
    setError('');
    const response = await fetch('/api/platform/admin/skill-releases/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ package_name: packageName })
    });
    if (!response.ok) {
      setError(await responseMessage(response, 'Skill 发布包导入失败。'));
      setBusy(false);
      return;
    }
    replaceRelease((await response.json()) as SkillRelease);
    setInbox((current) => current.filter((item) => item.package_name !== packageName));
    setBusy(false);
  }

  async function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    setBusy(true);
    setError('');
    const form = new FormData(event.currentTarget);
    const response = await fetch(`/api/platform/admin/skill-releases/${editing.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.get('name'),
        description: form.get('description'),
        category: form.get('category'),
        tags: String(form.get('tags') ?? '')
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
        ui: {
          ...editing.manifest.ui,
          employee_name: form.get('employee_name'),
          short_description: form.get('short_description'),
          categories: String(form.get('categories') ?? '')
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean),
          estimated_minutes: Number(form.get('estimated_minutes')),
          output_summary: form.get('output_summary'),
          action_label: form.get('action_label'),
          popular: form.get('popular') === 'on'
        }
      })
    });
    if (!response.ok) {
      setError(await responseMessage(response, 'Skill 元数据保存失败。'));
      setBusy(false);
      return;
    }
    replaceRelease((await response.json()) as SkillRelease);
    setEditing(null);
    setBusy(false);
  }

  async function submitReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reviewing) return;
    setBusy(true);
    setError('');
    const form = new FormData(event.currentTarget);
    const response = await fetch(`/api/platform/admin/skill-releases/${reviewing.id}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision: form.get('decision'), notes: form.get('notes') })
    });
    if (!response.ok) {
      setError(await responseMessage(response, 'Skill 发布审核失败。'));
      setBusy(false);
      return;
    }
    replaceRelease((await response.json()) as SkillRelease);
    setReviewing(null);
    setBusy(false);
  }

  async function submitAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!publishing) return;
    setBusy(true);
    setError('');
    const form = new FormData(event.currentTarget);
    const response = await fetch(`/api/platform/admin/skill-releases/${publishing.id}/rollout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmation: form.get('confirmation') })
    });
    if (!response.ok) {
      setError(await responseMessage(response, 'Skill 发布任务创建失败。'));
      setBusy(false);
      return;
    }
    let rollout = (await response.json()) as SkillRollout;
    setRolloutState(rollout.state);
    for (let attempt = 0; attempt < 300 && !isTerminalRollout(rollout.state); attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      const status = await fetch(`/api/platform/admin/skill-rollouts/${rollout.id}`);
      if (!status.ok) {
        setError(await responseMessage(status, 'Skill 发布状态读取失败。'));
        setBusy(false);
        return;
      }
      rollout = (await status.json()) as SkillRollout;
      setRolloutState(rollout.state);
    }
    if (rollout.state !== 'succeeded') {
      setError(rollout.error_message || 'Skill 发布未成功，目标 Skill 保持禁用或已恢复原版本。');
      setBusy(false);
      return;
    }
    const refreshed = await fetch('/api/platform/admin/skill-releases');
    if (refreshed.ok) setReleases((await refreshed.json()) as SkillRelease[]);
    const refreshedAvailability = await fetch('/api/platform/admin/skills/availability');
    if (refreshedAvailability.ok) {
      setAvailability((await refreshedAvailability.json()) as SkillAvailability[]);
    }
    setPublishing(null);
    setRolloutState('');
    setBusy(false);
  }

  return (
    <section className='space-y-4'>
      {view === 'inbox' && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <IconGitBranch className='size-5' />
                受控 Skill 发布
              </CardTitle>
              <CardDescription>
                代码必须先在 Git
                中提交并通过测试，再由服务器打包工具放入收件箱。网页不上传或编辑代码。
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-2 text-sm'>
              <p>流程：受控同步 → 生成发布包 → 导入 → 编辑业务元数据 → 审核 → 发布。</p>
              <code className='block overflow-x-auto rounded bg-muted p-3 text-xs'>
                scripts\stage_skill_release.py --skill-dir &lt;暂存目录&gt; --source-repo
                &lt;Git仓库&gt; --source-skill &lt;源码Skill&gt; --test-command &lt;测试命令&gt;
              </code>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className='text-base'>待导入发布包</CardTitle>
              <CardDescription>只显示服务器受控收件箱中不超过 50 MB 的 ZIP 包。</CardDescription>
            </CardHeader>
            <CardContent className='space-y-2'>
              {inbox.length === 0 ? (
                <p className='text-sm text-muted-foreground'>当前没有待导入发布包。</p>
              ) : (
                <PaginatedCollection ariaLabel='待导入发布包' contentClassName='space-y-2'>
                  {inbox.map((item) => (
                  <div
                    key={item.package_name}
                    className='flex flex-wrap items-center gap-3 rounded border p-3'
                  >
                    <IconPackageImport className='size-5' />
                    <div className='min-w-0 flex-1'>
                      <p className='truncate font-medium'>{item.package_name}</p>
                      <p className='text-xs text-muted-foreground'>
                        {(item.size_bytes / 1024).toFixed(1)} KB · SHA-256{' '}
                        {item.sha256.slice(0, 12)}…
                      </p>
                    </div>
                    <Button
                      type='button'
                      onClick={() => void importPackage(item.package_name)}
                      disabled={busy}
                    >
                      导入并校验
                    </Button>
                  </div>
                  ))}
                </PaginatedCollection>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {view === 'records' && (
        <section className='space-y-3' aria-labelledby='skill-review-records-title'>
          <div>
            <h2 id='skill-review-records-title' className='text-lg font-semibold'>
              Skill 发布记录
            </h2>
          </div>
          {releases.length === 0 ? (
            <Card>
              <CardContent className='py-8 text-sm text-muted-foreground'>
                当前没有 Skill 发布记录。
              </CardContent>
            </Card>
          ) : (
            <PaginatedCollection
              ariaLabel='Skill 发布记录'
              contentClassName='grid gap-3 lg:grid-cols-2'
            >
              {releases.map((release) => (
                <Card key={release.id}>
                  <CardHeader>
                    <div className='flex items-start justify-between gap-3'>
                      <div>
                        <CardTitle className='text-base'>{release.manifest.name}</CardTitle>
                        <CardDescription>
                          {release.skill_id} · v{release.version}
                        </CardDescription>
                      </div>
                      <Badge variant={release.state === 'published' ? 'default' : 'outline'}>
                        {STATE_LABELS[release.state]}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className='space-y-3 text-sm'>
                    <div className='grid grid-cols-2 gap-2 text-muted-foreground'>
                      <span>
                        当前运行版本：
                        {availabilityBySkill.get(release.skill_id)?.current_version
                          ? `v${availabilityBySkill.get(release.skill_id)?.current_version}`
                          : '未记录'}
                      </span>
                      <span>发布包状态：{STATE_LABELS[release.state]}</span>
                      <span>发布包源码提交：{release.source_commit.slice(0, 12) || '未记录'}</span>
                      <span>
                        上游最近发现：
                        {shortCommit(bindingBySkill.get(release.skill_id)?.last_seen_commit || '')}
                      </span>
                      <span>导入：{formatDate(release.created_at)}</span>
                      <span>
                        结构校验：{release.validation?.passed === true ? '通过' : '未通过'}
                      </span>
                      <span>测试：{release.tests?.passed === true ? '通过' : '未通过'}</span>
                    </div>
                    {release.review_notes && (
                      <p className='rounded bg-muted p-2'>
                        发布说明：
                        {release.review_notes === '自动保存的线上回退基线'
                          ? '自动保存的发布前线上版本归档'
                          : release.review_notes}
                      </p>
                    )}
                  </CardContent>
                </Card>
              ))}
            </PaginatedCollection>
          )}
        </section>
      )}
      {error && (
        <p role='alert' className='text-sm text-destructive'>
          {error}
        </p>
      )}

      <Dialog open={Boolean(editing)} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-2xl'>
          {editing && (
            <form onSubmit={(event) => void saveMetadata(event)} className='space-y-3'>
              <DialogHeader>
                <DialogTitle>编辑业务元数据</DialogTitle>
                <DialogDescription>
                  执行入口、运行限制和代码内容只能通过 Git 发布包修改。
                </DialogDescription>
              </DialogHeader>
              <label htmlFor='release-name' className='grid gap-1 text-sm'>
                内部名称
                <Input
                  id='release-name'
                  name='name'
                  defaultValue={editing.manifest.name}
                  required
                />
              </label>
              <label htmlFor='release-employee-name' className='grid gap-1 text-sm'>
                业务名称
                <Input
                  id='release-employee-name'
                  name='employee_name'
                  defaultValue={editing.manifest.ui?.employee_name}
                  required
                />
              </label>
              <label htmlFor='release-description' className='grid gap-1 text-sm'>
                说明
                <Textarea
                  id='release-description'
                  name='description'
                  defaultValue={editing.manifest.description}
                  required
                />
              </label>
              <label htmlFor='release-short-description' className='grid gap-1 text-sm'>
                员工短说明
                <Textarea
                  id='release-short-description'
                  name='short_description'
                  defaultValue={editing.manifest.ui?.short_description}
                  required
                />
              </label>
              <div className='grid gap-3 sm:grid-cols-2'>
                <label htmlFor='release-category' className='grid gap-1 text-sm'>
                  内部分类
                  <Input
                    id='release-category'
                    name='category'
                    defaultValue={editing.manifest.category}
                    required
                  />
                </label>
                <label htmlFor='release-categories' className='grid gap-1 text-sm'>
                  员工分类（逗号分隔）
                  <Input
                    id='release-categories'
                    name='categories'
                    defaultValue={editing.manifest.ui?.categories.join(',')}
                    required
                  />
                </label>
                <label htmlFor='release-tags' className='grid gap-1 text-sm'>
                  标签（逗号分隔）
                  <Input
                    id='release-tags'
                    name='tags'
                    defaultValue={editing.manifest.tags?.join(',')}
                  />
                </label>
                <label htmlFor='release-estimated-minutes' className='grid gap-1 text-sm'>
                  预计分钟
                  <Input
                    id='release-estimated-minutes'
                    name='estimated_minutes'
                    type='number'
                    min={1}
                    max={1440}
                    defaultValue={editing.manifest.ui?.estimated_minutes}
                    required
                  />
                </label>
              </div>
              <label htmlFor='release-output-summary' className='grid gap-1 text-sm'>
                输出说明
                <Input
                  id='release-output-summary'
                  name='output_summary'
                  defaultValue={editing.manifest.ui?.output_summary}
                  required
                />
              </label>
              <label htmlFor='release-action-label' className='grid gap-1 text-sm'>
                操作按钮文字
                <Input
                  id='release-action-label'
                  name='action_label'
                  defaultValue={editing.manifest.ui?.action_label}
                  required
                />
              </label>
              <label className='flex items-center gap-2 text-sm'>
                <input
                  name='popular'
                  type='checkbox'
                  defaultChecked={editing.manifest.ui?.popular}
                />
                标记为常用 Skill
              </label>
              {error && (
                <p role='alert' className='text-sm text-destructive'>
                  {error}
                </p>
              )}
              <DialogFooter>
                <Button type='submit' disabled={busy}>
                  {busy ? '保存中…' : '保存元数据'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(reviewing)} onOpenChange={(open) => !open && setReviewing(null)}>
        <DialogContent>
          {reviewing && (
            <form onSubmit={(event) => void submitReview(event)} className='space-y-4'>
              <DialogHeader>
                <DialogTitle>
                  审核 {reviewing.skill_id} v{reviewing.version}
                </DialogTitle>
                <DialogDescription>
                  确认源码提交、包哈希、测试证据、执行入口和业务元数据。
                </DialogDescription>
              </DialogHeader>
              <label className='grid gap-1 text-sm'>
                审核结果
                <select name='decision' className='h-9 rounded-md border bg-background px-3'>
                  <option value='approve'>审核通过</option>
                  <option value='reject'>退回修改</option>
                </select>
              </label>
              <label htmlFor='release-review-notes' className='grid gap-1 text-sm'>
                审核意见
                <Textarea
                  id='release-review-notes'
                  name='notes'
                  required
                  minLength={2}
                  maxLength={2000}
                />
              </label>
              {error && (
                <p role='alert' className='text-sm text-destructive'>
                  {error}
                </p>
              )}
              <DialogFooter>
                <Button type='submit' disabled={busy}>
                  {busy ? '提交中…' : '提交审核'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(publishing)} onOpenChange={(open) => !open && setPublishing(null)}>
        <DialogContent>
          {publishing && (
            <form onSubmit={(event) => void submitAction(event)} className='space-y-4'>
              <DialogHeader>
                <DialogTitle>停用并发布 Skill 版本</DialogTitle>
                <DialogDescription>
                  系统先停止接收该 Skill 的新任务，等待现有任务结束，再切换版本并重新启用。
                </DialogDescription>
              </DialogHeader>
              <p className='rounded bg-muted p-3 text-sm'>
                请输入：
                <strong>
                  停用并发布 {publishing.skill_id} {publishing.version}
                </strong>
              </p>
              <Input name='confirmation' required autoComplete='off' />
              {rolloutState && (
                <p role='status' className='text-sm text-muted-foreground'>
                  当前进度：{rolloutStateLabel(rolloutState)}
                </p>
              )}
              {error && (
                <p role='alert' className='text-sm text-destructive'>
                  {error}
                </p>
              )}
              <DialogFooter>
                <Button type='submit' disabled={busy}>
                  {busy ? '处理中…' : '确认执行'}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}

function isTerminalRollout(state: SkillRollout['state']) {
  return ['succeeded', 'failed', 'failed_disabled'].includes(state);
}

function rolloutStateLabel(state: SkillRollout['state']) {
  return {
    queued: '等待 Worker',
    draining: '等待现有任务结束',
    activating: '切换版本',
    verifying: '验证新版本',
    succeeded: '发布完成并已启用',
    failed: '发布失败，已恢复原版本',
    failed_disabled: '发布失败，保持禁用'
  }[state];
}

function shortCommit(commit: string): string {
  return commit ? commit.slice(0, 12) : '未记录';
}
