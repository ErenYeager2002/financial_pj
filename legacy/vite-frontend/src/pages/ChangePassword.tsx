import { FormEvent, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { KeyRound, Loader2, Save } from 'lucide-react'
import { api } from '../api'
import type { UserSession } from '../types'

export function ChangePassword() {
  const navigate = useNavigate()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    if (newPassword.length < 8) {
      setError('新密码至少 8 位。')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致。')
      return
    }
    setLoading(true)
    try {
      await api.changePassword(currentPassword, newPassword)
      setDone(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : '修改失败')
    } finally {
      setLoading(false)
    }
  }

  if (done) {
    return <Navigate to="/" replace />
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <div className="brand-mark">
            <KeyRound size={22} strokeWidth={1.8} />
          </div>
          <div>
            <strong>修改初始密码</strong>
            <span>首次登录需要设置你自己的密码</span>
          </div>
        </div>

        <label className="login-field">
          <span>当前密码</span>
          <div className="login-input-wrap">
            <KeyRound size={16} />
            <input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
            />
          </div>
        </label>

        <label className="login-field">
          <span>新密码（至少 8 位）</span>
          <div className="login-input-wrap">
            <KeyRound size={16} />
            <input
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
            />
          </div>
        </label>

        <label className="login-field">
          <span>再次输入新密码</span>
          <div className="login-input-wrap">
            <KeyRound size={16} />
            <input
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
            />
          </div>
        </label>

        {error && <p className="login-error">{error}</p>}

        <button className="login-submit" type="submit" disabled={loading}>
          {loading ? <Loader2 size={16} className="spin" /> : <Save size={16} />}
          {loading ? '正在修改…' : '修改并进入平台'}
        </button>
      </form>
    </div>
  )
}
