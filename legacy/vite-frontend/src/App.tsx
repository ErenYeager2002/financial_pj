import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Admin } from './pages/Admin'
import { ChangePassword } from './pages/ChangePassword'
import { Dashboard } from './pages/Dashboard'
import { Login } from './pages/Login'
import { ModelSettings } from './pages/ModelSettings'
import { RunDetail } from './pages/RunDetail'
import { RunList } from './pages/RunList'
import { SkillList } from './pages/SkillList'
import { SkillRun } from './pages/SkillRun'
import { WorkflowChat } from './pages/WorkflowChat'
import { WorkflowBatch } from './pages/WorkflowBatch'
import { RequireAdmin } from './auth/RequireAdmin'
import { RequireAuth } from './auth/RequireAuth'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/change-password"
        element={
          <RequireAuth>
            <ChangePassword />
          </RequireAuth>
        }
      />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="skills" element={<SkillList />} />
        <Route path="skills/:skillId" element={<SkillRun />} />
        <Route path="runs" element={<RunList />} />
        <Route path="runs/:runId" element={<RunDetail />} />
        <Route path="workflows/:workflowId" element={<WorkflowChat />} />
        <Route path="workflow-batches/:batchId" element={<WorkflowBatch />} />
        <Route
          path="admin"
          element={
            <RequireAdmin>
              <Admin />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
