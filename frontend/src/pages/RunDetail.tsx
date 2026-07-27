import {
  ArrowLeft,
  CheckCircle2,
  CircleStop,
  Clock3,
  Download,
  FileCheck2,
  Hash,
  LoaderCircle,
  MessageSquareText,
  RefreshCcw,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, eventStreamUrl } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import type { RunEvent, RunRecord } from '../types'

const TERMINAL = ['succeeded', 'failed', 'timed_out', 'cancelled']

export function RunDetail() {
  const { runId = '' } = useParams()
  const [run, setRun] = useState<RunRecord | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [error, setError] = useState('')
  const [acting, setActing] = useState(false)
  const lastEvent = useRef(0)

  const load = useCallback(async () => {
    try {
      setRun(await api.run(runId))
    } catch (reason) {
      setError((reason as Error).message)
    }
  }, [runId])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!run || TERMINAL.includes(run.state)) return
    const stream = new EventSource(eventStreamUrl(runId, lastEvent.current))
    const receive = (rawEvent: Event) => {
      const event = rawEvent as MessageEvent<string>
      const item = JSON.parse(event.data) as RunEvent
      lastEvent.current = Math.max(lastEvent.current, item.id)
      setEvents((current) =>
        current.some((existing) => existing.id === item.id) ? current : [...current, item],
      )
      load()
    }
    ;['state', 'progress', 'log', 'notice'].forEach((type) => stream.addEventListener(type, receive))
    stream.onerror = () => stream.close()
    return () => stream.close()
  }, [load, run?.state, runId])

  useEffect(() => {
    if (!run || TERMINAL.includes(run.state)) return
    const timer = window.setInterval(load, 2500)
    return () => window.clearInterval(timer)
  }, [load, run])

  const action = async (type: 'confirm' | 'cancel') => {
    setActing(true)
    setError('')
    try {
      if (type === 'confirm') await api.confirmRun(runId)
      else await api.cancelRun(runId)
      await load()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setActing(false)
    }
  }

  if (!run) {
    return <div className="loading-screen" aria-live="polite"><LoaderCircle className="spin" />{error || '正在读取任务…'}</div>
  }

  const summary = run.result.summary || {}
  const outputs = run.result.output_files || []
  const warnings = run.result.warnings || []

  return (
    <div className="page-stack">
      <Link to="/runs" className="back-link"><ArrowLeft size={16} /> 返回运行记录</Link>
      <section className="run-detail-header">
        <div>
          <div className="title-line">
            <span className="skill-category">{run.skill_id}</span>
            <StatusBadge state={run.state} />
          </div>
          <h2>{run.skill_name}</h2>
          <p>任务号 {run.id}</p>
        </div>
        <div className="run-actions">
          <button className="button button-secondary" onClick={load}>
            <RefreshCcw size={16} /> 刷新
          </button>
          {run.state === 'waiting_confirmation' && (
            <button className="button button-primary" onClick={() => action('confirm')} disabled={acting}>
              <ShieldCheck size={16} /> 确认执行
            </button>
          )}
          {!TERMINAL.includes(run.state) && (
            <button className="button button-danger-ghost" onClick={() => action('cancel')} disabled={acting}>
              <CircleStop size={16} /> 取消任务
            </button>
          )}
        </div>
      </section>

      {error && <div className="alert alert-error" role="alert"><TriangleAlert size={18} />{error}</div>}
      {run.state === 'waiting_user_action' && (
        <div className="alert alert-warning">
          <Clock3 size={18} />执行器正在等待你在 RPA 浏览器中完成登录或页面操作。
        </div>
      )}

      <section className="progress-panel">
        <div className="progress-head">
          <div>
            <span>当前进度</span>
            <strong>{run.progress_message || '等待执行器更新'}</strong>
          </div>
          <b>{run.progress}%</b>
        </div>
        <div className="progress-track"><span style={{ width: `${run.progress}%` }} /></div>
        <div className="progress-meta">
          <span><Clock3 size={15} /> 创建于 {new Date(run.created_at).toLocaleString('zh-CN')}</span>
          <span><Hash size={15} /> Skill SHA {run.skill_commit?.slice(0, 10) || '本地版本'}</span>
          <span><ShieldCheck size={15} /> v{run.skill_version} 运行快照</span>
        </div>
      </section>

      {run.state === 'succeeded' && (
        <>
          <section className="result-banner">
            <CheckCircle2 size={26} />
            <div><strong>任务执行完成</strong><span>以下数字来自 Skill 的确定性结果，模型不会修改。</span></div>
          </section>
          <section className="result-grid">
            {Object.entries(summary).map(([key, value]) => (
              <article key={key}>
                <span>{summaryLabel(key)}</span>
                <strong>{value}</strong>
              </article>
            ))}
          </section>
        </>
      )}

      {(run.state === 'failed' || run.state === 'timed_out') && (
        <div className="alert alert-error" role="alert">
          <TriangleAlert size={18} />
          <div><strong>执行没有完成</strong><span>{run.error_message || run.progress_message}</span></div>
        </div>
      )}

      <section className="detail-grid">
        <div className="surface-panel">
          <div className="section-heading">
            <div><span className="eyebrow">ACTIVITY</span><h2>执行动态</h2></div>
          </div>
          <div className="timeline">
            {(events.length ? events : [{
              id: 0,
              type: 'state',
              state: run.state,
              progress: run.progress,
              message: run.progress_message,
              data: {},
              created_at: run.created_at,
            }]).map((item) => (
              <div className="timeline-item" key={item.id}>
                <span className="timeline-dot" />
                <div>
                  <strong>{item.message || item.state}</strong>
                  <small>{new Date(item.created_at).toLocaleTimeString('zh-CN')}</small>
                </div>
                {item.progress !== undefined && <b>{item.progress}%</b>}
              </div>
            ))}
          </div>
        </div>

        <div className="surface-panel">
          <div className="section-heading">
            <div><span className="eyebrow">ARTIFACTS</span><h2>结果文件</h2></div>
          </div>
          <div className="artifact-list">
            {outputs.map((file) => (
              <a key={file.file_id} href={file.download_url} className="artifact-row">
                <div className="artifact-icon"><FileCheck2 size={19} /></div>
                <div><strong>{file.name}</strong><span>{Math.ceil(file.size_bytes / 1024)} KB · SHA {file.sha256.slice(0, 8)}</span></div>
                <Download size={18} />
              </a>
            ))}
            {!outputs.length && <div className="empty-inline">任务完成后，结果文件会显示在这里。</div>}
          </div>
          {warnings.length > 0 && (
            <div className="warning-list">
              <strong><MessageSquareText size={16} /> 需要人工留意</strong>
              {warnings.map((warning) => <p key={warning}>{warning}</p>)}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function summaryLabel(key: string): string {
  const labels: Record<string, string> = {
    bank_records: '银行流水',
    ledger_records: '总账记录',
    matched: '成功匹配',
    unmatched: '未匹配',
    unmatched_bank: '银行未匹配',
    unmatched_ledger: '总账未匹配',
  }
  return labels[key] || key
}
