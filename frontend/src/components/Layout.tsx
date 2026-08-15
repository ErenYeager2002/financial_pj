import {
  ArrowRight,
  Activity,
  Blocks,
  Command,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  Search,
  Settings2,
  Sparkles,
  Sun,
  X,
} from 'lucide-react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { PlatformHealth, RunRecord, SkillManifest, UserSession, WorkflowRecord } from '../types'

const TITLES: Record<string, string> = {
  '/': '工作概览',
  '/skills': '财务工具',
  '/runs': '运行记录',
  '/workflows': '对话任务',
  '/admin': 'Skill 管理',
}

export function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  const [session, setSession] = useState<UserSession | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [theme, setTheme] = useState<'dark' | 'light'>(() =>
    (localStorage.getItem('financial-theme') as 'dark' | 'light') || 'dark',
  )
  const [quickSkills, setQuickSkills] = useState<Array<{ skill: SkillManifest; uses: number }>>([])
  const [globalQuery, setGlobalQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchSkills, setSearchSkills] = useState<SkillManifest[]>([])
  const [searchRuns, setSearchRuns] = useState<RunRecord[]>([])
  const [searchWorkflows, setSearchWorkflows] = useState<WorkflowRecord[]>([])
  const [health, setHealth] = useState<PlatformHealth | null>(null)
  const searchRef = useRef<HTMLDivElement>(null)
  const role = session?.role || 'finance_user'

  useEffect(() => {
    api.session().then(setSession).catch(() => setSession(null))
  }, [location.pathname])

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [skills, runs, workflows, platformHealth] = await Promise.all([
          api.skills(),
          api.runs(),
          api.workflows(),
          api.health(),
        ])
        if (!active) return
        const published = skills.filter((skill) => (skill.status ?? 'published') === 'published')
        const usage = new Map<string, number>()
        runs.forEach((run) => usage.set(run.skill_id, (usage.get(run.skill_id) || 0) + 1))
        workflows.forEach((workflow) => usage.set(workflow.skill_id, (usage.get(workflow.skill_id) || 0) + 1))
        setQuickSkills(
          published
            .map((skill) => ({ skill, uses: usage.get(skill.id) || 0 }))
            .sort((a, b) => b.uses - a.uses || a.skill.name.localeCompare(b.skill.name, 'zh-CN'))
            .slice(0, 3),
        )
        setSearchSkills(published)
        setSearchRuns(runs)
        setSearchWorkflows(workflows)
        setHealth(platformHealth)
      } catch {
        if (active) {
          setQuickSkills([])
          setHealth(null)
        }
      }
    }
    load()
    const timer = window.setInterval(load, 5000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('financial-theme', theme)
  }, [theme])

  useEffect(() => {
    setNavOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!searchOpen) return
    const closeOnOutside = (event: MouseEvent) => {
      if (!searchRef.current?.contains(event.target as Node)) setSearchOpen(false)
    }
    window.addEventListener('mousedown', closeOnOutside)
    return () => window.removeEventListener('mousedown', closeOnOutside)
  }, [searchOpen])

  const title =
    Object.entries(TITLES).find(([path]) =>
      path === '/' ? location.pathname === '/' : location.pathname.startsWith(path),
    )?.[1] || '任务详情'

  const searchResults = useMemo(() => {
    const query = globalQuery.trim().toLowerCase()
    if (!query) return []
    const results: Array<{ id: string; label: string; detail: string; href: string }> = []
    searchSkills
      .filter((skill) => `${skill.name}${skill.description}${skill.tags.join('')}`.toLowerCase().includes(query))
      .slice(0, 3)
      .forEach((skill) => results.push({ id: `skill-${skill.id}`, label: skill.name, detail: '财务工具', href: `/skills/${skill.id}` }))
    searchRuns
      .filter((run) => JSON.stringify(run).toLowerCase().includes(query))
      .slice(0, 3)
      .forEach((run) => results.push({ id: `run-${run.id}`, label: run.skill_name, detail: `任务 · ${run.owner_name}`, href: `/runs/${run.id}` }))
    searchWorkflows
      .filter((workflow) => JSON.stringify(workflow).toLowerCase().includes(query))
      .slice(0, 3)
      .forEach((workflow) => results.push({ id: `workflow-${workflow.id}`, label: workflow.skill_name, detail: '工作流任务', href: `/workflows/${workflow.id}` }))
    return results.slice(0, 6)
  }, [globalQuery, searchRuns, searchSkills, searchWorkflows])

  const submitGlobalSearch = () => {
    const query = globalQuery.trim()
    if (!query) return
    setSearchOpen(false)
    navigate(searchResults[0]?.href || `/skills?search=${encodeURIComponent(query)}`)
  }

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
          <span className="nav-section">核心工作台</span>
          <NavLink to="/" end>
            <LayoutDashboard size={18} /> 工作概览
          </NavLink>
          <NavLink to="/skills">
            <Blocks size={18} /> 财务工具
          </NavLink>
          <NavLink to="/runs">
            <ListChecks size={18} /> 运行记录
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

        <div className="sidebar-shortcuts">
          <span className="nav-section">快捷入口</span>
          {quickSkills.length > 0 ? quickSkills.map((skill) => (
            <NavLink key={skill.skill.id} to={`/skills/${skill.skill.id}`} title={`${skill.skill.name} · 使用 ${skill.uses} 次`}>
              <Blocks size={17} /> <span className="sidebar-shortcut-label">{skill.skill.name}</span><small>{skill.uses}</small>
            </NavLink>
          )) : (
            <span className="sidebar-shortcuts-empty">正在读取已发布 Skill…</span>
          )}
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
            <div className="global-search" ref={searchRef}>
              <label className="command-search">
                <Search size={15} />
                <input
                  aria-label="搜索 Skill、任务、文件、人员"
                  placeholder="搜索 Skill、任务、文件、人员"
                  value={globalQuery}
                  onChange={(event) => { setGlobalQuery(event.target.value); setSearchOpen(true) }}
                  onFocus={() => setSearchOpen(true)}
                  onKeyDown={(event) => { if (event.key === 'Enter') submitGlobalSearch() }}
                />
                <kbd><Command size={12} /> K</kbd>
              </label>
              {searchOpen && globalQuery.trim() && (
                <div className="global-search-results" role="listbox" aria-label="搜索结果">
                  {searchResults.length ? searchResults.map((result) => (
                    <Link key={result.id} to={result.href} onClick={() => setSearchOpen(false)}>
                      <Search size={14} /><span><strong>{result.label}</strong><small>{result.detail}</small></span><ArrowRight size={14} />
                    </Link>
                  )) : <div className="global-search-empty">没有匹配的 Skill、任务或文件</div>}
                  <button type="button" onClick={submitGlobalSearch}>查看全部搜索结果 <Command size={12} /> Enter</button>
                </div>
              )}
            </div>
            <span className={`service-health ${health?.status !== 'ok' ? 'is-degraded' : ''}`}>
              <Activity size={15} />
              {health?.status === 'ok' ? '平台正常' : health ? '平台异常' : '连接中…'}
            </span>
            <button
              className="theme-toggle"
              type="button"
              aria-label={theme === 'dark' ? '切换白天模式' : '切换夜间模式'}
              title={theme === 'dark' ? '白天模式' : '夜间模式'}
              onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <div className="identity-badge" aria-label={role === 'skill_admin' ? '当前为管理员端' : '当前为财务员工端'}>
              <span className="role-avatar">{role === 'skill_admin' ? '管' : '财'}</span>
              <span className="role-copy">
                <strong>{session?.display_name || (role === 'skill_admin' ? 'Skill 管理员' : '财务员工')}</strong>
                <small>{role === 'skill_admin' ? '平台管理权限' : '财务部 · 普通权限'}</small>
              </span>
              <button
                className="logout-button"
                type="button"
                aria-label="退出登录"
                title="退出登录"
                onClick={async () => {
                  try {
                    await api.logout()
                  } finally {
                    navigate('/login', { replace: true })
                  }
                }}
              >
                <LogOut size={15} />
              </button>
            </div>
          </div>
        </header>
        <div className="content-area" id="main-content" tabIndex={-1}>
          <Outlet />
        </div>
      </main>
    </div>
  )
}
