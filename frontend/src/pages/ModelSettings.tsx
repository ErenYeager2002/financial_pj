import {
  Bot,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  Server,
  ShieldCheck,
  Trash2,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { ModelConnection } from '../types'

export function ModelSettings() {
  const [connections, setConnections] = useState<ModelConnection[]>([])
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      setConnections(await api.modelConnections())
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const connect = async () => {
    if (!apiKey.trim()) {
      setError('请输入 API Key。')
      return
    }
    setConnecting(true)
    setError('')
    setNotice('')
    try {
      const connection = await api.connectModel(apiKey.trim())
      setApiKey('')
      setConnections((current) => [
        connection,
        ...current.filter((item) => item.id !== connection.id),
      ])
      setNotice(`已识别 ${connection.provider_name}，发现 ${connection.models.length} 个可用模型。`)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setConnecting(false)
    }
  }

  const updateModel = async (connection: ModelConnection, model: string) => {
    setBusyId(connection.id)
    setError('')
    try {
      const updated = await api.selectModel(connection.id, model)
      replaceConnection(updated)
      setNotice(`默认模型已切换为 ${updated.selected_model}。`)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusyId('')
    }
  }

  const refresh = async (connection: ModelConnection) => {
    setBusyId(connection.id)
    setError('')
    try {
      const updated = await api.refreshModel(connection.id)
      replaceConnection(updated)
      setNotice(`模型列表已刷新，共 ${updated.models.length} 个可用模型。`)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusyId('')
    }
  }

  const remove = async (connection: ModelConnection) => {
    if (!window.confirm(`确定移除 ${connection.provider_name} 连接吗？`)) return
    setBusyId(connection.id)
    setError('')
    try {
      await api.deleteModel(connection.id)
      setConnections((current) => current.filter((item) => item.id !== connection.id))
      setNotice('模型连接已移除，服务端不再保留该 API Key。')
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusyId('')
    }
  }

  const replaceConnection = (updated: ModelConnection) => {
    setConnections((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    )
  }

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <span className="eyebrow">模型服务</span>
          <h2>模型接入</h2>
          <p>只输入 API Key，平台自动识别供应商并读取支持 Tool Calling 的模型。</p>
        </div>
        <div className="trust-pill"><ShieldCheck size={16} /> 密钥加密保存，不回传浏览器</div>
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          <TriangleAlert size={18} />{error}
        </div>
      )}
      {notice && (
        <div className="alert alert-success" aria-live="polite">
          <CheckCircle2 size={18} />{notice}
        </div>
      )}

      <section className="model-connect-panel">
        <div className="model-connect-copy">
          <div className="model-connect-icon"><KeyRound size={24} /></div>
          <div>
            <h3>接入一个模型服务</h3>
            <p>平台会向允许的供应商端点验证密钥，仅保存加密后的凭据。</p>
          </div>
        </div>
        <div className="key-entry">
          <label className="field">
            <span>API Key</span>
            <div className="secret-input">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') connect()
                }}
                placeholder="sk-..."
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="button"
                onClick={() => setShowKey((current) => !current)}
                aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
              >
                {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <small>当前支持自动识别阿里云百炼千问，后续可扩展更多供应商。</small>
          </label>
          <button
            className="button button-primary connect-button"
            onClick={connect}
            disabled={connecting || !apiKey.trim()}
          >
            {connecting ? <LoaderCircle className="spin" size={17} /> : <Bot size={17} />}
            {connecting ? '正在识别模型…' : '自动识别并接入'}
          </button>
        </div>
      </section>

      <section>
        <div className="section-heading">
          <div><span className="eyebrow">连接列表</span><h2>已接入模型服务</h2></div>
          <span className="connection-count">{connections.length} 个连接</span>
        </div>
        <div className="model-connection-grid">
          {loading && (
            <div className="loading-screen model-empty">
              <LoaderCircle className="spin" size={20} /> 正在读取模型连接…
            </div>
          )}
          {!loading && connections.map((connection) => (
            <article className="model-connection-card" key={connection.id}>
              <div className="connection-card-head">
                <div className="provider-mark"><Server size={20} /></div>
                <div>
                  <strong>{connection.provider_name}</strong>
                  <span>{connection.api_key_hint}</span>
                </div>
                <span className={`connection-state ${connection.status}`}>
                  {connection.status === 'connected' ? '已连接' : '需检查'}
                </span>
              </div>
              <label className="field">
                <span>默认执行模型</span>
                <select
                  value={connection.selected_model}
                  onChange={(event) => updateModel(connection, event.target.value)}
                  disabled={busyId === connection.id}
                >
                  {connection.models.map((model) => (
                    <option key={model} value={model}>{model}</option>
                  ))}
                </select>
                <small>
                  共 {connection.models.length} 个模型 · 最后验证{' '}
                  {new Date(connection.last_checked_at).toLocaleString('zh-CN')}
                </small>
              </label>
              <div className="connection-actions">
                <button
                  className="button button-secondary"
                  onClick={() => refresh(connection)}
                  disabled={busyId === connection.id}
                >
                  {busyId === connection.id
                    ? <LoaderCircle className="spin" size={16} />
                    : <RefreshCw size={16} />}
                  刷新模型
                </button>
                <button
                  className="button button-danger-ghost"
                  onClick={() => remove(connection)}
                  disabled={busyId === connection.id}
                >
                  <Trash2 size={16} /> 移除
                </button>
              </div>
            </article>
          ))}
          {!loading && !connections.length && (
            <div className="empty-state model-empty">
              <Bot size={28} />
              <h3>尚未接入模型</h3>
              <p>在上方输入 API Key，平台会自动完成识别与模型发现。</p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
