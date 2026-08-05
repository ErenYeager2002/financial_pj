import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  Clock3,
  Layers3,
  LoaderCircle,
  RotateCcw,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import type { WorkflowBatchRecord } from '../types'

const TERMINAL_STATES = new Set(['succeeded', 'failed', 'cancelled'])

function dateLabel(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  })
}

export function WorkflowBatch() {
  const { batchId = '' } = useParams()
  const [batch, setBatch] = useState<WorkflowBatchRecord | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [error, setError] = useState('')

  const refresh = async () => {
    const next = await api.workflowBatch(batchId)
    setBatch(next)
    return next
  }

  useEffect(() => {
    let active = true
    api.workflowBatch(batchId)
      .then((data) => { if (active) setBatch(data) })
      .catch((reason: Error) => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [batchId])

  useEffect(() => {
    if (!batch || TERMINAL_STATES.has(batch.state)) return
    const timer = window.setInterval(() => refresh().catch((reason: Error) => setError(reason.message)), 1500)
    return () => window.clearInterval(timer)
  }, [batch?.state, batchId])

  const counts = useMemo(() => {
    const workflows = batch?.workflows || []
    return {
      succeeded: workflows.filter((item) => item.state === 'succeeded').length,
      failed: workflows.filter((item) => item.state === 'failed').length,
      waiting: workflows.filter((item) => item.state === 'queued').length,
    }
  }, [batch?.workflows])

  const retry = async () => {
    if (!batch) return
    setRetrying(true)
    setError('')
    try {
      setBatch(await api.retryWorkflowBatch(batch.id))
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setRetrying(false)
    }
  }

  if (!batch) {
    if (error) return <div className="alert alert-error"><TriangleAlert size={18} />{error}</div>
    return <div className="loading-screen"><LoaderCircle className="spin" />正在加载核销批次…</div>
  }

  return (
    <div className="page-stack workflow-batch-page">
      <Link to="/runs" className="back-link"><ArrowLeft size={16} /> 返回运行记录</Link>
      <header className="workflow-batch-hero">
        <div className="workflow-batch-icon"><Layers3 size={28} /></div>
        <div>
          <span className="eyebrow">MULTI-DAY BATCH</span>
          <h2>{batch.skill_name} · {batch.reconciliation_dates.length} 天批次</h2>
          <p>{batch.progress_message}</p>
          <small>批次 ID <code>{batch.id}</code></small>
        </div>
        <StatusBadge state={batch.state} />
      </header>

      {error && <div className="alert alert-error" role="alert"><TriangleAlert size={18} />{error}</div>}

      <section className="workflow-batch-overview">
        <div className="workflow-batch-progress">
          <div><strong>整体进度</strong><b>{batch.progress}%</b></div>
          <div className="batch-progress-track"><span style={{ width: `${batch.progress}%` }} /></div>
          <p>已完成 {counts.succeeded} 天 · 等待 {counts.waiting} 天 · 失败 {counts.failed} 天</p>
        </div>
        <div className="workflow-batch-rule">
          <Clock3 size={20} />
          <div><strong>严格串行执行</strong><span>前一天工作副本写入并回读成功后，下一天才会开始。</span></div>
        </div>
      </section>

      {batch.state === 'failed' && (
        <section className="workflow-batch-alert">
          <TriangleAlert size={22} />
          <div><strong>批次已在失败日期暂停</strong><p>{batch.error_message || '请检查失败任务详情。之前成功的日期不会重复执行。'}</p></div>
          <button className="button button-primary" type="button" disabled={retrying} onClick={retry}>
            {retrying ? <><LoaderCircle className="spin" size={16} /> 正在继续…</> : <><RotateCcw size={16} /> 从失败日期继续</>}
          </button>
        </section>
      )}

      <section className="workflow-batch-days">
        <div className="section-heading">
          <div><span className="eyebrow">DAILY RUNS</span><h2>逐日执行记录</h2></div>
          <span className="section-count">{batch.workflows.length} 个任务 ID</span>
        </div>
        <div className="workflow-batch-day-list">
          {batch.workflows.map((workflow) => (
            <Link className={`workflow-batch-day is-${workflow.state}`} to={`/workflows/${workflow.id}`} key={workflow.id}>
              <div className="workflow-batch-order">
                {workflow.state === 'succeeded' ? <Check size={17} /> : workflow.state === 'running' ? <LoaderCircle className="spin" size={17} /> : workflow.batch_sequence}
              </div>
              <div className="workflow-batch-day-copy">
                <strong><CalendarDays size={15} /> {dateLabel(workflow.reconciliation_date)}</strong>
                <span>{workflow.progress_message}</span>
                <small title={workflow.id}>任务 ID · {workflow.id}</small>
              </div>
              <div className="workflow-batch-day-progress">
                <b>{workflow.progress}%</b>
                <span><i style={{ width: `${workflow.progress}%` }} /></span>
              </div>
              <StatusBadge state={workflow.state} />
              <ArrowRight size={16} />
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}
