import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CalendarDays,
  Check,
  FileCheck2,
  FileSpreadsheet,
  FileUp,
  LoaderCircle,
  LockKeyhole,
  Sparkles,
  ShieldCheck,
  TriangleAlert,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { SelectMenu } from '../components/SelectMenu'
import type {
  JsonSchemaProperty,
  ModelConnection,
  ServiceCredential,
  SkillManifest,
  UploadedFile,
} from '../types'

function humanSize(size: number) {
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function localIsoDate(value = new Date()) {
  const offset = value.getTimezoneOffset() * 60_000
  return new Date(value.getTime() - offset).toISOString().slice(0, 10)
}

function dateLabel(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString('zh-CN', {
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  })
}

export function SkillRun() {
  const { skillId = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [skill, setSkill] = useState<SkillManifest | null>(null)
  const [files, setFiles] = useState<Record<string, UploadedFile>>({})
  const [message, setMessage] = useState('')
  const [parameters, setParameters] = useState<Record<string, unknown>>({})
  const [loadingRole, setLoadingRole] = useState('')
  const [deletingFileId, setDeletingFileId] = useState('')
  const [interpreting, setInterpreting] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [startingWorkflow, setStartingWorkflow] = useState(false)
  const [workflowFiles, setWorkflowFiles] = useState<Record<string, UploadedFile[]>>({})
  const [workflowUploadingRole, setWorkflowUploadingRole] = useState('')
  const [reconciliationDates, setReconciliationDates] = useState<string[]>([])
  const [dateDraft, setDateDraft] = useState('')
  const [rangeStart, setRangeStart] = useState('')
  const [rangeEnd, setRangeEnd] = useState('')
  const [serviceCredential, setServiceCredential] = useState<ServiceCredential | null>(null)
  const [error, setError] = useState('')
  const [notes, setNotes] = useState<string[]>([])
  const [modelConnections, setModelConnections] = useState<ModelConnection[]>([])
  const [modelConnectionId, setModelConnectionId] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const consumedDraft = useRef(false)

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
    if (!skill || consumedDraft.current) return
    const draft = (location.state as { draft?: { message?: string; files?: UploadedFile[] } } | null)?.draft
    if (!draft) return
    consumedDraft.current = true
    if (draft.message) setMessage(draft.message)
    if (draft.files?.length) {
      if (skill.execution_mode === 'guided_workflow') {
        const grouped = draft.files.reduce<Record<string, UploadedFile[]>>((current, file) => {
          current[file.role] = [...(current[file.role] || []), file]
          return current
        }, {})
        setWorkflowFiles(grouped)
      } else {
        setFiles(Object.fromEntries(draft.files.map((file) => [file.role, file])))
      }
    }
    navigate(location.pathname, { replace: true, state: null })
  }, [location.pathname, location.state, navigate, skill])

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

  useEffect(() => {
    if (skill?.execution_mode !== 'guided_workflow') return
    api.serviceCredential('zhiyun')
      .then(setServiceCredential)
      .catch((reason: Error) => setError(reason.message))
  }, [skill?.execution_mode])

  const ready = useMemo(() => {
    if (!skill) return false
    return skill.file_inputs.every((spec) => !spec.required || Boolean(files[spec.role]))
  }, [files, skill])

  const workflowReady = useMemo(() => {
    if (!skill || skill.execution_mode !== 'guided_workflow') return false
    return Boolean(
      reconciliationDates.length > 0 &&
      modelConnectionId &&
      selectedModel &&
      serviceCredential?.configured &&
      skill.file_inputs.every(
        (spec) => !spec.required || (workflowFiles[spec.role]?.length || 0) >= (spec.min_files || 1),
      ),
    )
  }, [modelConnectionId, reconciliationDates, selectedModel, serviceCredential?.configured, skill, workflowFiles])

  const addDates = (values: string[]) => {
    setError('')
    const normalized = Array.from(new Set([...reconciliationDates, ...values])).sort()
    if (normalized.length > 7) {
      setError('单个批次最多选择 7 个核销日期。')
      return
    }
    setReconciliationDates(normalized)
  }

  const addSingleDate = (value: string) => {
    setDateDraft(value)
    if (!value) return
    addDates([value])
    window.setTimeout(() => setDateDraft(''), 0)
  }

  const addDateRange = () => {
    if (!rangeStart || !rangeEnd) {
      setError('请选择连续日期范围的开始日期和结束日期。')
      return
    }
    if (rangeStart > rangeEnd) {
      setError('开始日期不能晚于结束日期。')
      return
    }
    const values: string[] = []
    const cursor = new Date(`${rangeStart}T00:00:00`)
    const end = new Date(`${rangeEnd}T00:00:00`)
    while (cursor <= end && values.length <= 7) {
      values.push(localIsoDate(cursor))
      cursor.setDate(cursor.getDate() + 1)
    }
    if (values.length > 7 || new Set([...reconciliationDates, ...values]).size > 7) {
      setError('连续日期范围与已选日期合计不能超过 7 天。')
      return
    }
    addDates(values)
  }

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

  const removeFile = async (role: string, file: UploadedFile) => {
    setDeletingFileId(file.id)
    setError('')
    try {
      await api.deleteFile(file.id)
      setFiles((current) => {
        const next = { ...current }
        delete next[role]
        return next
      })
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setDeletingFileId('')
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
    if (!skill || skill.execution_mode !== 'guided_workflow') return
    setStartingWorkflow(true)
    setError('')
    try {
      if (!reconciliationDates.length) throw new Error('请至少选择一个核销日期。')
      if (!modelConnectionId || !selectedModel) throw new Error('请选择模型服务和执行模型。')
      if (!workflowReady) throw new Error('请先上传全部必需文件。')
      if (!serviceCredential?.configured) {
        throw new Error('尚未配置智云登录凭据，请先在模型接入页保存智云账号密码。')
      }
      const batch = await api.startWorkflowBatch(
        skill.id,
        reconciliationDates,
        Object.fromEntries(
          Object.entries(workflowFiles).map(([role, items]) => [role, items.map((item) => item.id)]),
        ),
        modelConnectionId,
        selectedModel,
      )
      navigate(`/workflow-batches/${batch.id}`)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setStartingWorkflow(false)
    }
  }

  const uploadWorkflowFiles = async (role: string, selected: FileList | null) => {
    if (!selected?.length) return
    setWorkflowUploadingRole(role)
    setError('')
    try {
      const uploaded: UploadedFile[] = []
      for (const file of Array.from(selected)) uploaded.push(await api.upload(role, file))
      setWorkflowFiles((current) => ({ ...current, [role]: [...(current[role] || []), ...uploaded] }))
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setWorkflowUploadingRole('')
    }
  }

  const removeWorkflowFile = async (role: string, file: UploadedFile) => {
    setError('')
    try {
      await api.deleteFile(file.id)
      setWorkflowFiles((current) => ({
        ...current,
        [role]: (current[role] || []).filter((item) => item.id !== file.id),
      }))
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  if (!skill && !error) {
    return <div className="loading-screen" aria-live="polite"><LoaderCircle className="spin" />正在读取 Skill…</div>
  }

  if (!skill) {
    return <div className="alert alert-error" role="alert"><TriangleAlert size={18} />{error}</div>
  }

  if (skill.execution_mode === 'guided_workflow') {
    return (
      <div className="workflow-launch page-stack">
        <Link to="/skills" className="back-link"><ArrowLeft size={16} /> 返回工具列表</Link>
        <header className="workflow-launch-hero">
          <div className="workflow-start-icon"><Bot size={28} /></div>
          <span className="skill-category">{skill.categories?.[0] || skill.category}</span>
          <h2>{skill.name}</h2>
          <p>{skill.description}</p>
          <div className="workflow-gates">
            <span><Check size={16} /> 前置资料完整校验</span>
            <span><Check size={16} /> 智云数据自动读取</span>
            <span><LockKeyhole size={16} /> 写前校验通过后仅写副本</span>
          </div>
        </header>

        {error && <div className="alert alert-error" role="alert"><TriangleAlert size={18} />{error}</div>}

        <div className="workflow-launch-grid">
          <main className="workflow-launch-main">
            <section className="workflow-form-card">
              <div className="workflow-form-heading">
                <span className="step-number">1</span>
                <div><h3>上传前置文件</h3><p>请上传本次核销使用的两张表，平台只读取隔离副本。</p></div>
              </div>
              <div className="workflow-prereq-grid">
                {skill.file_inputs.map((spec) => {
                  const roleFiles = workflowFiles[spec.role] || []
                  return (
                    <div className="workflow-prereq-upload" key={spec.role}>
                      <label className="workflow-prereq-dropzone">
                        <input
                          type="file"
                          multiple={spec.multiple}
                          accept={spec.extensions.map((item) => `.${item}`).join(',')}
                          disabled={workflowUploadingRole === spec.role || startingWorkflow}
                          onChange={(event) => uploadWorkflowFiles(spec.role, event.target.files)}
                        />
                        <FileSpreadsheet size={23} />
                        <strong>{spec.name}<b>*</b></strong>
                        <span>{spec.description}</span>
                        <small>支持 {spec.extensions.join('、').toUpperCase()} · 至少 {spec.min_files || 1} 个</small>
                        {workflowUploadingRole === spec.role && <LoaderCircle className="spin" size={17} />}
                      </label>
                      {roleFiles.length > 0 && (
                        <div className="workflow-prereq-files">
                          {roleFiles.map((file) => (
                            <div className="workflow-prereq-file" key={file.id}>
                              <FileCheck2 size={15} />
                              <span title={file.name}>{file.name}</span>
                              <small>{humanSize(file.size_bytes)}</small>
                              <button
                                type="button"
                                aria-label={`删除${file.name}`}
                                disabled={startingWorkflow}
                                onClick={() => removeWorkflowFile(spec.role, file)}
                              ><X size={14} /></button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </section>

            <section className="workflow-form-card">
              <div className="workflow-form-heading">
                <span className="step-number">2</span>
                <div><h3>选择核销日期</h3><p>最多选择 7 天；平台会从早到晚逐日串行核销。</p></div>
              </div>
              <div className="workflow-multi-date">
                <label className="workflow-date-field field">
                  <span><CalendarDays size={16} /> 添加单个日期</span>
                  <div className="date-picker-control">
                    <button className="date-picker-trigger" type="button" tabIndex={-1} aria-hidden="true">
                      <strong>选择并添加日期</strong>
                      <CalendarDays size={16} />
                    </button>
                    <input className="date-native-input" aria-label="添加核销日期" type="date" value={dateDraft} max={localIsoDate()} onChange={(event) => addSingleDate(event.target.value)} />
                  </div>
                </label>
                <div className="workflow-date-range">
                  <div className="field"><span>连续日期开始</span><input aria-label="连续日期开始" type="date" value={rangeStart} max={localIsoDate()} onChange={(event) => setRangeStart(event.target.value)} /></div>
                  <div className="field"><span>连续日期结束</span><input aria-label="连续日期结束" type="date" value={rangeEnd} min={rangeStart || undefined} max={localIsoDate()} onChange={(event) => setRangeEnd(event.target.value)} /></div>
                  <button className="button button-secondary" type="button" onClick={addDateRange}>添加日期范围</button>
                </div>
                <div className="workflow-selected-dates" aria-live="polite">
                  <div><strong>已选日期</strong><span>{reconciliationDates.length}/7 天</span></div>
                  {reconciliationDates.length ? (
                    <div className="workflow-date-chips">
                      {reconciliationDates.map((value, index) => (
                        <span className="workflow-date-chip" key={value}>
                          <b>{index + 1}</b>{dateLabel(value)}
                          <button type="button" aria-label={`移除${value}`} onClick={() => setReconciliationDates((current) => current.filter((item) => item !== value))}><X size={13} /></button>
                        </span>
                      ))}
                    </div>
                  ) : <p>还没有选择日期。可以逐个添加，也可以添加一段连续日期。</p>}
                </div>
              </div>
              <div className="workflow-batch-note"><LockKeyhole size={15} /><span>后一天只会在前一天写入和回读成功后开始；失败时自动暂停。</span></div>
            </section>

            <section className="workflow-form-card">
              <div className="workflow-form-heading">
                <span className="step-number">3</span>
                <div><h3>选择模型服务</h3><p>模型负责理解和控制流程，金额计算仍由固定脚本执行。</p></div>
              </div>
              {modelConnections.length ? (
                <div className="task-model-selector">
                  <div className="task-model-icon"><Bot size={19} /></div>
                  <div className="field"><span>模型服务</span><SelectMenu value={modelConnectionId} ariaLabel="模型服务" onChange={(value) => { const connection = modelConnections.find((item) => item.id === value); setModelConnectionId(value); setSelectedModel(connection?.selected_model || '') }} options={modelConnections.map((connection) => ({ value: connection.id, label: connection.provider_name, description: connection.api_key_hint }))} /></div>
                  <div className="field"><span>执行模型</span><SelectMenu value={selectedModel} ariaLabel="执行模型" onChange={setSelectedModel} options={(modelConnections.find((item) => item.id === modelConnectionId)?.models || []).map((model) => ({ value: model, label: model }))} /></div>
                </div>
              ) : (
                <div className="model-required">
                  <Bot size={18} />
                  <div><strong>需要先接入模型服务</strong><span>请先在模型接入页保存可用的 API Key。</span></div>
                  <Link to="/models">接入模型</Link>
                </div>
              )}
              <div className={`workflow-credential-note ${serviceCredential?.configured ? 'is-ready' : ''}`}>
                <ShieldCheck size={16} />
                {serviceCredential?.configured
                  ? `智云凭据已安全保存：${serviceCredential.account_hint}`
                  : '智云凭据尚未配置，开始核销前需要先保存账号密码。'}
              </div>
            </section>
          </main>

          <aside className="workflow-launch-summary">
            <div className="workflow-summary-card">
              <span className="eyebrow">开始前检查</span>
              <h3>核实执行条件</h3>
              <p>所有条件满足后，平台会调用模型并排队执行核销 Skill。</p>
              <div className="workflow-check-list">
                <span className={(skill.file_inputs.every((spec) => !spec.required || (workflowFiles[spec.role]?.length || 0) >= (spec.min_files || 1))) ? 'done' : ''}><Check size={15} /> 前置文件已上传完整</span>
                <span className={reconciliationDates.length ? 'done' : ''}><CalendarDays size={15} /> 已选择 {reconciliationDates.length} 个核销日期</span>
                <span className={modelConnectionId && selectedModel ? 'done' : ''}><Bot size={15} /> 模型服务已选择</span>
                <span className={serviceCredential?.configured ? 'done' : ''}><ShieldCheck size={15} /> 智云凭据可用</span>
              </div>
              <button
                type="button"
                className="button button-primary workflow-start-button"
                disabled={!workflowReady || startingWorkflow}
                onClick={startWorkflow}
              >
                {startingWorkflow
                  ? <><LoaderCircle className="spin" size={17} /> 正在开始核销…</>
                  : <>{reconciliationDates.length ? `开始 ${reconciliationDates.length} 天核销` : '开始核销'} <ArrowRight size={17} /></>}
              </button>
              {!workflowReady && <small className="submit-hint">请完成上面的文件、日期和模型选择。</small>}
            </div>
          </aside>
        </div>
      </div>
    )
  }

  return (
    <div className="run-builder">
      <div className="run-builder-main">
        <Link to="/skills" className="back-link"><ArrowLeft size={16} /> 返回工具列表</Link>
        <div className="run-title">
          <span className="skill-category">{skill.categories?.[0] || skill.category}</span>
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
                      aria-label={`删除${uploaded.name}`}
                      title="删除上传文件"
                      disabled={deletingFileId === uploaded.id || submitting}
                      onClick={(event) => {
                        event.preventDefault()
                        removeFile(spec.role, uploaded)
                      }}
                    >
                      {deletingFileId === uploaded.id
                        ? <LoaderCircle className="spin" size={16} />
                        : <X size={16} />}
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
              <div className="field"><span>本次使用的模型服务</span><SelectMenu value={modelConnectionId} ariaLabel="本次使用的模型服务" onChange={(value) => { const connection = modelConnections.find((item) => item.id === value); setModelConnectionId(value); setSelectedModel(connection?.selected_model || '') }} options={modelConnections.map((connection) => ({ value: connection.id, label: connection.provider_name, description: connection.api_key_hint }))} /></div>
              <div className="field"><span>执行模型</span><SelectMenu value={selectedModel} ariaLabel="执行模型" onChange={setSelectedModel} options={(modelConnections.find((item) => item.id === modelConnectionId)?.models || []).map((model) => ({ value: model, label: model }))} /></div>
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
            <div><dt>预计耗时</dt><dd>约 {skill.estimated_minutes || 1} 分钟</dd></div>
            <div><dt>结果内容</dt><dd>{skill.output_summary || '结果文件和业务摘要'}</dd></div>
            <div><dt>风险等级</dt><dd>{skill.risk.level === 'read_only' ? '只读分析' : '需要确认'}</dd></div>
          </dl>
          <div className="check-list">
            <span className={ready ? 'done' : ''}><Check size={15} /> 必要文件已上传</span>
            <span className="done"><Check size={15} /> 执行配置将写入审计记录</span>
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
        <SelectMenu value={String(value ?? '')} ariaLabel={property.title || name} onChange={(next) => onChange(next)} options={property.enum.map((option) => ({ value: String(option), label: String(option) }))} />
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
