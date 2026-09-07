'use client';

import { type FormEvent, useMemo, useState } from 'react';
import { IconHistory, IconPlus, IconShield, IconTrash, IconUserCog } from '@tabler/icons-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  CollectionPaginationControls,
  PaginatedCollection,
  useResponsiveCollectionPagination
} from '@/components/ui/collection-pagination';
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
  AuditEventPage,
  PlatformSession,
  SkillPermissionWrite,
  SkillSummary
} from '@/features/platform-api/types';
import { formatDate } from '@/lib/format';

interface PlatformUserManagementProps {
  session: PlatformSession;
  initialUsers: AdminUser[];
  skills: SkillSummary[];
  initialAuditPage: AuditEventPage;
  initialAuditFilters: AuditFilters;
  initialAuditTab: boolean;
}

interface AuditFilters {
  action: string;
  actorId: string;
  resourceType: string;
  resourceId: string;
  createdFrom: string;
  createdTo: string;
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
  'user.delete': '删除平台用户',
  'user.update': '更新平台用户'
};

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null;
  return body?.detail ?? fallback;
}

function auditDateQueryValue(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  const withSeconds = trimmed.length === 16 ? `${trimmed}:00` : trimmed;
  const parsed = new Date(`${withSeconds}+08:00`);
  return Number.isNaN(parsed.getTime()) ? trimmed : parsed.toISOString();
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
  initialAuditPage,
  initialAuditFilters,
  initialAuditTab
}: PlatformUserManagementProps) {
  const [users, setUsers] = useState(initialUsers);
  const [auditEvents, setAuditEvents] = useState(initialAuditPage.items ?? []);
  const [auditHasMore, setAuditHasMore] = useState(initialAuditPage.has_more);
  const [auditLoading, setAuditLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [notice, setNotice] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState('finance_user');
  const [status, setStatus] = useState('active');
  const [resetPassword, setResetPassword] = useState('');
  const [permissions, setPermissions] = useState<Record<string, PermissionState>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [auditAction, setAuditAction] = useState(initialAuditFilters.action);
  const [auditActor, setAuditActor] = useState(initialAuditFilters.actorId);
  const [auditResourceType, setAuditResourceType] = useState(initialAuditFilters.resourceType);
  const [auditResourceId, setAuditResourceId] = useState(initialAuditFilters.resourceId);
  const [auditCreatedFrom, setAuditCreatedFrom] = useState(initialAuditFilters.createdFrom);
  const [auditCreatedTo, setAuditCreatedTo] = useState(initialAuditFilters.createdTo);
  const usersById = useMemo(() => new Map(users.map((user) => [user.id, user])), [users]);
  const permissionPage = useResponsiveCollectionPagination(skills, {
    base: 5,
    md: 6,
    lg: 8
  });

  function openUser(user: AdminUser) {
    setSelected(user);
    setDisplayName(user.display_name);
    setRole(user.role);
    setStatus(user.status);
    setResetPassword('');
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

  async function deleteUser() {
    if (!deleteTarget || deleting) return;
    const target = deleteTarget;
    setDeleting(true);
    setDeleteError('');
    setNotice('');
    try {
      const response = await fetch(`/api/platform/admin/users/${encodeURIComponent(target.id)}`, {
        method: 'DELETE'
      });
      if (!response.ok) {
        setDeleteError(await responseMessage(response, '平台用户删除失败。'));
        return;
      }
      setUsers((current) => current.filter((user) => user.id !== target.id));
      setSelected((current) => current?.id === target.id ? null : current);
      setDeleteTarget(null);
      setNotice(`已删除用户 ${target.display_name}，历史记录已保留。`);
    } catch {
      setDeleteError('未能确认删除结果，请刷新用户列表后核对。');
    } finally {
      setDeleting(false);
    }
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

  async function loadAudit(reset = true) {
    setAuditLoading(true);
    setError('');
    const params = new URLSearchParams({ limit: '20' });
    if (auditAction.trim()) params.set('action', auditAction.trim());
    if (auditActor) params.set('actor_id', auditActor);
    if (auditResourceType.trim()) params.set('resource_type', auditResourceType.trim());
    if (auditResourceId.trim()) params.set('resource_id', auditResourceId.trim());
    if (auditCreatedFrom.trim()) params.set('created_from', auditDateQueryValue(auditCreatedFrom));
    if (auditCreatedTo.trim()) params.set('created_to', auditDateQueryValue(auditCreatedTo));
    if (!reset && auditEvents.length) params.set('before_id', String(auditEvents[auditEvents.length - 1].id));
    const response = await fetch(`/api/platform/admin/audit-events/page?${params}`);
    if (!response.ok) {
      setError(await responseMessage(response, '审计事件加载失败。'));
      setAuditLoading(false);
      return;
    }
    const page = (await response.json()) as AuditEventPage;
    setAuditEvents((current) =>
      reset
        ? page.items ?? []
        : [...current, ...(page.items ?? []).filter((item) => !current.some((row) => row.id === item.id))]
    );
    setAuditHasMore(page.has_more);
    setAuditLoading(false);
  }

  return (
    <>
      <Tabs defaultValue={initialAuditTab ? 'audit' : 'users'} className='space-y-4'>
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
          {notice && <p role='status' className='text-sm text-muted-foreground'>{notice}</p>}
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
          <PaginatedCollection
            ariaLabel='平台用户'
            contentClassName='grid gap-3 lg:grid-cols-2'
            responsivePageSize={{ base: 3, lg: 6 }}
          >
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
                    disabled={busy || deleting}
                    onClick={() => openUser(user)}
                  >
                    <IconUserCog />
                    管理账号与权限
                  </Button>
                  <Button
                    type='button'
                    variant='outline'
                    className='w-full text-destructive hover:text-destructive'
                    disabled={busy || deleting || user.id === session.user_id}
                    title={user.id === session.user_id ? '不能删除当前登录的管理员' : undefined}
                    aria-label={`删除用户 ${user.display_name}`}
                    onClick={() => {
                      setDeleteTarget(user);
                      setDeleteError('');
                    }}
                  >
                    <IconTrash />
                    删除用户
                  </Button>
                </CardContent>
              </Card>
            ))}
          </PaginatedCollection>
        </TabsContent>

        <TabsContent value='audit' className='space-y-4'>
          <Card>
            <CardContent className='grid gap-3 pt-4 md:grid-cols-2 xl:grid-cols-3'>
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
              <label htmlFor='audit-resource-type' className='grid gap-1 text-sm'>
                资源类型
                <Input
                  id='audit-resource-type'
                  value={auditResourceType}
                  onChange={(event) => setAuditResourceType(event.target.value)}
                  placeholder='例如 workflow 或 file'
                />
              </label>
              <label htmlFor='audit-resource-id' className='grid gap-1 text-sm'>
                任务或文件标识
                <Input
                  id='audit-resource-id'
                  value={auditResourceId}
                  onChange={(event) => setAuditResourceId(event.target.value)}
                />
              </label>
              <label htmlFor='audit-created-from' className='grid gap-1 text-sm'>
                开始时间（北京时间）
                <Input
                  id='audit-created-from'
                  type='datetime-local'
                  value={auditCreatedFrom}
                  onChange={(event) => setAuditCreatedFrom(event.target.value)}
                />
              </label>
              <label htmlFor='audit-created-to' className='grid gap-1 text-sm'>
                结束时间（北京时间）
                <Input
                  id='audit-created-to'
                  type='datetime-local'
                  value={auditCreatedTo}
                  onChange={(event) => setAuditCreatedTo(event.target.value)}
                />
              </label>
              <Button
                type='button'
                variant='outline'
                onClick={() => void loadAudit(true)}
                disabled={auditLoading}
              >
                {auditLoading ? '查询中…' : '查询'}
              </Button>
            </CardContent>
          </Card>
          {auditEvents.length ? (
            <PaginatedCollection ariaLabel='审计记录' contentClassName='space-y-2'>
              {auditEvents.map((event) => (
                <Card key={event.id}>
                  <CardContent className='grid gap-2 py-3 text-sm md:grid-cols-[13rem_1fr_auto] md:items-center'>
                    <div className='text-muted-foreground'>
                      {new Date(event.created_at).toLocaleString('zh-CN', {
                        hour12: false,
                        timeZone: 'Asia/Shanghai',
                        timeZoneName: 'short'
                      })}{' '}
                      （北京时间）
                    </div>
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
            </PaginatedCollection>
          ) : (
            <p className='text-sm text-muted-foreground'>当前条件下没有审计记录。</p>
          )}
          {auditHasMore && (
            <Button
              type='button'
              variant='outline'
              onClick={() => void loadAudit(false)}
              disabled={auditLoading}
            >
              {auditLoading ? '加载中…' : '加载更早记录'}
            </Button>
          )}
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

      <Dialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除用户 {deleteTarget?.display_name}</DialogTitle>
            <DialogDescription>
              确认删除账号 {deleteTarget?.username}？删除后将从用户列表移除，撤销登录会话和权限，
              并停止该用户的任务提醒。历史任务、文件和审计记录保留。
            </DialogDescription>
          </DialogHeader>
          <p className='text-sm text-muted-foreground'>
            删除后不能在此恢复，原用户名不能重新注册。有未结束任务时，请先完成或取消任务。
          </p>
          {deleteError && <p role='alert' className='text-sm text-destructive'>{deleteError}</p>}
          <DialogFooter>
            <Button type='button' variant='outline' disabled={deleting} onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button type='button' variant='destructive' disabled={deleting} onClick={() => void deleteUser()}>
              {deleting ? '删除中…' : '确认删除用户'}
            </Button>
          </DialogFooter>
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
                <div className='md:col-span-2'>
                  <Button type='button' onClick={() => void saveUser()} disabled={busy}>
                    {busy ? '保存中…' : '保存账号信息'}
                  </Button>
                </div>
                <div className='space-y-2 border-t pt-4 md:col-span-2'>
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
                </div>
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
                  <div
                    className='max-h-[36rem] overflow-auto overscroll-contain rounded-lg border [scrollbar-gutter:stable]'
                    role='region'
                    aria-label={`Skill 权限，每页最多 ${permissionPage.pageSize} 项`}
                  >
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
                        {permissionPage.items.map((skill) => {
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
                  <CollectionPaginationControls
                    ariaLabel='Skill 权限'
                    page={permissionPage.page}
                    pageCount={permissionPage.pageCount}
                    total={permissionPage.total}
                    onPageChange={permissionPage.setPage}
                  />
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
