import {
  Activity,
  Blocks,
  Bot,
  ChevronDown,
  LayoutDashboard,
  ListChecks,
  Menu,
  Settings2,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api, getRole, setRole } from '../api'
import type { UserRole, UserSession } from '../types'

const TITLES: Record<string, string> = {
  '/': '工作概览',
  '/skills': '财务工具',
  '/runs': '运行记录',
  '/workflows': '对话任务',
  '/models': '模型接入',
  '/admin': 'Skill 管理',
}

export function Layout() {
  const location = useLocation()
  const [session, setSession] = useState<UserSession | null>(null)
  const [role, setCurrentRole] = useState<UserRole>(getRole())
  const [navOpen, setNavOpen] = useState(false)

  useEffect(() => {
    api.session().then(setSession).catch(() => setSession(null))
  }, [role])

  useEffect(() => {
    setNavOpen(false)
  }, [location.pathname])

  const changeRole = (next: UserRole) => {
    setRole(next)
    setCurrentRole(next)
  }

  const title =
    Object.entries(TITLES).find(([path]) =>
      path === '/' ? location.pathname === '/' : location.pathname.startsWith(path),
    )?.[1] || '任务详情'

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className={`sidebar ${navOpen ? 'sidebar-open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">
            <Sparkles size={20} strokeWidth={1.8} />
          </div>
          <div>
            <strong>Finance Skills</strong>
            <span>财务数字员工平台</span>
          </div>
          <button
            className="sidebar-close"
            type="button"
            aria-label="关闭导航"
            onClick={() => setNavOpen(false)}
          >
            <X size={20} />
          </button>
        </div>

        <nav className="side-nav" aria-label="主导航">
          <span className="nav-section">日常工作</span>
          <NavLink to="/" end>
            <LayoutDashboard size={18} /> 工作概览
          </NavLink>
          <NavLink to="/skills">
            <Blocks size={18} /> 财务工具
          </NavLink>
          <NavLink to="/runs">
            <ListChecks size={18} /> 运行记录
          </NavLink>
          <NavLink to="/models">
            <Bot size={18} /> 模型接入
          </NavLink>
          {role === 'skill_admin' && (
            <>
              <span className="nav-section">平台管理</span>
              <NavLink to="/admin">
                <Settings2 size={18} /> Skill 管理
              </NavLink>
            </>
          )}
        </nav>

        <div className="sidebar-trust">
          <ShieldCheck size={18} />
          <div>
            <strong>部门内网运行</strong>
            <span>文件不会进入 GitHub</span>
          </div>
        </div>
      </aside>
      {navOpen && (
        <button
          className="sidebar-scrim"
          type="button"
          aria-label="关闭导航"
          onClick={() => setNavOpen(false)}
        />
      )}

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-leading">
            <button
              className="mobile-menu-button"
              type="button"
              aria-label="打开导航"
              aria-expanded={navOpen}
              onClick={() => setNavOpen(true)}
            >
              <Menu size={20} />
            </button>
            <div>
              <span className="eyebrow">财务工作台</span>
              <h1>{title}</h1>
            </div>
          </div>
          <div className="topbar-actions">
            <span className="service-health">
              <Activity size={15} />
              服务正常
            </span>
            <label className="role-switch">
              <span className="avatar">{role === 'skill_admin' ? '管' : '财'}</span>
              <span className="role-copy">
                <strong>{session?.display_name || '财务员工'}</strong>
                <small>{role === 'skill_admin' ? 'Skill 管理员' : '财务部'}</small>
              </span>
              <select
                aria-label="切换演示角色"
                value={role}
                onChange={(event) => changeRole(event.target.value as UserRole)}
              >
                <option value="finance_user">财务员工</option>
                <option value="skill_admin">Skill 管理员</option>
              </select>
              <ChevronDown size={15} aria-hidden="true" />
            </label>
          </div>
        </header>
        <div className="content-area" id="main-content" tabIndex={-1}>
          <Outlet />
        </div>
      </main>
    </div>
  )
}
