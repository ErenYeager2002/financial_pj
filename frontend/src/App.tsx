import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Admin } from './pages/Admin'
import { Dashboard } from './pages/Dashboard'
import { RunDetail } from './pages/RunDetail'
import { RunList } from './pages/RunList'
import { SkillList } from './pages/SkillList'
import { SkillRun } from './pages/SkillRun'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="skills" element={<SkillList />} />
        <Route path="skills/:skillId" element={<SkillRun />} />
        <Route path="runs" element={<RunList />} />
        <Route path="runs/:runId" element={<RunDetail />} />
        <Route path="admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

