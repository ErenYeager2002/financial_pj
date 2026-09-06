'use client';

import { type FormEvent, useMemo, useState } from 'react';
import { IconPlus, IconTrash, IconUserEdit, IconUsers } from '@tabler/icons-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  CollectionPaginationControls,
  useCollectionPagination
} from '@/components/ui/collection-pagination';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import type { AdminUser, SkillDedication, SkillDetail } from '@/features/platform-api/types';

interface Props {
  initialDedications: SkillDedication[];
  users: AdminUser[];
  skills: SkillDetail[];
  skillIds: string[];
}

interface DedicationAction {
  kind: 'set' | 'clear';
  skillId: string;
}

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null;
  return body?.detail ?? fallback;
}

export function SkillDedicatedUserManagement({
  initialDedications,
  users,
  skills,
  skillIds
}: Props) {
  const [dedications, setDedications] = useState(initialDedications);
  const [query, setQuery] = useState('');
  const [action, setAction] = useState<DedicationAction | null>(null);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const usersForSelection = useMemo(
    () =>
      users
        .filter((user) => user.status === 'active' && user.role === 'finance_user')
        .toSorted((left, right) => left.display_name.localeCompare(right.display_name, 'zh-CN')),
    [users]
  );
  const skillsById = useMemo(() => new Map(skills.map((skill) => [skill.id, skill])), [skills]);
  const dedicationBySkillId = useMemo(
    () => new Map(dedications.map((dedication) => [dedication.skill_id, dedication])),
    [dedications]
  );
  const rows = useMemo(() => {
    const ids = new Set([
      ...skillIds,
      ...skills.map((skill) => skill.id),
      ...dedications.map((dedication) => dedication.skill_id)
    ]);
    const normalizedQuery = query.trim().toLocaleLowerCase('zh-CN');
    return [...ids]
      .toSorted((left, right) => left.localeCompare(right))
      .filter((skillId) => {
        if (!normalizedQuery) return true;
        const skill = skillsById.get(skillId);
        const dedication = dedicationBySkillId.get(skillId);
        return [skillId, skill?.name ?? '', dedication?.user_display_name ?? ''].some((value) =>
          value.toLocaleLowerCase('zh-CN').includes(normalizedQuery)
        );
      });
  }, [dedications, dedicationBySkillId, query, skillIds, skills, skillsById]);
  const rowPage = useCollectionPagination(rows);

  function openSet(skillId: string) {
    const current = dedicationBySkillId.get(skillId);
    setSelectedUserId(current?.user_status === 'active' ? current.user_id : '');
    setAction({ kind: 'set', skillId });
    setMessage('');
    setError('');
  }

  function openClear(skillId: string) {
    setAction({ kind: 'clear', skillId });
    setMessage('');
    setError('');
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!action) return;
    setBusy(true);
    setMessage('');
    setError('');
    try {
      if (action.kind === 'set') {
        if (!selectedUserId) {
          setError('请选择一名当前部门的正常财务员工。');
          return;
        }
        const response = await fetch(
          `/api/platform/admin/skill-dedications/${encodeURIComponent(action.skillId)}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: selectedUserId })
          }
        );
        if (!response.ok) {
          setError(await responseMessage(response, 'Skill 专属员工设置失败。'));
          return;
        }
        const next = (await response.json()) as SkillDedication;
        setDedications((current) => [
          ...current.filter((item) => item.skill_id !== next.skill_id),
          next
        ]);
        setMessage(`${action.skillId} 的专属员工已更新为 ${next.user_display_name}。`);
      } else {
        const response = await fetch(
          `/api/platform/admin/skill-dedications/${encodeURIComponent(action.skillId)}`,
          { method: 'DELETE' }
        );
        if (!response.ok) {
          setError(await responseMessage(response, 'Skill 专属员工清除失败。'));
          return;
        }
        setDedications((current) => current.filter((item) => item.skill_id !== action.skillId));
        setMessage(`${action.skillId} 的专属员工标记已清除。`);
      }
      setAction(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Skill 专属员工操作失败。');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className='space-y-4' aria-labelledby='skill-dedication-title'>
      <Card>
        <CardHeader>
          <CardTitle id='skill-dedication-title' className='flex items-center gap-2 text-base'>
            <IconUsers className='size-5' />
            Skill 专属员工
          </CardTitle>
        </CardHeader>
        <CardContent className='space-y-4'>
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder='按 Skill ID 或名称筛选'
            aria-label='按 Skill ID 或名称筛选'
          />
          {message && (
            <p className='text-sm text-emerald-700 dark:text-emerald-400' role='status'>
              {message}
            </p>
          )}
          {error && (
            <p className='text-sm text-destructive' role='alert'>
              {error}
            </p>
          )}

          {rows.length === 0 ? (
            <p className='rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground'>
              没有符合条件的 Skill。
            </p>
          ) : (
            <>
              <div
                className='max-h-[36rem] overflow-auto overscroll-contain rounded-lg [scrollbar-gutter:stable]'
                role='region'
                aria-label='Skill 专属员工管理列表，每页最多 5 项'
              >
                <Table>
                  <caption className='sr-only'>Skill 专属员工管理列表</caption>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Skill</TableHead>
                      <TableHead>专属员工</TableHead>
                      <TableHead>员工状态</TableHead>
                      <TableHead className='text-right'>操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rowPage.items.map((skillId) => {
                      const skill = skillsById.get(skillId);
                      const dedication = dedicationBySkillId.get(skillId);
                      return (
                        <TableRow key={skillId}>
                          <TableCell>
                            <div className='min-w-40'>
                              <p className='font-medium'>{skill?.name ?? skillId}</p>
                              {skill?.name && (
                                <p className='text-xs text-muted-foreground'>{skillId}</p>
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            {dedication ? (
                              <span>{dedication.user_display_name}</span>
                            ) : (
                              <span className='text-muted-foreground'>未设置</span>
                            )}
                          </TableCell>
                          <TableCell>
                            {dedication ? (
                              <Badge
                                variant={
                                  dedication.user_status === 'disabled' ? 'destructive' : 'outline'
                                }
                              >
                                {dedication.user_status === 'disabled' ? '已停用' : '正常'}
                              </Badge>
                            ) : (
                              <span className='text-muted-foreground'>—</span>
                            )}
                          </TableCell>
                          <TableCell>
                            <div className='flex justify-end gap-2'>
                              <Button
                                type='button'
                                variant='outline'
                                size='sm'
                                onClick={() => openSet(skillId)}
                              >
                                {dedication ? <IconUserEdit /> : <IconPlus />}
                                {dedication ? '更换' : '设置'}
                              </Button>
                              {dedication && (
                                <Button
                                  type='button'
                                  variant='ghost'
                                  size='sm'
                                  onClick={() => openClear(skillId)}
                                >
                                  <IconTrash />
                                  清除
                                </Button>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
              <CollectionPaginationControls
                ariaLabel='Skill 专属员工管理列表'
                page={rowPage.page}
                pageCount={rowPage.pageCount}
                total={rowPage.total}
                onPageChange={rowPage.setPage}
              />
            </>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={Boolean(action)}
        onOpenChange={(open) => {
          if (!open && !busy) setAction(null);
        }}
      >
        <DialogContent>
          <form onSubmit={submit}>
            <DialogHeader>
              <DialogTitle>
                {action?.kind === 'clear' ? '清除专属员工' : '设置专属员工'}
              </DialogTitle>
              <DialogDescription>
                {action?.kind === 'clear'
                  ? `确认清除 ${action.skillId} 的专属员工标记？`
                  : `为 ${action?.skillId ?? ''} 选择当前部门的正常财务员工。`}
              </DialogDescription>
            </DialogHeader>
            {action?.kind === 'set' && (
              <label className='mt-4 grid gap-2 text-sm font-medium'>
                员工
                <select
                  value={selectedUserId}
                  onChange={(event) => setSelectedUserId(event.target.value)}
                  className='h-9 w-full rounded-lg border border-input bg-transparent px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50'
                  disabled={busy}
                  required
                >
                  <option value=''>请选择员工</option>
                  {usersForSelection.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <DialogFooter className='mt-4'>
              <Button
                type='button'
                variant='outline'
                onClick={() => setAction(null)}
                disabled={busy}
              >
                取消
              </Button>
              <Button
                type='submit'
                variant={action?.kind === 'clear' ? 'destructive' : 'default'}
                disabled={busy}
              >
                {busy ? '处理中…' : action?.kind === 'clear' ? '确认清除' : '保存设置'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
