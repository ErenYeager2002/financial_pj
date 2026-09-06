'use client';

import * as React from 'react';
import { Button } from '@/components/ui/button';
import type { OrderEvidenceDetail, OrderEvidencePage } from '../order-evidence';

const FIELD_LABELS: Record<string, string> = {
  record: '首次判定', order: '对应年度盈亏表', parent: '父回款及关联订单',
  sources: '来源文件指纹', final_results: '实际执行与最终复核',
  record_id: '判定记录编号', case_id: '业务记录编号', order_key: '年度及订单索引',
  ar: '父回款单号', so: '销售订单', sod: '销售明细', code: '原因码', reason: '判断原因',
  initial_bucket: '首次分类', warning_codes: '警告原因码', available: '是否有对应材料',
  source: '来源文件', sheet: '工作表', ledger_year: '交付年度', rows: '业务行', row: '行号',
  ledger_row_ref: '初始目标行', sha256: '文件指纹', delivery_date: '交付日期',
  delivery_date_issue: '交付日期问题', match_basis: '匹配依据', five_cols: '计划写入值',
  current_values: '当前业务值', idempotence_audit: '重复写入检查',
  write_currency_audit: '本次回款及币种依据', split_payment_source: '本次金额与交付额',
  sod_capacity_audit: 'SOD 历史回款及可承接金额', source_events: '原始核销事件',
  row_operation: '拆分与合并计划', same_so_multi_sod_absorbed: '合并记录依据',
  tail_tolerance_absorbed: '尾差吸收依据', related_orders: '关联订单', record_ids: '关联判定记录',
  status: '状态', comparison_basis: '核对口径', parent_total_orig: '父回款原币总额',
  parent_total_local: '父回款本币总额', parent_net_orig: '父回款原币净额',
  parent_net_local: '父回款本币净额', parent_charge_orig: '原币手续费',
  parent_charge_local: '本币手续费', order_amount_total: '订单金额合计', delta: '金额差额',
  delta_dedup: '去重后差额', threshold: '允许差额', error_code: '错误码',
  fallback_used: '是否使用父回款分配', is_whole_payment: '是否整笔回款',
  unallocated_parent_amount: '父回款未分配余额', amounts: '金额明细',
  execution_status: '实际执行状态', final_status: '最终状态', final_code: '最终原因码',
  final_reason: '最终原因', change_reason: '状态变化依据', reason_detail: '判断事实与规则',
  execution_evidence: '实际执行凭据', execution_rows: '实际目标行',
  execution_reason: '首次校验及执行依据', execution_check: '首次校验事实',
  source_lineage: '展开前来源', source_id: '来源事件指纹', lineage: '首次与写后对应关系',
  final_outcomes: '写后逐项结果', outcomes: '逐项判断依据', bucket: '分类',
  initial_case_id: '首次案例ID', final_case_ids: '写后对应案例ID',
  shared_initial_case_ids: '共用此复核结果的首次案例', mapping_changed: '记录对应是否变化',
  hold_rescan: '挂账复查', scope: '记录范围', initial_record_ids: '首次证据记录',
  before_status: '重扫前状态', after_status: '重扫后状态', before_code: '原原因码',
  after_code: '重扫后原因码', before_reason: '重扫前原因', after_reason: '重扫后原因',
  revisit_condition: '后续处理条件', state_changed: '判断是否变化',
  amount: '原币金额', amount_local: '本币金额', currency: '币种', date: '业务日期',
  snapshot_date: '快照日期', disposition: '处理结论', rowid: '来源记录编号'
};
const STATUS_LABELS: Record<string, string> = {
  auto: '自动判定', hold: '挂账', exception: '异常', completed: '写入并完成复核',
  skipped: '跳过', conflict: '冲突', written_verified: '已写入并回读', not_executed: '未执行写入',
  current_task: '本任务', historical: '历史挂账'
};
const STATUS_FIELDS = new Set(['initial_bucket', 'execution_status', 'final_status', 'bucket', 'status', 'scope']);

export function WorkflowOrderEvidenceDetail({ workflowId, recordId }: { workflowId: string; recordId: string }) {
  const [request, setRequest] = React.useState({ offset: 0, fingerprint: '', previous: [] as number[] });
  const [detail, setDetail] = React.useState<OrderEvidenceDetail | null>(null);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(true);
  const [revision, setRevision] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setError(''); setDetail(null);
    const search = new URLSearchParams({ record_id: recordId, detail_offset: String(request.offset) });
    if (request.fingerprint) search.set('fingerprint', request.fingerprint);
    void fetch(`/api/platform/workflows/${encodeURIComponent(workflowId)}/order-evidence?${search}`, {
      signal: controller.signal, cache: 'no-store'
    }).then(async (response) => {
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || payload.message || '订单明细读取失败。');
      const result = payload as OrderEvidencePage;
      if (!result.available || !result.detail) throw new Error(result.message || '当前没有可读取的订单明细。');
      if (!controller.signal.aborted) setDetail(result.detail);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '订单明细读取失败。');
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [workflowId, recordId, request, revision]);

  return <div className='mt-3 space-y-3 text-sm'>
    {busy && <p role='status'>正在读取订单明细…</p>}
    {error && <div role='alert' className='space-y-2'>
      <p className='text-destructive'>{error}</p>
      <Button variant='outline' onClick={() => { setRequest({ offset: 0, fingerprint: '', previous: [] }); setRevision(value => value + 1); }}>重新读取明细</Button>
    </div>}
    {detail && <>
      <p className='text-muted-foreground'>显示第 {detail.offset + 1}–{detail.next_offset} 项，共 {detail.total} 项依据。盈亏行、父回款、来源和最终结果均包含在明细中。</p>
      <dl className='divide-y rounded-md border px-3'>
        {(detail.entries || []).map((entry, index) => {
          const field = entry.path.at(-1) || '';
          const label = entry.path.map(part => /^\d+$/.test(part) ? `第 ${Number(part) + 1} 项` : FIELD_LABELS[part] || part).join(' / ');
          const value = entry.kind === 'null' ? '未提供' : entry.kind === 'boolean' ? entry.text === 'true' ? '是' : '否'
            : entry.kind === 'array' ? '无记录' : entry.kind === 'object' ? '无明细'
              : STATUS_FIELDS.has(field) ? STATUS_LABELS[entry.text] || entry.text : entry.text || '空白';
          return <div key={`${detail.offset + index}`} className='py-2'>
            <dt className='break-words text-xs text-muted-foreground'>{label}</dt>
            <dd className='mt-1 whitespace-pre-wrap break-words'>{value}</dd>
            {entry.char_total > Array.from(entry.text).length && <dd className='text-xs text-muted-foreground'>长文本第 {entry.char_offset + 1}–{entry.char_offset + Array.from(entry.text).length} 字，共 {entry.char_total} 字</dd>}
          </div>;
        })}
      </dl>
      <div className='flex flex-wrap gap-2'>
        <Button variant='outline' disabled={busy || request.previous.length === 0} onClick={() => setRequest({
          offset: request.previous.at(-1) || 0, fingerprint: detail.fingerprint, previous: request.previous.slice(0, -1)
        })}>上一页明细</Button>
        <Button variant='outline' disabled={busy || detail.next_offset >= detail.total} onClick={() => setRequest({
          offset: detail.next_offset, fingerprint: detail.fingerprint, previous: [...request.previous, detail.offset]
        })}>下一页明细</Button>
      </div>
    </>}
  </div>;
}
