import { ArrowRight, Bot, ListFilter } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import type { RunRecord, WorkflowRecord } from '../types'

export function RunList() {
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([])
  const [filter, setFilter] = useState('all')

  useEffect(() => {
    const load = () =>
      Promise.all([api.runs(), api.workflows()]).then(([runData, workflowData]) => {
        setRuns(runData)
        setWorkflows(workflowData)
      })
    load()
    const timer = window.setInterval(load, 3000)
    return () => window.clearInterval(timer)
  }, [])

  const filtered = useMemo(
    () =>
      filter === 'all'
        ? runs
        : runs.filter((run) =>
            filter === 'active'
              ? ['queued', 'running', 'waiting_user_action', 'waiting_confirmation'].includes(run.state)
              : run.state === filter,
          ),
    [filter, runs],
  )
  const filteredWorkflows = useMemo(
    () =>
      filter === 'all'
        ? workflows
        : workflows.filter((workflow) =>
            filter === 'active'
              ? ['active', 'running', 'waiting_confirmation'].includes(workflow.state)
              : workflow.state === filter,
          ),
    [filter, workflows],
  )

  return (
    <div className="page-stack">
      <div className="page-intro">
        <div>
          <span className="eyebrow">任务审计</span>
          <h2>部门运行记录</h2>
          <p>每次运行都保存 Skill 版本、文件哈希、参数、进度、结果和异常。</p>
        </div>
      </div>
      <div className="filter-tabs table-filters">
        {[
          ['all', '全部'],
          ['active', '处理中'],
          ['succeeded', '已完成'],
          ['failed', '失败'],
          ['cancelled', '已取消'],
        ].map(([value, label]) => (
          <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>
            {label}
          </button>
        ))}
      </div>
      {filteredWorkflows.length > 0 && (
        <section className="workflow-records">
          <div className="section-heading">
            <div><span className="eyebrow">人在环任务</span><h2>对话式工作流</h2></div>
          </div>
          <div className="workflow-record-grid">
            {filteredWorkflows.map((workflow) => (
              <Link
                className="workflow-record-card"
                to={`/workflows/${workflow.id}`}
                key={workflow.id}
              >
                <div className="run-glyph"><Bot size={18} /></div>
                <div>
                  <strong>{workflow.skill_name}</strong>
                  <span>{workflow.progress_message}</span>
                  <small>
                    {new Date(workflow.created_at).toLocaleString('zh-CN')}
                    {' · '}{workflow.model_name}
                  </small>
                </div>
                <StatusBadge state={workflow.state} />
                <ArrowRight size={16} />
              </Link>
            ))}
          </div>
        </section>
      )}
      <div className="table-panel">
        <table>
          <thead>
            <tr>
              <th>任务</th>
              <th>执行人</th>
              <th>Skill 版本</th>
              <th>创建时间</th>
              <th>进度</th>
              <th>状态</th>
              <th><span className="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((run) => (
              <tr key={run.id}>
                <td><strong>{run.skill_name}</strong><small>{run.id.slice(0, 8)}</small></td>
                <td>{run.owner_name}</td>
                <td>v{run.skill_version}</td>
                <td>{new Date(run.created_at).toLocaleString('zh-CN')}</td>
                <td>
                  <div className="mini-progress"><span style={{ width: `${run.progress}%` }} /></div>
                  <small>{run.progress}%</small>
                </td>
                <td><StatusBadge state={run.state} /></td>
                <td><Link className="row-action" to={`/runs/${run.id}`}>详情 <ArrowRight size={15} /></Link></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && !filteredWorkflows.length && (
          <div className="empty-state"><ListFilter size={28} /><h3>当前筛选下没有记录</h3></div>
        )}
      </div>
    </div>
  )
}
