import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileSpreadsheet,
  LoaderCircle,
  PlayCircle,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import type { RunRecord, SkillManifest } from '../types'

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function Dashboard() {
  const [skills, setSkills] = useState<SkillManifest[]>([])
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([api.skills(), api.runs()])
      .then(([skillData, runData]) => {
        setSkills(skillData.filter((item) => item.status === 'published'))
        setRuns(runData)
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false))
  }, [])

  const metrics = useMemo(() => {
    const succeeded = runs.filter((item) => item.state === 'succeeded').length
    const attention = runs.filter((item) =>
      ['failed', 'timed_out', 'waiting_user_action', 'waiting_confirmation'].includes(item.state),
    ).length
    const active = runs.filter((item) => ['queued', 'running'].includes(item.state)).length
    return { succeeded, attention, active }
  }, [runs])

  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div className="hero-copy">
          <span className="hero-kicker">确定性执行 · 全程留痕</span>
          <h2>把重复财务工作交给 Skill，<br />把判断留给财务人员。</h2>
          <p>
            选择工具、上传文件并说明口径。平台会固定 Skill 版本、校验参数，
            再交给隔离 Worker 执行。
          </p>
          <div className="hero-actions">
            <Link className="button button-primary" to="/skills">
              开始一项任务 <ArrowRight size={17} />
            </Link>
            <Link className="button button-secondary" to="/runs">
              查看运行记录
            </Link>
          </div>
        </div>
        <div className="hero-status" aria-label="平台运行方式">
          <div className="status-step active">
            <span>01</span>
            <div><strong>理解要求</strong><small>模型只提取参数</small></div>
          </div>
          <div className="status-rail" />
          <div className="status-step active">
            <span>02</span>
            <div><strong>确定性执行</strong><small>Python / RPA / API</small></div>
          </div>
          <div className="status-rail" />
          <div className="status-step">
            <span>03</span>
            <div><strong>人工复核</strong><small>下载结果与差异</small></div>
          </div>
        </div>
      </section>

      {error && <div className="alert alert-error" role="alert"><TriangleAlert size={18} />{error}</div>}

      <section className="metric-grid" aria-label="运行概览">
        <article className="metric-card">
          <div className="metric-icon metric-blue"><FileSpreadsheet size={20} /></div>
          <div><span>已发布 Skill</span><strong>{loading ? '—' : skills.length}</strong><small>部门可直接使用</small></div>
        </article>
        <article className="metric-card">
          <div className="metric-icon metric-amber"><Clock3 size={20} /></div>
          <div><span>正在处理</span><strong>{loading ? '—' : metrics.active}</strong><small>排队或执行中</small></div>
        </article>
        <article className="metric-card">
          <div className="metric-icon metric-green"><CheckCircle2 size={20} /></div>
          <div><span>成功完成</span><strong>{loading ? '—' : metrics.succeeded}</strong><small>历史运行次数</small></div>
        </article>
        <article className="metric-card">
          <div className="metric-icon metric-red"><TriangleAlert size={20} /></div>
          <div><span>需要关注</span><strong>{loading ? '—' : metrics.attention}</strong><small>失败或等待人工</small></div>
        </article>
      </section>

      <section className="split-grid">
        <div className="surface-panel">
          <div className="section-heading">
            <div><span className="eyebrow">快捷入口</span><h2>常用财务工具</h2></div>
            <Link to="/skills">全部工具 <ArrowRight size={15} /></Link>
          </div>
          <div className="skill-quick-grid">
            {skills.slice(0, 4).map((skill) => (
              <Link key={skill.id} className="quick-skill" to={`/skills/${skill.id}`}>
                <div className="quick-skill-icon"><FileSpreadsheet size={20} /></div>
                <div>
                  <strong>{skill.name}</strong>
                  <span>{skill.description}</span>
                  <small>{skill.handler.adapter.toUpperCase()} · v{skill.version}</small>
                </div>
                <ArrowRight size={17} />
              </Link>
            ))}
            {loading && <div className="empty-inline"><LoaderCircle className="spin" size={17} /> 正在读取工具…</div>}
            {!loading && !skills.length && <div className="empty-inline">暂无已发布 Skill。</div>}
          </div>
        </div>

        <div className="surface-panel">
          <div className="section-heading">
            <div><span className="eyebrow">任务动态</span><h2>最近运行</h2></div>
          </div>
          <div className="recent-list">
            {runs.slice(0, 5).map((run) => (
              <Link key={run.id} to={`/runs/${run.id}`} className="recent-row">
                <div className="run-glyph"><PlayCircle size={18} /></div>
                <div className="recent-main">
                  <strong>{run.skill_name}</strong>
                  <span>{formatTime(run.created_at)} · {run.owner_name}</span>
                </div>
                <StatusBadge state={run.state} />
              </Link>
            ))}
            {loading && <div className="empty-inline"><LoaderCircle className="spin" size={17} /> 正在读取任务…</div>}
            {!loading && !runs.length && <div className="empty-inline">还没有运行记录。</div>}
          </div>
        </div>
      </section>
    </div>
  )
}
