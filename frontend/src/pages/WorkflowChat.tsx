import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CalendarDays,
  Check,
  Download,
  FileSpreadsheet,
  LoaderCircle,
  LockKeyhole,
  RotateCcw,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import type { SkillManifest, WorkflowRecord } from '../types'

const BUSY_STAGES = new Set(['preparing', 'applying'])

const EXECUTION_STEPS = [
  { key: 'preflight', label: '前置条件校验', detail: '文件、日期、模型和凭据' },
  { key: 'fetch', label: '智云自动取数', detail: '按核销日期读取回款与订单' },
  { key: 'classify', label: '核销判定', detail: '执行确定性核验和异常识别' },
  { key: 'worklist', label: '生成核销日清', detail: '输出清单并完成写前校验' },
  { key: 'apply', label: '写入工作副本', detail: '先盈亏明细，再写流转安全子集' },
]

function humanSize(size: number) {
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function currentStep(workflow: WorkflowRecord) {
  if (workflow.state === 'failed') return 2
  if (workflow.stage === 'awaiting_apply_confirmation') return 4
  if (workflow.stage === 'applying') return 5
  if (workflow.stage === 'completed') return 5
  if (workflow.progress >= 75) return 4
  if (workflow.progress >= 45) return 3
  if (workflow.progress >= 20) return 2
  return 1
}

export function WorkflowChat() {
  const { workflowId = '' } = useParams()
  const [workflow, setWorkflow] = useState<WorkflowRecord | null>(null)
  const [skill, setSkill] = useState<SkillManifest | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [showResetDialog, setShowResetDialog] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [error, setError] = useState('')

  const refresh = async () => {
    const next = await api.workflow(workflowId)
    setWorkflow(next)
    return next
  }

  useEffect(() => {
    let active = true
    api.workflow(workflowId)
      .then(async (data) => {
        if (!active) return
        setWorkflow(data)
        setSkill(await api.skill(data.skill_id))
      })
      .catch((reason: Error) => setError(reason.message))
    return () => { active = false }
  }, [workflowId])

  useEffect(() => {
    if (!workflow || !BUSY_STAGES.has(workflow.stage)) return
    const timer = window.setInterval(() => refresh().catch((reason: Error) => setError(reason.message)), 1500)
    return () => window.clearInterval(timer)
  }, [workflow?.stage, workflowId])

  useEffect(() => {
    if (!showResetDialog) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !resetting) setShowResetDialog(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [showResetDialog, resetting])

  const step = workflow ? currentStep(workflow) : 1
  const files = useMemo(
    () => Object.values(workflow?.files || {}).flat(),
    [workflow?.files],
  )

  const confirmResult = async () => {
    if (!workflow) return
    setConfirming(true)
    setError('')
    try {
      setWorkflow(await api.confirmWorkflow(workflow.id))
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setConfirming(false)
    }
  }

  const rebuild = async () => {
    if (!workflow) return
    setRebuilding(true)
    setError('')
    try {
      setWorkflow(await api.rebuildWorkflow(workflow.id))
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setRebuilding(false)
    }
  }

  const resetWorkflow = async () => {
    if (!workflow || BUSY_STAGES.has(workflow.stage)) return
    setResetting(true)
    setError('')
    try {
      setWorkflow(await api.resetWorkflow(workflow.id))
      setShowResetDialog(false)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setResetting(false)
    }
  }

  if (!workflow || !skill) {
    if (error) return <div className="alert alert-error"><TriangleAlert size={18} />{error}</div>
    return <div className="loading-screen"><LoaderCircle className="spin" />正在加载核销执行页…</div>
  }

  const waitingConfirmation = workflow.stage === 'awaiting_apply_confirmation'
  const failed = workflow.state === 'failed'
  const completed = workflow.state === 'completed'

  return (
    <div className="workflow-page workflow-execution-page">
      <header className="workflow-header">
        <div>
          <Link to={workflow.batch_id ? `/workflow-batches/${workflow.batch_id}` : '/skills'} className="back-link"><ArrowLeft size={16} /> {workflow.batch_id ? '返回核销批次' : '返回工具列表'}</Link>
          <span className="skill-category">{skill.category}</span>
          <h2>{workflow.skill_name}</h2>
          <p><Bot size={15} /> {workflow.model_provider} · {workflow.model_name}</p>
          <p className="detail-record-id">任务 ID <code>{workflow.id}</code></p>
        </div>
        <div className="workflow-header-actions">
          {!workflow.batch_id && (
            <button
              type="button"
              className="button button-danger-ghost workflow-reset-button"
              disabled={BUSY_STAGES.has(workflow.stage) || resetting}
              onClick={() => setShowResetDialog(true)}
            ><RotateCcw size={16} /> 重置任务</button>
          )}
          <div className={`workflow-state workflow-state-${workflow.state}`}>
            <ShieldCheck size={17} />
            <span>{completed ? '核销完成' : failed ? '执行失败' : workflow.progress_message}</span>
            {BUSY_STAGES.has(workflow.stage) && <b>{workflow.progress}%</b>}
          </div>
        </div>
      </header>

      {error && <div className="alert alert-error" role="alert"><TriangleAlert size={18} />{error}</div>}

      <div className="workflow-execution-layout">
        <main className="workflow-execution-main">
          <section className="execution-hero">
            <div className={`execution-hero-icon ${failed ? 'is-failed' : completed ? 'is-complete' : ''}`}>
              {failed ? <TriangleAlert size={28} /> : completed ? <Check size={30} /> : <LoaderCircle className="spin" size={28} />}
            </div>
            <div>
              <span className="eyebrow">核销执行中</span>
              <h3>{failed ? '本次核销没有完成' : completed ? '核销任务已完成' : waitingConfirmation ? '核销日清已生成，等待你的确认' : '正在自动核销'}</h3>
              <p>{failed ? workflow.error_message : workflow.progress_message}</p>
            </div>
            <strong className="execution-progress-number">{workflow.progress}%</strong>
          </section>

          <section className="execution-panel">
            <div className="execution-panel-heading">
              <div><span className="eyebrow">EXECUTION FLOW</span><h3>核销执行进度</h3></div>
              <span className="execution-date"><CalendarDays size={15} /> {workflow.reconciliation_date}</span>
            </div>
            <div className="workflow-timeline">
              {EXECUTION_STEPS.map((item, index) => {
                const number = index + 1
                const done = number < step || (number === 4 && waitingConfirmation) || (number === 5 && completed)
                const active = !done && number === step && !failed
                return (
                  <div className={`workflow-timeline-step ${done ? 'is-done' : ''} ${active ? 'is-active' : ''}`} key={item.key}>
                    <div className="workflow-timeline-marker">{done ? <Check size={15} /> : active ? <LoaderCircle className="spin" size={15} /> : number}</div>
                    <div><strong>{item.label}</strong><span>{item.detail}</span></div>
                    {active && <small>处理中</small>}
                    {done && <small>已完成</small>}
                  </div>
                )
              })}
            </div>
          </section>

          {waitingConfirmation && (
            <section className="execution-confirm-card">
              <div className="execution-confirm-icon"><ShieldCheck size={24} /></div>
              <div><span className="eyebrow">HUMAN CHECKPOINT</span><h3>核销日清已准备好</h3><p>请先下载并检查核销日清。确认后才会写入工作副本。</p></div>
              <button type="button" className="button button-primary" onClick={confirmResult} disabled={confirming}>
                {confirming ? <><LoaderCircle className="spin" size={16} /> 正在确认…</> : <>确认写入 <ArrowRight size={16} /></>}
              </button>
            </section>
          )}

          {failed && !workflow.batch_id && (
            <section className="execution-confirm-card is-failed">
              <div className="execution-confirm-icon"><TriangleAlert size={24} /></div>
              <div><span className="eyebrow">ACTION REQUIRED</span><h3>需要重新生成</h3><p>请根据错误提示修正前置条件，重新执行本次核销。原始财务文件未被修改。</p></div>
              <button type="button" className="button button-secondary" onClick={rebuild} disabled={rebuilding}>
                {rebuilding ? <><LoaderCircle className="spin" size={16} /> 正在重试…</> : <>重新生成 <ArrowRight size={16} /></>}
              </button>
            </section>
          )}

          <section className="execution-log-panel">
            <div className="execution-panel-heading"><div><span className="eyebrow">AUDIT LOG</span><h3>执行记录</h3></div><span className="execution-log-count">{workflow.messages.length} 条</span></div>
            <div className="execution-log-list">
              {workflow.messages.map((item) => (
                <div className={`execution-log-item execution-log-${item.role}`} key={item.id}>
                  <span className="execution-log-dot" />
                  <div><strong>{item.role === 'assistant' ? '系统执行器' : '操作记录'}</strong><p>{item.content}</p><small>{new Date(item.created_at).toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</small></div>
                </div>
              ))}
            </div>
          </section>
        </main>

        <aside className="workflow-execution-sidebar">
          <section className="workflow-side-card">
            <div className="workflow-side-title"><CalendarDays size={18} /><div><h3>任务摘要</h3><p>本次执行边界</p></div></div>
            <dl className="workflow-meta">
              <div><dt>任务 ID</dt><dd className="workflow-id-value" title={workflow.id}>{workflow.id}</dd></div>
              <div><dt>核销日期</dt><dd>{workflow.reconciliation_date}</dd></div>
              <div><dt>模型</dt><dd>{workflow.model_name}</dd></div>
              <div><dt>Skill 版本</dt><dd>v{workflow.skill_version}</dd></div>
              <div><dt>安全策略</dt><dd>{workflow.requires_confirmation ? '人工确认后写入' : '写前校验通过后自动写副本'}</dd></div>
              {workflow.batch_id && <div><dt>所属批次</dt><dd><Link to={`/workflow-batches/${workflow.batch_id}`}>{workflow.batch_id}</Link></dd></div>}
            </dl>
          </section>

          <section className="workflow-side-card">
            <div className="workflow-side-title"><FileSpreadsheet size={18} /><div><h3>已上传文件</h3><p>隔离副本，只读处理</p></div></div>
            <div className="execution-file-list">
              {files.map((file) => <div className="execution-file-row" key={file.file_id}><FileSpreadsheet size={15} /><span title={file.name}>{file.name}</span><small>{humanSize(file.size_bytes)}</small></div>)}
            </div>
          </section>

          {workflow.artifacts.length > 0 && (
            <section className="workflow-side-card">
              <div className="workflow-side-title"><FileSpreadsheet size={18} /><div><h3>输出文件</h3><p>下载后检查核销日清</p></div></div>
              <div className="workflow-artifacts">
                {workflow.artifacts.map((artifact) => <a href={artifact.download_url} key={artifact.file_id}><FileSpreadsheet size={16} /><span>{artifact.name}</span><Download size={15} /></a>)}
              </div>
            </section>
          )}
        </aside>
      </div>

      {showResetDialog && (
        <div className="dialog-backdrop">
          <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="reset-dialog-title">
            <div className="confirm-dialog-icon"><RotateCcw size={21} /></div>
            <div><h3 id="reset-dialog-title">重置当前任务？</h3><p>将清空核销日期、文件绑定和当前输出，历史审计记录及已经完成的写入不会撤销。</p></div>
            <div className="confirm-dialog-actions">
              <button type="button" className="button button-secondary" autoFocus disabled={resetting} onClick={() => setShowResetDialog(false)}>取消</button>
              <button type="button" className="button button-danger" disabled={resetting} onClick={resetWorkflow}>{resetting ? <><LoaderCircle className="spin" size={16} /> 正在重置…</> : <><RotateCcw size={16} /> 确认重置</>}</button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
