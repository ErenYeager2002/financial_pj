import { GitBranch, RefreshCcw, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { SkillManifest } from '../types'

export function Admin() {
  const [skills, setSkills] = useState<SkillManifest[]>([])
  const [message, setMessage] = useState('')
  const [errors, setErrors] = useState<Array<{ path: string; error: string }>>([])

  const load = () => api.skills().then(setSkills)
  useEffect(() => { load() }, [])

  const reload = async () => {
    try {
      const result = await api.reloadRegistry()
      setErrors(result.errors)
      setMessage(`Registry 已重新加载，共发现 ${result.skills} 个 Skill。`)
      await load()
    } catch (reason) {
      setMessage((reason as Error).message)
    }
  }

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <span className="eyebrow">SKILL 注册中心</span>
          <h2>已批准版本</h2>
          <p>普通员工运行的是发布时固化的只读副本，只有管理员可以重新加载 Registry。</p>
        </div>
        <button className="button button-primary" onClick={reload}><RefreshCcw size={16} /> 重新扫描</button>
      </div>
      {message && <div className="alert alert-info"><ShieldCheck size={18} />{message}</div>}
      {errors.map((item) => (
        <div className="alert alert-error" role="alert" key={item.path}><TriangleAlert size={18} />{item.path}：{item.error}</div>
      ))}
      <div className="table-panel">
        <table>
          <thead><tr><th>Skill</th><th>分类</th><th>版本</th><th>状态</th><th>执行器</th><th>来源</th><th>Commit</th></tr></thead>
          <tbody>
            {skills.map((skill) => (
              <tr key={skill.id}>
                <td>
                  <strong>{skill.name}</strong>
                  <small>{skill.id}</small>
                  {skill.blocked_reason && <small>{skill.blocked_reason}</small>}
                </td>
                <td>{skill.category}</td>
                <td>v{skill.version}</td>
                <td><span className={`publish-state ${skill.status}`}>{skill.status}</span></td>
                <td>{skill.handler.adapter.toUpperCase()}</td>
                <td>{skill.source}</td>
                <td><span className="commit"><GitBranch size={14} />{skill.commit_sha?.slice(0, 10) || '未提交'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
