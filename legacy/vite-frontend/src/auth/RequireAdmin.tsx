import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { api } from '../api'
import type { UserSession } from '../types'

export function RequireAdmin({ children }: { children: React.ReactNode }) {
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
    return <div className="auth-loading">正在校验管理员身份…</div>
  }
  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (session.role !== 'skill_admin') {
    return <Navigate to="/" replace />
  }
  return children
}
