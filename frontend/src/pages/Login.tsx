import { FormEvent, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Loader2, Lock, LogIn, Sparkles, User } from 'lucide-react'
import { api } from '../api'
import type { UserSession } from '../types'

export function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [session, setSession] = useState<UserSession | null>(null)

  const from = (location.state as { from?: string } | null)?.from || '/'

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      const value = await api.login(username, password)
      setSession(value)
      navigate(value.must_change_password ? '/change-password' : from, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  if (session) {
    return <Navigate to={from} replace />
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <div className="brand-mark">
            <Sparkles size={22} strokeWidth={1.8} />
          </div>
          <div>
            <strong>Finance Skills</strong>
            <span>财务数字员工平台 · 员工登录</span>
          </div>
        </div>

        <label className="login-field">
          <span>用户名</span>
          <div className="login-input-wrap">
            <User size={16} />
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入用户名"
              required
            />
          </div>
        </label>

        <label className="login-field">
          <span>密码</span>
          <div className="login-input-wrap">
            <Lock size={16} />
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入密码"
              required
            />
          </div>
        </label>

        {error && <p className="login-error">{error}</p>}

        <button className="login-submit" type="submit" disabled={loading}>
          {loading ? <Loader2 size={16} className="spin" /> : <LogIn size={16} />}
          {loading ? '正在登录…' : '登录'}
        </button>
      </form>
    </div>
  )
}
