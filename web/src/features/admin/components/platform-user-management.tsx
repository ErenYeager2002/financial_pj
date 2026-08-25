'use client';

import { type FormEvent, useMemo, useState } from 'react';
import { IconHistory, IconPlus, IconShield, IconUserCog } from '@tabler/icons-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type {
  AdminUser,
  AuditEvent,
  PlatformSession,
  SkillPermissionWrite,
  SkillSummary
} from '@/features/platform-api/types';
import { formatDate } from '@/lib/format';
import type { AuthMode } from '@/features/auth/auth-mode';

interface PlatformUserManagementProps {
  session: PlatformSession;
  initialUsers: AdminUser[];
  skills: SkillSummary[];
  initialAuditEvents: AuditEvent[];
  authMode: AuthMode;
}

type PermissionState = Required<Omit<SkillPermissionWrite, 'skill_id' | 'requires_approval'>> & {
  enabled: boolean;
};

const EMPTY_PERMISSION: PermissionState = {
  enabled: false,
  can_run: true,
  can_upload: true,
  can_create_draft: true
};

const ACTION_LABELS: Record<string, string> = {
  'admin.audit.read': '查看审计记录',
  'admin.approvals.read': '查看写入审批',
  'admin.skill_release_inbox.read': '查看 Skill 发布收件箱',
  'admin.skill_releases.read': '查看 Skill 发布记录',
  'admin.users.read': '查看用户列表',
  'assistant_profile.delete': '删除助手模型配置',
  'assistant_profile.update': '更新助手模型配置',
  'approval.approve': '批准写入任务',
  'approval.reject': '拒绝写入任务',
  'approval.request': '申请写入审批',
  'approval.revoke': '撤销写入审批',
  'user.password_reset': '重置一次性密码',
  'auth.login': '账号登录',
  'draft.confirm': '确认任务草稿',
  'draft.delete': '删除任务草稿',
  'draft.prepare': '生成任务草稿',
  'draft.update': '更新任务草稿',
  'file.delete': '删除文件',
  'file.download': '下载文件',
  'file.upload': '上传文件',
  'permission.replace': '更新 Skill 权限',
  'run.confirm': '确认任务',
  'run.create': '创建任务',
  'skill_release.import': '导入 Skill 发布包',
  'skill_release.metadata_update': '更新 Skill 业务元数据',
  'skill_release.publish': '发布 Skill 版本',
  'skill_release.review': '审核 Skill 版本',
  'skill_release.rollback': '回退 Skill 版本',
  'user.create': '创建平台用户',
  'user.update': '更新平台用户'
};

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null;
  return body?.detail ?? fallback;
}

function permissionsFor(user: AdminUser, skills: SkillSummary[]): Record<string, PermissionState> {
  const current = new Map((user.permissions ?? []).map((item) => [item.skill_id, item]));
  return Object.fromEntries(
    skills.map((skill) => {
      const item = current.get(skill.id);
      return [
        skill.id,
        item
          ? {
              enabled: true,
              can_run: item.can_run ?? true,
              can_upload: item.can_upload ?? true,
              can_create_draft: item.can_create_draft ?? true
            }
          : { ...EMPTY_PERMISSION }
      ];
    })
  );
}

export function PlatformUserManagement({
  session,
  initialUsers,
  skills,
  initialAuditEvents,
  authMode
}: PlatformUserManagementProps) {
  const [users, setUsers] = useState(initialUsers);
  const [auditEvents, setAuditEvents] = useState(initialAuditEvents);
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState('finance_user');
  const [status, setStatus] = useState('active');
  const [clerkUserId, setClerkUserId] = useState('');
  const [resetPassword, setResetPassword] = useState('');
  const [clerkOrganizationId, setClerkOrganizationId] = useState('');
  const [permissions, setPermissions] = useState<Record<string, PermissionState>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [auditAction, setAuditAction] = useState('');
  const [auditActor, setAuditActor] = useState('');
  const usersById = useMemo(() => new Map(users.map((user) => [user.id, user])), [users]);

  function openUser(user: AdminUser) {
    setSelected(user);
    setDisplayName(user.display_name);
    setRole(user.role);
    setStatus(user.status);
    setClerkUserId(user.clerk_user_id ?? '');
    setResetPassword('');
    setClerkOrganizationId(user.clerk_organization_id ?? '');
    setPermissions(permissionsFor(user, skills));
    setError('');
  }

  function replaceUser(updated: AdminUser) {
    setUsers((current) => current.map((user) => (user.id === updated.id ? updated : user)));
    setSelected(updated);
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const form = new FormData(event.currentTarget);
    const response = await fetch('/api/platform/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: form.get('username'),
        display_name: form.get('display_name'),
        initial_password: form.get('initial_password'),
        role: form.get('role')
      })
    });
    if (!response.ok) {
      setError(await responseMessage(response, '平台用户创建失败。'));
      setBusy(false);
      return;
    }
    const created = (await response.json()) as AdminUser;
    setUsers((current) => [...current, created]);
    setCreateOpen(false);
    setBusy(false);
  }

  async function saveUser() {
    if (!selected) return;
    setBusy(true);
    setError('');
    const response = await fetch(`/api/platform/admin/users/${encodeURIComponent(selected.id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        display_name: displayName,
        role,
        status,
        clerk_user_id: clerkUserId || null,
        clerk_organization_id: clerkOrganizationId || null
      })
    });
    if (!response.ok) {
      setError(await responseMessage(response, '平台用户更新失败。'));
      setBusy(false);
      return;
    }
    replaceUser((await response.json()) as AdminUser);
    setBusy(false);
  }

  async function resetOneTimePassword() {
    if (!selected) return;
    if (resetPassword.length < 8 || resetPassword.length > 256) {
      setError('一次性密码必须为 8 到 256 个字符。');
      return;
    }
    setBusy(true);
    setError('');
    const response = await fetch(
      `/api/platform/admin/users/${encodeURIComponent(selected.id)}/reset-password`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ initial_password: resetPassword })
      }
    );
    if (!response.ok) {
      setError(await responseMessage(response, '一次性密码重置失败。'));
      setBusy(false);
      return;
    }
    const updated = (await response.json()) as AdminUser;
    replaceUser(updated);
    setResetPassword('');
    setBusy(false);
  }

  function updatePermission(skillId: string, patch: Partial<PermissionState>) {
    setPermissions((current) => ({
      ...current,
      [skillId]: { ...(current[skillId] ?? EMPTY_PERMISSION), ...patch }
    }));
  }

  async function savePermissions() {
    if (!selected) return;
    setBusy(true);
    setError('');
    const rows = Object.entries(permissions)
      .filter(([, value]) => value.enabled)
      .map(([skillId, value]) => ({
        skill_id: skillId,
        can_run: value.can_run,
        can_upload: value.can_upload,
        can_create_draft: value.can_create_draft
      }));
    const response = await fetch(
      `/api/platform/admin/users/${encodeURIComponent(selected.id)}/skill-permissions`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ permissions: rows })
      }
    );
    if (!response.ok) {
      setError(await responseMessage(response, 'Skill 权限保存失败。'));
      setBusy(false);
      return;
    }
    const saved = (await response.json()) as AdminUser['permissions'];
    replaceUser({ ...selected, permissions: saved });
    setBusy(false);
  }

  async function loadAudit() {
    setBusy(true);
    setError('');
    const params = new URLSearchParams({ limit: '100' });
    if (auditAction.trim()) params.set('action', auditAction.trim());
    if (auditActor) params.set('actor_id', auditActor);
    const response = await fetch(`/api/platform/admin/audit-events?${params}`);
    if (!response.ok) {
      setError(await responseMessage(response, '审计事件加载失败。'));
      setBusy(false);
      return;
    }
    setAuditEvents((await response.json()) as AuditEvent[]);
    setBusy(false);
  }

  return (
    <>
      <Tabs defaultValue='users' className='space-y-4'>
        <TabsList>
          <TabsTrigger value='users'>
            <IconUserCog />
            平台用户
          </TabsTrigger>
          <TabsTrigger value='audit'>
            <IconHistory />
            审计记录
          </TabsTrigger>
        </TabsList>

        <TabsContent value='users' className='space-y-4'>
          <div className='flex items-center justify-between gap-3'>
            <p className='text-sm text-muted-foreground'>
              当前部门 {session.department_id}，共 {users.length} 个平台用户。
            </p>
            <Button
              type='button'
              onClick={() => {
                setError('');
                setCreateOpen(true);
              }}
            >
              <IconPlus />
              新增平台用户
            </Button>
          </div>
          <div className='grid gap-3 lg:grid-cols-2'>
            {users.map((user) => (
              <Card key={user.id}>
                <CardHeader className='pb-3'>
                  <div className='flex items-start justify-between gap-3'>
                    <div className='min-w-0'>
                      <CardTitle className='truncate text-base'>{user.display_name}</CardTitle>
                      <CardDescription className='truncate'>{user.username}</CardDescription>
                    </div>
                    <div className='flex gap-2'>
                      <Badge variant={user.status === 'active' ? 'default' : 'destructive'}>
                        {user.status === 'active' ? '启用' : '禁用'}
                      </Badge>
                      <Badge variant='outline'>
                        {user.role === 'skill_admin' ? '管理员' : '财务员工'}
                      </Badge>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className='space-y-3 text-sm'>
                  <div className='grid grid-cols-2 gap-3 text-muted-foreground'>
                    <span>Clerk：{user.clerk_user_id ? '已绑定' : '未绑定'}</span>
                    <span>
                      Skill：
                      {user.role === 'skill_admin' ? '全部' : `${user.permissions?.length ?? 0} 个`}
                    </span>
                  </div>
                  <Button
                    type='button'
                    variant='outline'
                    className='w-full'
                    onClick={() => openUser(user)}
                  >
                    <IconUserCog />
                    管理账号与权限
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value='audit' className='space-y-4'>
          <Card>
            <CardContent className='flex flex-wrap items-end gap-3 pt-4'>
              <label htmlFor='audit-action' className='grid min-w-56 flex-1 gap-1 text-sm'>
                动作
                <Input
                  id='audit-action'
                  value={auditAction}
                  onChange={(event) => setAuditAction(event.target.value)}
                  placeholder='例如 file.download'
                />
              </label>
              <label htmlFor='audit-actor' className='grid min-w-56 flex-1 gap-1 text-sm'>
                操作人
                <select
                  id='audit-actor'
                  value={auditActor}
                  onChange={(event) => setAuditActor(event.target.value)}
                  className='h-9 rounded-md border bg-background px-3'
                >
                  <option value=''>全部操作人</option>
                  {users.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                type='button'
                variant='outline'
                onClick={() => void loadAudit()}
                disabled={busy}
              >
                查询
              </Button>
            </CardContent>
          </Card>
          <div className='space-y-2'>
            {auditEvents.map((event) => (
              <Card key={event.id}>
                <CardContent className='grid gap-2 py-3 text-sm md:grid-cols-[11rem_1fr_auto] md:items-center'>
                  <div className='text-muted-foreground'>{formatDate(event.created_at)}</div>
                  <div>
                    <p className='font-medium'>{ACTION_LABELS[event.action] ?? event.action}</p>
                    <p className='text-xs text-muted-foreground'>
                      {(usersById.get(event.actor_id)?.display_name ?? event.actor_id) || '系统'} ·{' '}
                      {event.resource_type || '平台'}{' '}
                      {event.resource_id ? `· ${event.resource_id.slice(0, 12)}…` : ''}
                    </p>
                    {Object.keys(event.details ?? {}).length > 0 && (
                      <details className='mt-1 text-xs text-muted-foreground'>
                        <summary className='cursor-pointer'>查看脱敏详情</summary>
                        <pre className='mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-muted p-2'>
                          {JSON.stringify(event.details, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                  <Badge variant={event.outcome === 'success' ? 'outline' : 'destructive'}>
                    {event.outcome === 'success' ? '成功' : '失败'}
                  </Badge>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <form onSubmit={(event) => void createUser(event)} className='space-y-4'>
            <DialogHeader>
              <DialogTitle>新增平台用户</DialogTitle>
              <DialogDescription>
                创建本部门平台账号。初始密码只用于本地迁移登录，首次登录必须修改。
              </DialogDescription>
            </DialogHeader>
            <label htmlFor='create-username' className='grid gap-1 text-sm'>
              用户名
              <Input
                id='create-username'
                name='username'
                required
                maxLength={128}
                autoComplete='off'
              />
            </label>
            <label htmlFor='create-display-name' className='grid gap-1 text-sm'>
              显示名称
              <Input id='create-display-name' name='display_name' required maxLength={128} />
            </label>
            <label htmlFor='create-password' className='grid gap-1 text-sm'>
              初始密码
              <Input
                id='create-password'
                name='initial_password'
                type='password'
                required
                minLength={8}
                maxLength={256}
                autoComplete='new-password'
              />
            </label>
            <label htmlFor='create-role' className='grid gap-1 text-sm'>
              平台角色
              <select
                id='create-role'
                name='role'
                className='h-9 rounded-md border bg-background px-3'
              >
                <option value='finance_user'>财务员工</option>
                <option value='skill_admin'>Skill 管理员</option>
              </select>
            </label>
            {error && (
              <p role='alert' className='text-sm text-destructive'>
                {error}
              </p>
            )}
            <DialogFooter>
              <Button type='submit' disabled={busy}>
                {busy ? '创建中…' : '创建用户'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-4xl'>
          {selected && (
            <div className='space-y-5'>
              <DialogHeader>
                <DialogTitle>管理 {selected.display_name}</DialogTitle>
                <DialogDescription>
                  {selected.username} · {selected.department_id}
                </DialogDescription>
              </DialogHeader>
              <section className='grid gap-3 md:grid-cols-2'>
                <label htmlFor='edit-display-name' className='grid gap-1 text-sm'>
                  显示名称
                  <Input
                    id='edit-display-name'
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    maxLength={128}
                  />
                </label>
                <label htmlFor='edit-role' className='grid gap-1 text-sm'>
                  平台角色
                  <select
                    id='edit-role'
                    value={role}
                    onChange={(event) => setRole(event.target.value)}
                    className='h-9 rounded-md border bg-background px-3'
                  >
                    <option value='finance_user'>财务员工</option>
                    <option value='skill_admin'>Skill 管理员</option>
                  </select>
                </label>
                <label htmlFor='edit-status' className='grid gap-1 text-sm'>
                  账号状态
                  <select
                    id='edit-status'
                    value={status}
                    onChange={(event) => setStatus(event.target.value)}
                    className='h-9 rounded-md border bg-background px-3'
                  >
                    <option value='active'>启用</option>
                    <option value='disabled'>禁用</option>
                  </select>
                </label>
                <label htmlFor='edit-clerk-user' className='grid gap-1 text-sm'>
                  Clerk User ID
                  <Input
                    id='edit-clerk-user'
                    value={clerkUserId}
                    onChange={(event) => setClerkUserId(event.target.value)}
                    maxLength={128}
                    placeholder='留空表示不绑定'
                  />
                </label>
                <label htmlFor='edit-clerk-org' className='grid gap-1 text-sm md:col-span-2'>
                  Clerk Organization ID
                  <Input
                    id='edit-clerk-org'
                    value={clerkOrganizationId}
                    onChange={(event) => setClerkOrganizationId(event.target.value)}
                    maxLength={128}
                    placeholder='可选，用于限制组织'
                  />
                </label>
                <div className='md:col-span-2'>
                  <Button type='button' onClick={() => void saveUser()} disabled={busy}>
                    {busy ? '保存中…' : '保存账号信息'}
                  </Button>
                </div>
                {authMode !== 'clerk' && <div className='space-y-2 border-t pt-4 md:col-span-2'>
                  <h3 className='font-medium'>重置为一次性密码</h3>
                  <p className='text-sm text-muted-foreground'>
                    重置后立即撤销该用户的现有会话，并要求下次登录修改密码。审计记录不保存密码内容。
                  </p>
                  <div className='flex flex-col gap-2 sm:flex-row'>
                    <Input
                      type='password'
                      value={resetPassword}
                      onChange={(event) => setResetPassword(event.target.value)}
                      minLength={8}
                      maxLength={256}
                      autoComplete='new-password'
                      placeholder='输入一次性密码'
                    />
                    <Button
                      type='button'
                      variant='destructive'
                      disabled={busy || resetPassword.length < 8}
                      onClick={() => void resetOneTimePassword()}
                    >
                      重置密码并撤销会话
                    </Button>
                  </div>
                </div>}
              </section>

              {role === 'finance_user' ? (
                <section className='space-y-3 border-t pt-4'>
                  <div>
                    <h3 className='flex items-center gap-2 font-medium'>
                      <IconShield className='size-4' />
                      Skill 权限
                    </h3>
                    <p className='text-sm text-muted-foreground'>
                      默认不授权。只有选中的已发布 Skill 才能出现在员工目录中。
                    </p>
                  </div>
                  <div className='overflow-x-auto rounded-lg border'>
                    <table className='w-full min-w-3xl text-sm'>
                      <thead className='bg-muted/50 text-left'>
                        <tr>
                          <th className='p-2'>启用</th>
                          <th className='p-2'>Skill</th>
                          <th className='p-2'>运行</th>
                          <th className='p-2'>上传</th>
                          <th className='p-2'>建草稿</th>
                        </tr>
                      </thead>
                      <tbody>
                        {skills.map((skill) => {
                          const item = permissions[skill.id] ?? EMPTY_PERMISSION;
                          return (
                            <tr key={skill.id} className='border-t'>
                              <td className='p-2'>
                                <Checkbox
                                  aria-label={`授权 ${skill.name}`}
                                  checked={item.enabled}
                                  onCheckedChange={(checked) =>
                                    updatePermission(skill.id, { enabled: checked === true })
                                  }
                                />
                              </td>
                              <td className='p-2'>
                                <p className='font-medium'>{skill.name}</p>
                                <p className='text-xs text-muted-foreground'>{skill.id}</p>
                              </td>
                              {(['can_run', 'can_upload', 'can_create_draft'] as const).map(
                                (field) => (
                                  <td key={field} className='p-2'>
                                    <Checkbox
                                      aria-label={`${skill.name} ${field}`}
                                      checked={item[field]}
                                      disabled={!item.enabled}
                                      onCheckedChange={(checked) =>
                                        updatePermission(skill.id, { [field]: checked === true })
                                      }
                                    />
                                  </td>
                                )
                              )}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <Button type='button' onClick={() => void savePermissions()} disabled={busy}>
                    {busy ? '保存中…' : '保存 Skill 权限'}
                  </Button>
                </section>
              ) : (
                <p className='rounded-lg bg-muted p-3 text-sm'>
                  管理员默认拥有当前部门全部 Skill 管理权限，无需逐项授权。
                </p>
              )}
              {error && (
                <p role='alert' className='text-sm text-destructive'>
                  {error}
                </p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
