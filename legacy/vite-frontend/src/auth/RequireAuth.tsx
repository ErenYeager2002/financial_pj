import { Navigate, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { UserSession } from '../types'

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const [session, setSession] = useState<UserSession | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    api
      .session()
      .then((value) => {
        if (active) setSession(value)
      })
      .catch(() => {
        if (active) setSession(null)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [location.pathname])

  if (loading) {
    return <div className="auth-loading">正在校验登录状态…</div>
  }
  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (
    session.must_change_password &&
    location.pathname !== '/change-password'
  ) {
    return <Navigate to="/change-password" replace />
  }
  return children
}
