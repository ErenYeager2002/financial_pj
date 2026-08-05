import { ArrowRight, Bot, FileSpreadsheet, LoaderCircle, Search, ShieldCheck } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { SkillManifest } from '../types'

export function SkillList() {
  const [searchParams] = useSearchParams()
  const [skills, setSkills] = useState<SkillManifest[]>([])
  const [query, setQuery] = useState(() => searchParams.get('search') || '')
  const [category, setCategory] = useState('全部')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.skills().then(setSkills).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    setQuery(searchParams.get('search') || '')
  }, [searchParams])

  const categories = ['全部', ...new Set(skills.map((item) => item.category))]
  const filtered = useMemo(
    () =>
      skills.filter((item) => {
        const categoryMatch = category === '全部' || item.category === category
        const text = `${item.name}${item.description}${item.tags.join('')}`.toLowerCase()
        return categoryMatch && text.includes(query.toLowerCase())
      }),
    [category, query, skills],
  )

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <span className="eyebrow">工具目录</span>
          <h2>选择一项财务工作</h2>
          <p>普通用户可以运行所有已发布 Skill，但不能修改其业务规则和执行程序。</p>
        </div>
        <div className="trust-pill"><ShieldCheck size={17} /> 已发布版本只读执行</div>
      </div>

      <div className="filter-bar">
        <label className="search-box">
          <Search size={18} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索 Skill、场景或关键词"
          />
        </label>
        <div className="filter-tabs" role="tablist">
          {categories.map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={category === item}
              className={category === item ? 'active' : ''}
              onClick={() => setCategory(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="loading-screen">
          <LoaderCircle className="spin" size={20} /> 正在读取财务工具…
        </div>
      )}
      {!loading && <div className="skill-grid">
        {filtered.map((skill) => (
          <article className="skill-card" key={skill.id}>
            <div className="skill-card-top">
              <div className="skill-icon">
                {['rpa', 'workflow'].includes(skill.handler.adapter)
                  ? <Bot size={22} />
                  : <FileSpreadsheet size={22} />}
              </div>
              <span className={`risk-chip risk-${skill.risk.level}`}>
                {skill.risk.level === 'read_only' ? '只读' : '执行前确认'}
              </span>
            </div>
            <div className="skill-card-body">
              <span className="skill-category">{skill.category}</span>
              <h3>{skill.name}</h3>
              <p>{skill.description}</p>
              <div className="tag-row">
                {skill.tags.slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}
              </div>
            </div>
            <div className="skill-card-footer">
              <span>{skill.handler.adapter.toUpperCase()} · v{skill.version}</span>
              <Link to={`/skills/${skill.id}`}>
                使用工具 <ArrowRight size={16} />
              </Link>
            </div>
          </article>
        ))}
      </div>}
      {!loading && !filtered.length && (
        <div className="empty-state">
          <Search size={28} />
          <h3>没有找到匹配的 Skill</h3>
          <p>尝试调整关键词或分类。</p>
        </div>
      )}
    </div>
  )
}
