import {
  GitBranch,
  RefreshCcw,
  Save,
  ShieldCheck,
  TriangleAlert,
  UserPlus,
  Users,
} from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { AdminUser, SkillManifest, SkillPermission } from '../types'

const emptyUser = { username: '', display_name: '', initial_password: '' }

export function Admin() {
  const [skills, setSkills] = useState<SkillManifest[]>([])
  const [users, setUsers] = useState<AdminUser[]>([])
  const [selectedUserId, setSelectedUserId] = useState('')
  const [permissions, setPermissions] = useState<Record<string, SkillPermission>>({})
  const [newUser, setNewUser] = useState(emptyUser)
  const [message, setMessage] = useState('')
  const [errors, setErrors] = useState<Array<{ path: string; error: string }>>([])
  const [saving, setSaving] = useState(false)

  const publishedSkills = useMemo(
    () => skills.filter((skill) => skill.status === 'published'),
    [skills],
  )
  const selectedUser = users.find((user) => user.id === selectedUserId)

  const load = async () => {
    const [skillItems, userItems] = await Promise.all([api.skills(), api.adminUsers()])
    setSkills(skillItems)
    setUsers(userItems)
    setSelectedUserId(
      (current) => current || userItems.find((item) => item.role === 'finance_user')?.id || '',
    )
  }

  useEffect(() => {
    load().catch((reason) => setMessage((reason as Error).message))
  }, [])

  useEffect(() => {
    const user = users.find((item) => item.id === selectedUserId)
    setPermissions(
      Object.fromEntries((user?.permissions || []).map((item) => [item.skill_id, item])),
    )
  }, [selectedUserId, users])

  const reload = async () => {
    try {
      const result = await api.reloadRegistry()
      setErrors(result.errors)
      setMessage(`Registry 已重新加载，共发现 ${result.skills} 个 Skill。`)
      await load()
    } catch (reason) {
      setMessage((reason as Error).message)
    }
  }

  const createEmployee = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setMessage('')
    try {
      const created = await api.createAdminUser({
        ...newUser,
        role: 'finance_user',
        department_id: 'finance',
      })
      setNewUser(emptyUser)
      await load()
      setSelectedUserId(created.id)
      setMessage(`员工 ${created.display_name} 已创建，首次登录必须修改初始密码。`)
    } catch (reason) {
      setMessage((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const toggleSkill = (skillId: string, enabled: boolean) => {
    setPermissions((current) => {
      if (!enabled) {
        const next = { ...current }
        delete next[skillId]
        return next
      }
      return {
        ...current,
        [skillId]: {
          skill_id: skillId,
          can_run: true,
          can_upload: true,
          can_create_draft: true,
          requires_approval: false,
        },
      }
    })
  }

  const savePermissions = async () => {
    if (!selectedUser) return
    setSaving(true)
    try {
      await api.replaceSkillPermissions(selectedUser.id, Object.values(permissions))
      await load()
      setMessage(`${selectedUser.display_name} 的工具权限已更新。`)
    } catch (reason) {
      setMessage((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const toggleUserStatus = async () => {
    if (!selectedUser) return
    setSaving(true)
    try {
      const status = selectedUser.status === 'active' ? 'disabled' : 'active'
      await api.updateAdminUser(selectedUser.id, { status })
      await load()
      setMessage(`${selectedUser.display_name} 已${status === 'active' ? '启用' : '禁用'}。`)
    } catch (reason) {
      setMessage((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <span className="eyebrow">员工与 SKILL 管理</span>
          <h2>员工权限</h2>
          <p>员工默认没有工具权限。创建账号后，需要在这里逐项授权。</p>
        </div>
        <button className="button button-primary" onClick={reload}>
          <RefreshCcw size={16} /> 重新扫描 Registry
        </button>
      </div>

      {message && <div className="alert alert-info"><ShieldCheck size={18} />{message}</div>}
      {errors.map((item) => (
        <div className="alert alert-error" role="alert" key={item.path}>
          <TriangleAlert size={18} />{item.path}：{item.error}
        </div>
      ))}

      <div className="split-grid">
        <form className="model-connection-card" onSubmit={createEmployee}>
          <div className="section-heading"><h2><UserPlus size={18} /> 新增员工</h2></div>
          <label className="field">
            <span>用户名</span>
            <input value={newUser.username} onChange={(event) => setNewUser({ ...newUser, username: event.target.value })} required pattern="[A-Za-z0-9_.-]+" />
          </label>
          <label className="field">
            <span>员工姓名</span>
            <input value={newUser.display_name} onChange={(event) => setNewUser({ ...newUser, display_name: event.target.value })} required />
          </label>
          <label className="field">
            <span>初始密码</span>
            <input type="password" minLength={8} autoComplete="new-password" value={newUser.initial_password} onChange={(event) => setNewUser({ ...newUser, initial_password: event.target.value })} required />
          </label>
          <button className="button button-primary" type="submit" disabled={saving}>
            <UserPlus size={16} /> 创建员工
          </button>
        </form>

        <section className="model-connection-card">
          <div className="section-heading"><h2><Users size={18} /> 工具授权</h2></div>
          <label className="field">
            <span>选择员工</span>
            <select value={selectedUserId} onChange={(event) => setSelectedUserId(event.target.value)}>
              <option value="">请选择员工</option>
              {users.filter((user) => user.role === 'finance_user').map((user) => (
                <option key={user.id} value={user.id}>{user.display_name}（{user.username}）· {user.status === 'active' ? '启用' : '禁用'}</option>
              ))}
            </select>
          </label>
          {selectedUser ? (
            <>
              <div style={{ display: 'grid', gap: 8, maxHeight: 420, overflowY: 'auto' }}>
                {publishedSkills.map((skill) => (
                  <label key={skill.id} style={{ display: 'grid', gridTemplateColumns: '20px 1fr', gap: 10, padding: 10, border: '1px solid var(--border-soft)', borderRadius: 10 }}>
                    <input type="checkbox" checked={Boolean(permissions[skill.id])} onChange={(event) => toggleSkill(skill.id, event.target.checked)} />
                    <span><strong>{skill.name}</strong><small style={{ display: 'block' }}>{skill.description}</small></span>
                  </label>
                ))}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                <button className="button button-secondary" type="button" onClick={toggleUserStatus} disabled={saving}>
                  {selectedUser.status === 'active' ? '禁用账号' : '启用账号'}
                </button>
                <button className="button button-primary" type="button" onClick={savePermissions} disabled={saving}>
                  <Save size={16} /> 保存权限
                </button>
              </div>
            </>
          ) : <p>先创建或选择一个员工账号。</p>}
        </section>
      </div>

      <div className="table-panel">
        <table>
          <thead><tr><th>Skill</th><th>分类</th><th>版本</th><th>状态</th><th>执行器</th><th>来源</th><th>Commit</th></tr></thead>
          <tbody>
            {skills.map((skill) => (
              <tr key={skill.id}>
                <td><strong>{skill.name}</strong><small>{skill.id}</small>{skill.blocked_reason && <small>{skill.blocked_reason}</small>}</td>
                <td>{skill.category}</td>
                <td>v{skill.version}</td>
                <td><span className={`publish-state ${skill.status}`}>{skill.status}</span></td>
                <td>{skill.handler?.adapter.toUpperCase() || '—'}</td>
                <td>{skill.source || '—'}</td>
                <td><span className="commit"><GitBranch size={14} />{skill.commit_sha?.slice(0, 10) || '未提交'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
