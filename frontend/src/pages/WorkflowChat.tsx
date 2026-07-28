import {
  ArrowLeft,
  Bot,
  CalendarDays,
  Download,
  FileSpreadsheet,
  LoaderCircle,
  Send,
  ShieldCheck,
  TriangleAlert,
  UploadCloud,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import type { SkillManifest, WorkflowRecord } from '../types'

const BUSY_STAGES = new Set(['preparing', 'applying'])

function humanSize(size: number) {
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function quickAction(workflow: WorkflowRecord) {
  if (workflow.stage === 'awaiting_date') return '昨天'
  if (workflow.stage === 'awaiting_date_confirmation') return '确认'
  if (workflow.stage === 'awaiting_files') return '上传好了'
  if (workflow.stage === 'awaiting_apply_confirmation') {
    return '我已检查核销日清，确认写入'
  }
  if (workflow.stage === 'failed') return '重新生成核销日清'
  return ''
}

export function WorkflowChat() {
  const { workflowId = '' } = useParams()
  const [workflow, setWorkflow] = useState<WorkflowRecord | null>(null)
  const [skill, setSkill] = useState<SkillManifest | null>(null)
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [uploadingRole, setUploadingRole] = useState('')
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
    return () => {
      active = false
    }
  }, [workflowId])

  useEffect(() => {
    if (!workflow || !BUSY_STAGES.has(workflow.stage)) return
    const timer = window.setInterval(() => {
      refresh().catch((reason: Error) => setError(reason.message))
    }, 1500)
    return () => window.clearInterval(timer)
  }, [workflow?.stage, workflowId])

  const actionText = workflow ? quickAction(workflow) : ''
  const canSend = Boolean(
    workflow
    && !BUSY_STAGES.has(workflow.stage)
    && !['completed', 'cancelled'].includes(workflow.stage),
  )
  const currentFiles = useMemo(
    () => workflow?.files || {},
    [workflow?.files],
  )

  const send = async (content = message) => {
    const trimmed = content.trim()
    if (!workflow || !trimmed || !canSend) return
    setSending(true)
    setError('')
    try {
      setWorkflow(await api.sendWorkflowMessage(workflow.id, trimmed))
      setMessage('')
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSending(false)
    }
  }

  const uploadFiles = async (role: string, selected: FileList | null) => {
    if (!workflow || !skill || !selected?.length) return
    const spec = skill.file_inputs.find((item) => item.role === role)
    const chosen = Array.from(selected)
    const existing = currentFiles[role] || []
    if (spec && existing.length + chosen.length < (spec.min_files || 1)) {
      setError(`${spec.name}至少需要 ${spec.min_files || 1} 个文件，请一次选齐。`)
      return
    }
    setUploadingRole(role)
    setError('')
    try {
      const uploadedIds = []
      for (const file of chosen) {
        const uploaded = await api.upload(role, file)
        uploadedIds.push(uploaded.id)
      }
      setWorkflow(
        await api.updateWorkflowFiles(workflow.id, {
          [role]: [...existing.map((item) => item.file_id), ...uploadedIds],
        }),
      )
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setUploadingRole('')
    }
  }

  if (!workflow || !skill) {
    if (error) {
      return <div className="alert alert-error"><TriangleAlert size={18} />{error}</div>
    }
    return (
      <div className="loading-screen">
        <LoaderCircle className="spin" />正在恢复对话任务…
      </div>
    )
  }

  return (
    <div className="workflow-page">
      <header className="workflow-header">
        <div>
          <Link to="/skills" className="back-link">
            <ArrowLeft size={16} /> 返回工具列表
          </Link>
          <span className="skill-category">{skill.category}</span>
          <h2>{workflow.skill_name}</h2>
          <p>
            <Bot size={15} /> {workflow.model_provider} · {workflow.model_name}
          </p>
        </div>
        <div className={`workflow-state workflow-state-${workflow.state}`}>
          <ShieldCheck size={17} />
          <span>{workflow.progress_message}</span>
          {BUSY_STAGES.has(workflow.stage) && <b>{workflow.progress}%</b>}
        </div>
      </header>

      {error && (
        <div className="alert alert-error" role="alert">
          <TriangleAlert size={18} />{error}
        </div>
      )}

      <div className="workflow-layout">
        <main className="chat-panel">
          <div className="chat-safety">
            <ShieldCheck size={17} />
            模型只理解意图和控制流程；金额计算与写表均由固化脚本执行。
          </div>
          <div className="chat-messages" aria-live="polite">
            {workflow.messages.map((item) => (
              <article className={`chat-message chat-${item.role}`} key={item.id}>
                <div className="chat-avatar">
                  {item.role === 'assistant' ? <Bot size={17} /> : '我'}
                </div>
                <div>
                  <span>{item.role === 'assistant' ? '财务工作流助手' : '当前用户'}</span>
                  <p>{item.content}</p>
                </div>
              </article>
            ))}
            {BUSY_STAGES.has(workflow.stage) && (
              <article className="chat-message chat-assistant">
                <div className="chat-avatar"><LoaderCircle className="spin" size={17} /></div>
                <div>
                  <span>确定性执行器</span>
                  <p>{workflow.progress_message}（{workflow.progress}%）</p>
                </div>
              </article>
            )}
          </div>
          {actionText && (
            <div className="chat-quick-actions">
              <span>建议操作</span>
              <button type="button" onClick={() => send(actionText)} disabled={sending}>
                {actionText}
              </button>
            </div>
          )}
          <form
            className="chat-composer"
            onSubmit={(event) => {
              event.preventDefault()
              send()
            }}
          >
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              disabled={!canSend}
              placeholder={canSend ? '回复日期、确认，或询问当前进度…' : '当前阶段暂不接收新指令'}
              rows={2}
            />
            <button
              type="submit"
              className="button button-primary"
              disabled={!canSend || !message.trim() || sending}
              aria-label="发送消息"
            >
              {sending ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
            </button>
          </form>
        </main>

        <aside className="workflow-sidebar">
          <section className="workflow-side-card">
            <div className="workflow-side-title">
              <UploadCloud size={18} />
              <div><h3>业务文件</h3><p>上传的是隔离副本</p></div>
            </div>
            {skill.file_inputs.map((spec) => {
              const roleFiles = currentFiles[spec.role] || []
              return (
                <div className="workflow-file-role" key={spec.role}>
                  <div>
                    <strong>{spec.name}</strong>
                    <span>
                      至少 {spec.min_files || 1} 个 · {spec.extensions.join('、').toUpperCase()}
                    </span>
                  </div>
                  {roleFiles.map((file) => (
                    <div className="workflow-file" key={file.file_id}>
                      <FileSpreadsheet size={15} />
                      <span>{file.name}</span>
                      <small>{humanSize(file.size_bytes)}</small>
                    </div>
                  ))}
                  <label className="workflow-upload-button">
                    <input
                      type="file"
                      multiple={spec.multiple}
                      accept={spec.extensions.map((item) => `.${item}`).join(',')}
                      disabled={uploadingRole === spec.role || BUSY_STAGES.has(workflow.stage)}
                      onChange={(event) => uploadFiles(spec.role, event.target.files)}
                    />
                    {uploadingRole === spec.role
                      ? <><LoaderCircle className="spin" size={15} /> 上传中…</>
                      : <><UploadCloud size={15} /> 选择文件</>}
                  </label>
                </div>
              )
            })}
          </section>

          <section className="workflow-side-card">
            <div className="workflow-side-title">
              <CalendarDays size={18} />
              <div><h3>执行边界</h3><p>每一步均有状态记录</p></div>
            </div>
            <dl className="workflow-meta">
              <div><dt>核销日期</dt><dd>{workflow.reconciliation_date || '待确认'}</dd></div>
              <div><dt>当前阶段</dt><dd>{workflow.stage}</dd></div>
              <div><dt>Skill 版本</dt><dd>v{workflow.skill_version}</dd></div>
            </dl>
          </section>

          {workflow.artifacts.length > 0 && (
            <section className="workflow-side-card">
              <div className="workflow-side-title">
                <FileSpreadsheet size={18} />
                <div><h3>输出文件</h3><p>先下载日清，确认后再写入</p></div>
              </div>
              <div className="workflow-artifacts">
                {workflow.artifacts.map((artifact) => (
                  <a href={artifact.download_url} key={artifact.file_id}>
                    <FileSpreadsheet size={16} />
                    <span>{artifact.name}</span>
                    <Download size={15} />
                  </a>
                ))}
              </div>
            </section>
          )}
        </aside>
      </div>
    </div>
  )
}
