import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  FileCheck2,
  FileUp,
  LoaderCircle,
  LockKeyhole,
  Sparkles,
  TriangleAlert,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import type {
  JsonSchemaProperty,
  ModelConnection,
  SkillManifest,
  UploadedFile,
} from '../types'

function humanSize(size: number) {
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export function SkillRun() {
  const { skillId = '' } = useParams()
  const navigate = useNavigate()
  const [skill, setSkill] = useState<SkillManifest | null>(null)
  const [files, setFiles] = useState<Record<string, UploadedFile>>({})
  const [message, setMessage] = useState('')
  const [parameters, setParameters] = useState<Record<string, unknown>>({})
  const [loadingRole, setLoadingRole] = useState('')
  const [interpreting, setInterpreting] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [startingWorkflow, setStartingWorkflow] = useState(false)
  const [error, setError] = useState('')
  const [notes, setNotes] = useState<string[]>([])
  const [modelConnections, setModelConnections] = useState<ModelConnection[]>([])
  const [modelConnectionId, setModelConnectionId] = useState('')
  const [selectedModel, setSelectedModel] = useState('')

  useEffect(() => {
    api.skill(skillId)
      .then((data) => {
        setSkill(data)
        const defaults = Object.fromEntries(
          Object.entries(data.input_schema.properties || {})
            .filter(([, property]) => property.default !== undefined)
            .map(([key, property]) => [key, property.default]),
        )
        setParameters(defaults)
      })
      .catch((reason: Error) => setError(reason.message))
  }, [skillId])

  useEffect(() => {
    api.modelConnections()
      .then((connections) => {
        setModelConnections(connections)
        if (connections.length) {
          setModelConnectionId(connections[0].id)
          setSelectedModel(connections[0].selected_model)
        }
      })
      .catch((reason: Error) => setError(reason.message))
  }, [])

  const ready = useMemo(() => {
    if (!skill) return false
    return skill.file_inputs.every((spec) => !spec.required || Boolean(files[spec.role]))
  }, [files, skill])

  const upload = async (role: string, file?: File) => {
    if (!file) return
    setError('')
    setLoadingRole(role)
    try {
      const uploaded = await api.upload(role, file)
      setFiles((current) => ({ ...current, [role]: uploaded }))
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setLoadingRole('')
    }
  }

  const interpret = async () => {
    if (!skill) return
    setInterpreting(true)
    setError('')
    try {
      const result = await api.interpret(
        skill.id,
        message,
        parameters,
        modelConnectionId,
        selectedModel,
      )
      setParameters(result.parameters)
      setNotes(result.notes)
      if (result.missing.length) {
        setError(`还缺少参数：${result.missing.join('、')}`)
      }
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setInterpreting(false)
    }
  }

  const submit = async () => {
    if (!skill || !ready) return
    setSubmitting(true)
    setError('')
    try {
      const run = await api.createRun(
        skill.id,
        message,
        parameters,
        Object.fromEntries(Object.entries(files).map(([role, file]) => [role, file.id])),
        modelConnectionId,
        selectedModel,
      )
      navigate(`/runs/${run.id}`)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const startWorkflow = async () => {
    if (!skill || !modelConnectionId) return
    setStartingWorkflow(true)
    setError('')
    try {
      const workflow = await api.createWorkflow(
        skill.id,
        modelConnectionId,
        selectedModel,
      )
      navigate(`/workflows/${workflow.id}`)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setStartingWorkflow(false)
    }
  }

  if (!skill && !error) {
    return <div className="loading-screen" aria-live="polite"><LoaderCircle className="spin" />正在读取 Skill…</div>
  }

  if (!skill) {
    return <div className="alert alert-error" role="alert"><TriangleAlert size={18} />{error}</div>
  }

  if (skill.handler.adapter === 'workflow') {
    return (
      <div className="workflow-start page-stack">
        <Link to="/skills" className="back-link"><ArrowLeft size={16} /> 返回工具列表</Link>
        <section className="workflow-start-card">
          <div className="workflow-start-icon"><Bot size={28} /></div>
          <span className="skill-category">{skill.category}</span>
          <h2>{skill.name}</h2>
          <p>{skill.description}</p>
          <div className="workflow-gates">
            <span><Check size={16} /> 对话确认核销日期</span>
            <span><Check size={16} /> 上传隔离副本并生成核销日清</span>
            <span><LockKeyhole size={16} /> 人工确认前禁止写表</span>
          </div>
          {error && (
            <div className="alert alert-error" role="alert">
              <TriangleAlert size={18} />{error}
            </div>
          )}
          {modelConnections.length ? (
            <div className="task-model-selector">
              <div className="task-model-icon"><Bot size={19} /></div>
              <label className="field">
                <span>模型服务</span>
                <select
                  value={modelConnectionId}
                  onChange={(event) => {
                    const connection = modelConnections.find(
                      (item) => item.id === event.target.value,
                    )
                    setModelConnectionId(event.target.value)
                    setSelectedModel(connection?.selected_model || '')
                  }}
                >
                  {modelConnections.map((connection) => (
                    <option key={connection.id} value={connection.id}>
                      {connection.provider_name} · {connection.api_key_hint}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>对话模型</span>
                <select
                  value={selectedModel}
                  onChange={(event) => setSelectedModel(event.target.value)}
                >
                  {(modelConnections.find((item) => item.id === modelConnectionId)?.models || [])
                    .map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
            </div>
          ) : (
            <div className="model-required">
              <Bot size={18} />
              <div>
                <strong>需要先接入对话模型</strong>
                <span>平台会使用模型理解你的回复，但所有财务计算仍由固定脚本完成。</span>
              </div>
              <Link to="/models">接入模型</Link>
            </div>
          )}
          <button
            type="button"
            className="button button-primary workflow-start-button"
            disabled={!modelConnectionId || startingWorkflow}
            onClick={startWorkflow}
          >
            {startingWorkflow
              ? <><LoaderCircle className="spin" size={17} /> 正在建立会话…</>
              : <>开始对话式核销 <ArrowRight size={17} /></>}
          </button>
        </section>
      </div>
    )
  }

  return (
    <div className="run-builder">
      <div className="run-builder-main">
        <Link to="/skills" className="back-link"><ArrowLeft size={16} /> 返回工具列表</Link>
        <div className="run-title">
          <span className="skill-category">{skill.category}</span>
          <h2>{skill.name}</h2>
          <p>{skill.description}</p>
        </div>

        {error && <div className="alert alert-error" role="alert"><TriangleAlert size={18} />{error}</div>}

        <section className="form-section">
          <div className="form-section-heading">
            <span className="step-number">1</span>
            <div><h3>上传业务文件</h3><p>文件只用于本次运行，脚本读取的是隔离副本。</p></div>
          </div>
          <div className="upload-grid">
            {skill.file_inputs.map((spec) => {
              const uploaded = files[spec.role]
              return (
                <label className={`upload-card ${uploaded ? 'uploaded' : ''}`} key={spec.role}>
                  <input
                    type="file"
                    accept={spec.extensions.map((item) => `.${item}`).join(',')}
                    onChange={(event) => upload(spec.role, event.target.files?.[0])}
                  />
                  {loadingRole === spec.role ? (
                    <LoaderCircle className="spin" size={25} />
                  ) : uploaded ? (
                    <FileCheck2 size={25} />
                  ) : (
                    <FileUp size={25} />
                  )}
                  <div>
                    <strong>{spec.name}{spec.required && <b>*</b>}</strong>
                    {uploaded ? (
                      <>
                        <span>{uploaded.name}</span>
                        <small>{humanSize(uploaded.size_bytes)} · SHA {uploaded.sha256.slice(0, 8)}</small>
                      </>
                    ) : (
                      <>
                        <span>{spec.description}</span>
                        <small>{spec.extensions.join('、').toUpperCase()} · 最大 {spec.max_size_mb || 100} MB</small>
                      </>
                    )}
                  </div>
                  {uploaded && (
                    <button
                      type="button"
                      aria-label={`移除${spec.name}`}
                      onClick={(event) => {
                        event.preventDefault()
                        setFiles((current) => {
                          const next = { ...current }
                          delete next[spec.role]
                          return next
                        })
                      }}
                    >
                      <X size={16} />
                    </button>
                  )}
                </label>
              )
            })}
          </div>
        </section>

        <section className="form-section">
          <div className="form-section-heading">
            <span className="step-number">2</span>
            <div><h3>说明本次要求</h3><p>可以说人话，模型只负责把要求整理成下面的参数。</p></div>
          </div>
          {modelConnections.length ? (
            <div className="task-model-selector">
              <div className="task-model-icon"><Bot size={19} /></div>
              <label className="field">
                <span>本次使用的模型服务</span>
                <select
                  value={modelConnectionId}
                  onChange={(event) => {
                    const connection = modelConnections.find(
                      (item) => item.id === event.target.value,
                    )
                    setModelConnectionId(event.target.value)
                    setSelectedModel(connection?.selected_model || '')
                  }}
                >
                  {modelConnections.map((connection) => (
                    <option key={connection.id} value={connection.id}>
                      {connection.provider_name} · {connection.api_key_hint}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>执行模型</span>
                <select
                  value={selectedModel}
                  onChange={(event) => setSelectedModel(event.target.value)}
                >
                  {(modelConnections.find((item) => item.id === modelConnectionId)?.models || [])
                    .map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
            </div>
          ) : (
            <div className="model-required">
              <Bot size={18} />
              <div>
                <strong>尚未接入可选模型</strong>
                <span>可以继续使用平台默认配置，或先前往模型接入页面添加 API Key。</span>
              </div>
              <Link to="/models">接入模型</Link>
            </div>
          )}
          <label className="field">
            <span>补充说明</span>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="例如：金额差异在 1 元以内、日期相差 2 天可以视为匹配。"
              rows={4}
            />
          </label>
          <button className="button button-ai" onClick={interpret} disabled={interpreting}>
            {interpreting ? <LoaderCircle size={17} className="spin" /> : <Sparkles size={17} />}
            {interpreting ? '正在理解…' : '根据说明填写参数'}
          </button>
          {notes.map((note) => <div className="helper-note" key={note}>{note}</div>)}
        </section>

        <section className="form-section">
          <div className="form-section-heading">
            <span className="step-number">3</span>
            <div><h3>确认执行参数</h3><p>真正计算以这里的结构化参数为准。</p></div>
          </div>
          <div className="parameter-grid">
            {Object.entries(skill.input_schema.properties || {}).map(([key, property]) => (
              <ParameterField
                key={key}
                name={key}
                property={property}
                value={parameters[key]}
                onChange={(value) => setParameters((current) => ({ ...current, [key]: value }))}
              />
            ))}
          </div>
        </section>
      </div>

      <aside className="run-summary">
        <div className="summary-sticky">
          <span className="eyebrow">运行确认</span>
          <h3>执行前复核</h3>
          <dl>
            <div><dt>Skill 版本</dt><dd>v{skill.version}</dd></div>
            <div><dt>执行器</dt><dd>{skill.handler.adapter.toUpperCase()}</dd></div>
            <div><dt>理解模型</dt><dd>{selectedModel || '平台默认'}</dd></div>
            <div><dt>风险等级</dt><dd>{skill.risk.level === 'read_only' ? '只读分析' : '需要确认'}</dd></div>
            <div><dt>最长运行</dt><dd>{skill.runtime.timeout_seconds} 秒</dd></div>
          </dl>
          <div className="check-list">
            <span className={ready ? 'done' : ''}><Check size={15} /> 必要文件已上传</span>
            <span className="done"><Check size={15} /> Skill 版本将被固化</span>
            <span className="done"><LockKeyhole size={15} /> 源文件保持只读</span>
          </div>
          <button
            className="button button-primary button-full"
            onClick={submit}
            disabled={!ready || submitting}
          >
            {submitting ? <LoaderCircle className="spin" size={17} /> : <>创建运行任务 <ArrowRight size={17} /></>}
          </button>
          {!ready && <small className="submit-hint">请先上传所有必要文件。</small>}
        </div>
      </aside>
    </div>
  )
}

function ParameterField({
  name,
  property,
  value,
  onChange,
}: {
  name: string
  property: JsonSchemaProperty
  value: unknown
  onChange: (value: unknown) => void
}) {
  const inputType = property.type === 'number' || property.type === 'integer' ? 'number' : 'text'
  return (
    <label className="field">
      <span>{property.title || name}</span>
      {property.enum ? (
        <select value={String(value ?? '')} onChange={(event) => onChange(event.target.value)}>
          {property.enum.map((option) => <option key={String(option)} value={option}>{option}</option>)}
        </select>
      ) : property.type === 'boolean' ? (
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
      ) : (
        <input
          type={inputType}
          value={String(value ?? '')}
          min={property.minimum}
          max={property.maximum}
          step={property.type === 'integer' ? 1 : 'any'}
          onChange={(event) =>
            onChange(inputType === 'number' ? Number(event.target.value) : event.target.value)
          }
        />
      )}
      {property.description && <small>{property.description}</small>}
    </label>
  )
}
