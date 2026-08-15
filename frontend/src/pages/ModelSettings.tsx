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
import { SelectMenu } from '../components/SelectMenu'
import type { ModelConnection, ModelProviderInfo } from '../types'

const PLACEHOLDER_PROVIDER = { value: '', label: '请选择供应商' }

export function ModelSettings() {
  const [connections, setConnections] = useState<ModelConnection[]>([])
  const [providers, setProviders] = useState<ModelProviderInfo[]>([])
  const [providerId, setProviderId] = useState('')
  const [modelName, setModelName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)

  const selectedProvider = providers.find((item) => item.id === providerId)

  const load = async () => {
    try {
      const [items, available] = await Promise.all([
        api.modelConnections(),
        api.modelProviders(),
      ])
      setConnections(items)
      setProviders(available)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const showModelField =
    !!selectedProvider &&
    (selectedProvider.discovery_mode === 'manual' || selectedProvider.discovery_mode === 'hybrid')

  const modelRequired = !!selectedProvider && selectedProvider.discovery_mode === 'manual'

  const canConnect =
    !!providerId &&
    !!apiKey.trim() &&
    (selectedProvider?.id !== 'custom_openai' || !!baseUrl.trim()) &&
    (!modelRequired || !!modelName.trim())

  const changeProvider = (next: string) => {
    setProviderId(next)
    setModelName('')
    if (next !== 'custom_openai') setBaseUrl('')
  }

  const connect = async () => {
    if (!providerId) {
      setError('请先选择模型供应商。')
      return
    }
    if (!apiKey.trim()) {
      setError('请输入 API Key。')
      return
    }
    if (selectedProvider?.id === 'custom_openai' && !baseUrl.trim()) {
      setError('请输入自定义服务地址（HTTPS）。')
      return
    }
    if (modelRequired && !modelName.trim()) {
      setError('该供应商需要填写模型名称或部署 ID。')
      return
    }
    setConnecting(true)
    setError('')
    setNotice('')
    try {
      const connection = await api.connectModel(
        providerId,
        apiKey.trim(),
        baseUrl.trim(),
        modelName.trim(),
      )
      setApiKey('')
      setBaseUrl('')
      setModelName('')
      setProviderId('')
      setConnections((current) => [
        connection,
        ...current.filter((item) => item.id !== connection.id),
      ])
      setNotice(`已接入 ${connection.provider_name}，发现 ${connection.models.length} 个可用模型。`)
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
          <p>选择供应商并输入 API Key，平台只向所选供应商验证密钥，并读取支持 Tool Calling 的模型。</p>
        </div>
        <div className="trust-pill"><ShieldCheck size={16} /> 密钥只发送给所选供应商，并在服务端加密保存</div>
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
            <p>密钥只会发送给所选供应商用于验证，平台仅保存加密后的凭据，不会发送给其他供应商。</p>
          </div>
        </div>
        <div className="connect-fields">
          <label className="field">
            <span>模型供应商</span>
            <SelectMenu
              value={providerId}
              ariaLabel="模型供应商"
              onChange={changeProvider}
              options={[
                PLACEHOLDER_PROVIDER,
                ...providers.map((item) => ({
                  value: item.id,
                  label: item.name,
                  description:
                    item.discovery_mode === 'manual'
                      ? '手动填写模型名称'
                      : item.discovery_mode === 'hybrid'
                        ? '自动发现，可手动填写模型或部署 ID'
                        : '自动发现模型',
                })),
              ]}
              disabled={connecting}
            />
            <small>当前支持阿里云百炼、DeepSeek、智谱、Moonshot、OpenAI 与火山方舟；自定义服务仅管理员可用。</small>
          </label>
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
                  disabled={!providerId}
                />
                <button
                  type="button"
                  onClick={() => setShowKey((current) => !current)}
                  aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
                >
                  {showKey ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              <small>密钥仅用于验证所选供应商，不会用于探测其他供应商。</small>
            </label>
            <button
              className="button button-primary connect-button"
              onClick={connect}
              disabled={connecting || !canConnect}
            >
              {connecting ? <LoaderCircle className="spin" size={17} /> : <Bot size={17} />}
              {connecting ? '正在验证…' : '验证并接入'}
            </button>
          </div>
          {selectedProvider?.id === 'custom_openai' && (
            <label className="field">
              <span>服务地址（HTTPS）</span>
              <input
                type="url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://your-endpoint.example.com/v1"
                autoComplete="off"
                spellCheck={false}
              />
              <small>仅管理员可见；服务端只允许访问管理员配置的可信 HTTPS 主机，并执行公网地址校验、不跟随重定向。</small>
            </label>
          )}
          {showModelField && (
            <label className="field">
              <span>{selectedProvider?.id === 'custom_openai' ? '模型名称' : '模型名称 / 部署 ID'}</span>
              <input
                type="text"
                value={modelName}
                onChange={(event) => setModelName(event.target.value)}
                placeholder={selectedProvider?.id === 'doubao' ? 'doubao-seed-... 或 ep-...' : '模型名称'}
                autoComplete="off"
                spellCheck={false}
              />
              <small>
                {selectedProvider?.discovery_mode === 'manual'
                  ? '手动模式必填，不读取模型目录。'
                  : '模型名称可选；留空时自动发现，无法发现时请手工填写模型或部署 ID。'}
              </small>
            </label>
          )}
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
                <SelectMenu
                  value={connection.selected_model}
                  ariaLabel={`默认执行模型 ${connection.provider_name}`}
                  onChange={(model) => updateModel(connection, model)}
                  options={connection.models.map((model) => ({ value: model, label: model }))}
                  disabled={busyId === connection.id}
                />
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
              <p>选择供应商并输入 API Key，平台会完成密钥验证与模型发现。</p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
