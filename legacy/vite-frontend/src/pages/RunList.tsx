import { ArrowRight, Bot, Layers3, ListChecks, ListFilter, LoaderCircle, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { StatusBadge } from '../components/StatusBadge'
import type { RunRecord, WorkflowBatchRecord, WorkflowRecord } from '../types'

export function RunList() {
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([])
  const [batches, setBatches] = useState<WorkflowBatchRecord[]>([])
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [runData, workflowData, batchData] = await Promise.all([
          api.runs(),
          api.workflows(),
          api.workflowBatches(),
        ])
        if (!active) return
        setRuns(runData)
        setWorkflows(workflowData)
        setBatches(batchData)
        setError('')
      } catch (loadError) {
        if (!active) return
        setError(loadError instanceof Error ? loadError.message : '运行记录读取失败，请稍后重试。')
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    const timer = window.setInterval(load, 3000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
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
  const filteredBatches = useMemo(
    () =>
      filter === 'all'
        ? batches
        : batches.filter((batch) =>
            filter === 'active'
              ? ['queued', 'running'].includes(batch.state)
              : batch.state === filter,
          ),
    [batches, filter],
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
      <div className="filter-tabs table-filters" role="tablist" aria-label="运行记录筛选">
        {[
          ['all', '全部'],
          ['active', '处理中'],
          ['succeeded', '已完成'],
          ['failed', '失败'],
          ['cancelled', '已取消'],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={filter === value}
            className={filter === value ? 'active' : ''}
            onClick={() => setFilter(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {error && (
        <div className="alert alert-error records-alert" role="alert">
          <TriangleAlert size={17} />
          <span>{error}</span>
        </div>
      )}
      {loading ? (
        <div className="records-state" role="status">
          <LoaderCircle className="spin" size={24} />
          <strong>正在读取运行记录</strong>
          <span>正在汇总标准任务和对话式工作流。</span>
        </div>
      ) : (
        <>
          {filteredBatches.length > 0 && (
            <section className="workflow-records workflow-batch-records">
              <div className="section-heading">
                <div><span className="eyebrow">多日期串行执行</span><h2>核销批次</h2></div>
                <span className="section-count">{filteredBatches.length} 个批次</span>
              </div>
              <div className="workflow-record-grid">
                {filteredBatches.map((batch) => (
                  <Link className="workflow-record-card" to={`/workflow-batches/${batch.id}`} key={batch.id}>
                    <div className="run-glyph"><Layers3 size={18} /></div>
                    <div>
                      <strong>{batch.skill_name} · {batch.reconciliation_dates.length} 天</strong>
                      <small className="record-id" title={batch.id}>批次 ID · {batch.id}</small>
                      <span>{batch.progress_message}</span>
                      <small>{batch.reconciliation_dates.join('、')} · {batch.model_name}</small>
                    </div>
                    <StatusBadge state={batch.state} />
                    <ArrowRight size={16} />
                  </Link>
                ))}
              </div>
            </section>
          )}
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
                      <small className="record-id" title={workflow.id}>任务 ID · {workflow.id}</small>
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
          {filtered.length > 0 && (
            <section className="standard-run-records">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">脚本 · RPA · API</span>
                  <h2>标准任务</h2>
                </div>
                <span className="section-count">{filtered.length} 条</span>
              </div>
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
                        <td><strong>{run.skill_name}</strong><small className="record-id" title={run.id}>任务 ID · {run.id}</small></td>
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
              </div>
            </section>
          )}
          {!filtered.length && !filteredWorkflows.length && !filteredBatches.length && (
            <div className="empty-state records-empty-state">
              {filter === 'all' ? <ListChecks size={30} /> : <ListFilter size={30} />}
              <h3>{filter === 'all' ? '还没有运行记录' : '当前筛选下没有记录'}</h3>
              <p>
                {filter === 'all'
                  ? '从财务工具发起任务后，进度、结果和审计信息会显示在这里。'
                  : '可以切换到“全部”，查看其他状态的任务。'}
              </p>
              <div className="empty-state-actions">
                {filter === 'all' ? (
                  <Link className="button button-primary" to="/skills">
                    前往财务工具 <ArrowRight size={16} />
                  </Link>
                ) : (
                  <button className="button button-secondary" type="button" onClick={() => setFilter('all')}>
                    查看全部记录
                  </button>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
