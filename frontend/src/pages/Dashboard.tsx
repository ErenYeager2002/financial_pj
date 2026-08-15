import {
  ArrowRight,
  Check,
  CheckCircle2,
  CircleDot,
  Clock3,
  FileSpreadsheet,
  LoaderCircle,
  Play,
  RefreshCw,
  Search,
  TriangleAlert,
  UploadCloud,
  X,
} from 'lucide-react'
import { ChangeEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import { SelectMenu } from '../components/SelectMenu'
import type { RunRecord, SkillManifest, UploadedFile, WorkflowBatchRecord, WorkflowRecord } from '../types'

type ConsoleTask = {
  id: string
  priority: string
  name: string
  skill: string
  file: string
  state: string
  progress: number
  owner: string
  team: string
  time: string
  href: string
  recordId: string
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function fileLabel(files: Record<string, unknown>) {
  const first = Object.values(files || {})[0]
  const candidate = Array.isArray(first) ? first[0] : first
  if (candidate && typeof candidate === 'object' && 'name' in candidate) return String((candidate as { name?: string }).name || '任务输入文件')
  return typeof candidate === 'string' ? candidate : '任务输入文件'
}

function runToTask(run: RunRecord): ConsoleTask {
  return {
    id: `REQ-${run.id.slice(0, 8).toUpperCase()}`,
    priority: run.confirmation_required ? 'P1' : 'P2',
    name: run.skill_name,
    skill: run.skill_name,
    file: fileLabel(run.files || {}),
    state: run.state,
    progress: run.progress,
    owner: run.owner_name,
    team: '财务部',
    time: formatTime(run.created_at),
    href: `/runs/${run.id}`,
    recordId: run.id,
  }
}

function workflowToTask(workflow: WorkflowRecord): ConsoleTask {
  const state = workflow.stage === 'awaiting_apply_confirmation'
    ? 'waiting_confirmation'
    : workflow.stage === 'completed'
      ? 'succeeded'
      : workflow.stage === 'failed'
        ? 'failed'
        : workflow.stage === 'preparing'
          ? 'preparing'
          : workflow.state
  return {
    id: `WF-${workflow.id.slice(0, 8).toUpperCase()}`,
    priority: workflow.state === 'failed' ? 'P1' : 'P2',
    name: workflow.skill_name,
    skill: workflow.skill_name,
    file: Object.values(workflow.files || {})[0]?.[0]?.name || '工作流输入文件',
    state,
    progress: workflow.progress,
    owner: '当前用户',
    team: '财务部',
    time: formatTime(workflow.updated_at),
    href: `/workflows/${workflow.id}`,
    recordId: workflow.id,
  }
}

function batchToTask(batch: WorkflowBatchRecord): ConsoleTask {
  return {
    id: batch.id,
    priority: batch.state === 'failed' ? 'P1' : 'P2',
    name: `${batch.skill_name} · ${batch.reconciliation_dates.length} 天`,
    skill: batch.skill_name,
    file: batch.reconciliation_dates.join('、'),
    state: batch.state,
    progress: batch.progress,
    owner: '当前用户',
    team: '财务部',
    time: formatTime(batch.updated_at),
    href: `/workflow-batches/${batch.id}`,
    recordId: batch.id,
  }
}

export function Dashboard() {
  const [skills, setSkills] = useState<SkillManifest[]>([])
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([])
  const [batches, setBatches] = useState<WorkflowBatchRecord[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('all')
  const [skillFilter, setSkillFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [selectedSkill, setSelectedSkill] = useState('')
  const [note, setNote] = useState('')
  const [files, setFiles] = useState<string[]>([])

  useEffect(() => {
    let active = true
    const load = () => Promise.all([api.skills(), api.runs(), api.workflows(), api.workflowBatches()])
      .then(([skillData, runData, workflowData, batchData]) => {
        if (!active) return
        const published = skillData.filter((item) => (item.status ?? 'published') === 'published')
        setSkills(published)
        setSelectedSkill((current) => current || published[0]?.id || '')
        setRuns(runData)
        setWorkflows(workflowData)
        setBatches(batchData)
      })
      .catch((reason: Error) => { if (active) setError(reason.message) })
      .finally(() => { if (active) setLoading(false) })
    load()
    const timer = window.setInterval(load, 5000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  const metrics = useMemo(() => {
    const all = [...runs.map((item) => ({ state: item.state, created_at: item.created_at, started_at: item.started_at, finished_at: item.finished_at })), ...workflows.map((item) => ({ state: workflowToTask(item).state, created_at: item.created_at, started_at: item.created_at, finished_at: ['completed', 'failed'].includes(item.stage) ? item.updated_at : undefined })), ...batches.map((item) => ({ state: item.state, created_at: item.created_at, started_at: item.created_at, finished_at: ['succeeded', 'failed'].includes(item.state) ? item.updated_at : undefined }))]
    const today = new Date().toDateString()
    const todayCount = all.filter((item) => new Date(item.created_at).toDateString() === today).length
    const active = all.filter((item) => ['queued', 'running', 'active', 'preparing', 'applying'].includes(item.state)).length
    const succeeded = all.filter((item) => item.state === 'succeeded').length
    const attention = all.filter((item) => ['failed', 'timed_out', 'waiting_user_action', 'waiting_confirmation', 'awaiting_apply_confirmation'].includes(item.state)).length
    const finished = all.filter((item) => item.finished_at && item.started_at)
    const averageSeconds = finished.length
      ? Math.round(finished.reduce((total, item) => total + (new Date(item.finished_at!).getTime() - new Date(item.started_at!).getTime()) / 1000, 0) / finished.length)
      : 0
    return { active, succeeded, attention, averageSeconds, todayCount, total: all.length }
  }, [batches, runs, workflows])

  const taskRows = useMemo(() => {
    const source = [...runs.map(runToTask), ...workflows.map(workflowToTask), ...batches.map(batchToTask)].sort((a, b) => b.time.localeCompare(a.time))
    return source.filter((task) => {
      const statusMatch = statusFilter === 'all' || (statusFilter === 'active' ? ['queued', 'running', 'active', 'preparing', 'applying'].includes(task.state) : task.state === statusFilter)
      const skillMatch = skillFilter === 'all' || task.skill === skillFilter
      const searchMatch = `${task.name}${task.skill}${task.file}${task.owner}`.toLowerCase().includes(query.toLowerCase())
      return statusMatch && skillMatch && searchMatch
    })
  }, [batches, query, runs, skillFilter, statusFilter, workflows])

  const [fileObjects, setFileObjects] = useState<File[]>([])
  const [startingTask, setStartingTask] = useState(false)
  const navigate = useNavigate()

  const handleFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const next = Array.from(event.target.files || [])
    setFileObjects(next)
    setFiles(next.map((file) => file.name))
  }

  const startTask = async () => {
    if (!selectedSkill) {
      navigate('/skills')
      return
    }
    setStartingTask(true)
    setError('')
    try {
      const role = activeSkill?.file_inputs[0]?.role || 'input_files'
      const uploaded: UploadedFile[] = []
      for (const file of fileObjects) uploaded.push(await api.upload(role, file))
      navigate(`/skills/${selectedSkill}`, { state: { draft: { message: note, files: uploaded } } })
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setStartingTask(false)
    }
  }

  const activeSkill = skills.find((skill) => skill.id === selectedSkill)

  return (
    <div className="console-page">
      <section className="console-metrics" aria-label="运行概览">
        <div className="console-metric"><span className="metric-symbol symbol-blue"><Play size={17} /></span><div><small>今日运行任务</small><strong>{loading ? '—' : metrics.todayCount}</strong><em>按真实创建时间统计</em></div></div>
        <div className="console-metric"><span className="metric-symbol symbol-cyan"><CheckCircle2 size={18} /></span><div><small>成功率</small><strong>{loading ? '—' : metrics.total ? `${Math.round((metrics.succeeded / metrics.total) * 1000) / 10}%` : '—'}</strong><em>{metrics.total ? `${metrics.succeeded} / ${metrics.total} 项完成` : '完成任务后显示'}</em></div></div>
        <div className="console-metric"><span className="metric-symbol symbol-lime"><Clock3 size={18} /></span><div><small>平均处理时长</small><strong>{loading ? '—' : metrics.averageSeconds ? `${Math.floor(metrics.averageSeconds / 60)}分 ${metrics.averageSeconds % 60}秒` : '—'}</strong><em>基于已完成任务</em></div></div>
        <div className="console-metric"><span className="metric-symbol symbol-yellow"><FileSpreadsheet size={18} /></span><div><small>待处理任务</small><strong>{loading ? '—' : metrics.active}</strong><em>排队或执行中</em></div></div>
        <div className="console-metric"><span className="metric-symbol symbol-red"><TriangleAlert size={18} /></span><div><small>异常任务</small><strong>{loading ? '—' : metrics.attention}</strong><em>需要人工关注</em></div></div>
      </section>

      {error && <div className="alert alert-error" role="alert"><TriangleAlert size={18} />{error}</div>}

      <div className="console-workspace">
        <div className="console-main-column">
          <section className="console-panel queue-panel">
            <div className="console-panel-heading">
              <div><h2>任务队列 <span>实时</span></h2><span className="queue-count">{taskRows.length} 条记录</span></div>
              <button className="console-icon-button" type="button" aria-label="刷新任务队列" onClick={() => window.location.reload()}><RefreshCw size={16} /></button>
            </div>
            <div className="queue-filters" id="queue">
              <SelectMenu value={statusFilter} onChange={setStatusFilter} ariaLabel="按状态筛选" className="console-select-menu" options={[{ value: 'all', label: '全部状态' }, { value: 'active', label: '处理中' }, { value: 'succeeded', label: '已完成' }, { value: 'failed', label: '异常' }]} />
              <SelectMenu value={skillFilter} onChange={setSkillFilter} ariaLabel="按 Skill 筛选" className="console-select-menu" options={[{ value: 'all', label: '全部 Skill' }, ...skills.map((skill) => ({ value: skill.name, label: skill.name }))]} />
              <label className="console-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务 / 文件 / 描述" /></label>
            </div>
            <div className="console-table-wrap">
              <table className="console-table">
                <thead><tr><th>优先级</th><th>任务名称</th><th>Skill</th><th>文件 / 数据源</th><th>状态</th><th>进度</th><th>所有者</th><th>更新时间</th></tr></thead>
                <tbody>
                  {taskRows.map((task) => (
                    <tr key={task.id}>
                      <td><span className={`priority priority-${task.priority.toLowerCase()}`}>{task.priority}</span></td>
                      <td><Link className="task-link" to={task.href}><strong>{task.name}</strong><small>{task.id}</small></Link></td>
                      <td>{task.skill}</td>
                      <td><strong className="file-name">{task.file}</strong><small>已上传文件</small></td>
                      <td><StatusBadge state={task.state} /></td>
                      <td><div className="console-progress"><span style={{ width: `${task.progress}%` }} /></div><small>{task.progress ? `${task.progress}%` : '—'}</small></td>
                      <td><span className="owner-chip"><span>{task.owner.slice(0, 1)}</span>{task.owner}<small>{task.team}</small></span></td>
                      <td>{task.time}</td>
                    </tr>
                  ))}
                  {!loading && !taskRows.length && <tr><td colSpan={8} className="console-empty">暂无真实运行记录。可以从右侧发起一项任务。</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="console-table-footer"><span>{metrics.total ? `共 ${metrics.total} 条运行记录` : '任务运行后会在这里显示'}</span><Link to="/runs">查看全部记录 <ArrowRight size={14} /></Link></div>
          </section>

          <section className="console-panel activity-panel">
            <div className="console-panel-heading"><h2>近期活动</h2><Link to="/runs">查看全部 <ArrowRight size={14} /></Link></div>
            <div className="activity-list">
              {[...runs.map(runToTask), ...workflows.map(workflowToTask), ...batches.map(batchToTask)].sort((a, b) => b.time.localeCompare(a.time)).slice(0, 5).map((task, index) => {
                return <div className="activity-row" key={`${task.id}-${index}`}><time>{task.time}</time><span className={`activity-dot activity-${task.state}`}><CircleDot size={14} /></span><strong>{task.name}</strong><span className="activity-copy">{task.state === 'succeeded' ? '任务已完成' : task.state === 'failed' ? '任务异常' : ['running', 'active', 'preparing', 'applying'].includes(task.state) ? '任务进入执行' : '任务进入队列'}</span><Link to={task.href}>查看</Link></div>
              })}
              {!loading && !runs.length && !workflows.length && !batches.length && <div className="activity-empty"><CircleDot size={14} /> 暂无近期活动，任务开始后会显示在这里。</div>}
            </div>
          </section>
        </div>

        <aside className="console-panel launch-panel">
          <div className="launch-heading"><div><span className="launch-mark">▷</span><div><h2>开始任务</h2><p>选择 Skill、上传文件、描述需求</p></div></div><ArrowRight size={17} /></div>
          <div className="launch-step"><div className="step-label"><span>1</span><strong>选择 Skill</strong><a href="#skill">查看说明 <ArrowRight size={13} /></a></div><SelectMenu value={selectedSkill || skills[0]?.id || ''} onChange={setSelectedSkill} ariaLabel="选择 Skill" className="launch-select-menu" options={skills.length ? skills.map((skill) => ({ value: skill.id, label: skill.name, description: skill.categories?.[0] || skill.category })) : [{ value: '', label: '正在读取 Skill…' }]} />{activeSkill && <small className="launch-help">{activeSkill.description}</small>}</div>
          <div className="launch-step"><div className="step-label"><span>2</span><strong>上传文件</strong></div><p className="launch-help">支持 Excel / CSV / PDF，单个文件 ≤ 100MB</p>{files.map((file) => <div className="selected-file" key={file}><FileSpreadsheet size={16} /><span>{file}</span><button type="button" aria-label={`移除 ${file}`} onClick={() => setFiles((current) => current.filter((item) => item !== file))}><X size={14} /></button></div>)}<label className="upload-dropzone"><UploadCloud size={21} /><span>点击或拖拽文件到此处</span><small>或 <b>选择文件</b></small><input type="file" multiple onChange={handleFiles} /></label></div>
          <div className="launch-step"><div className="step-label"><span>3</span><strong>描述需求</strong><em>（选填）</em></div><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="请按部门、费用类别、项目进行对比，输出差异金额与差异率…" maxLength={500} /><div className="char-count">{note.length} / 500</div></div>
          <label className="notify-check"><input type="checkbox" defaultChecked />完成后自动通知我</label>
          <button className="launch-button" type="button" onClick={startTask} disabled={startingTask}>{startingTask ? <LoaderCircle className="spin" size={16} /> : <Play size={16} fill="currentColor" />}{startingTask ? '正在准备任务…' : '开始任务'}</button>
          <button className="save-template" type="button"><Check size={15} />保存为模板</button>
        </aside>
      </div>
    </div>
  )
}
