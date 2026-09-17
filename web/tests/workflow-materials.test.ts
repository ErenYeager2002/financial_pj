import assert from 'node:assert/strict';
import test from 'node:test';
import {
  reusableMaterialSelection,
  selectedMaterialIds,
  selectedMaterialUpdates
} from '../src/features/workflow-agent/workflow-materials.ts';

test('任务创建入口读取并标记平台已保存的复用文件', () => {
  const materials = reusableMaterialSelection(
    {
      skill_id: 'ar-hexiao-daily',
      ready: true,
      missing_roles: [],
      material_set_id: 'set-v3',
      material_version: 3,
      source_workflow_id: 'workflow-v3',
      published_at: '2026-08-20T00:00:00Z',
      files: {
        profit_loss_ledgers: [
          { file_id: 'ledger-2025', name: '2025年盈亏核算表.xlsx' },
          { file_id: 'ledger-2026', name: '2026年盈亏核算表.xlsx' }
        ],
        receipt_flow_table: [{ file_id: 'flow-current', name: '到账流转表.xlsx' }]
      }
    },
    'ar-hexiao-daily'
  );

  assert.deepEqual(materials.profit_loss_ledgers, [
    { id: 'ledger-2025', name: '2025年盈亏核算表.xlsx', source: 'saved' },
    { id: 'ledger-2026', name: '2026年盈亏核算表.xlsx', source: 'saved' }
  ]);
  assert.deepEqual(materials.receipt_flow_table, [
    { id: 'flow-current', name: '到账流转表.xlsx', source: 'saved' }
  ]);
});

test('从本次任务移除历史文件后只提交仍被选中的文件', () => {
  assert.deepEqual(
    selectedMaterialIds({
      profit_loss_ledgers: [
        { id: 'ledger-2026-new', name: '2026年盈亏核算表_新版.xlsx', source: 'uploaded' }
      ],
      receipt_flow_table: [{ id: 'flow-current', name: '到账流转表.xlsx', source: 'saved' }]
    }),
    {
      profit_loss_ledgers: ['ledger-2026-new'],
      receipt_flow_table: ['flow-current']
    }
  );
});

test('仅复用已保存文件时不提交文件替换', () => {
  assert.deepEqual(
    selectedMaterialUpdates(
      {
        profit_loss_ledgers: [
          { id: 'ledger-2026', name: '2026年盈亏核算表.xlsx', source: 'saved' }
        ],
        receipt_flow_table: [{ id: 'flow-current', name: '到账流转表.xlsx', source: 'saved' }]
      },
      new Set()
    ),
    { files: {}, replace_roles: [] }
  );
});

test('只提交用户在本次任务中改动的文件用途', () => {
  assert.deepEqual(
    selectedMaterialUpdates(
      {
        profit_loss_ledgers: [
          { id: 'ledger-2026', name: '2026年盈亏核算表.xlsx', source: 'saved' }
        ],
        receipt_flow_table: [{ id: 'flow-new', name: '到账流转表_新版.xlsx', source: 'uploaded' }]
      },
      new Set(['receipt_flow_table'])
    ),
    {
      files: { receipt_flow_table: ['flow-new'] },
      replace_roles: ['receipt_flow_table']
    }
  );
});

// Candidate choices must never leak into the immutable task binding payload.
import { materialYear, toggleMaterialSelection, validateMaterialSelection } from '../src/features/workflow-agent/workflow-materials.ts';

test('annual selection replaces only the same year and preserves other years', () => {
  const entries = [
    { id: 'old', name: '2026年盈亏.xlsx', source: 'saved' as const },
    { id: 'new', name: '2026年盈亏新版.xlsx', source: 'uploaded' as const, selected: false },
    { id: 'prior', name: '2025年盈亏.xlsx', source: 'saved' as const }
  ];
  const result = toggleMaterialSelection('profit_loss_ledgers', entries, 'new');
  assert.deepEqual(selectedMaterialIds({ profit_loss_ledgers: result }), { profit_loss_ledgers: ['new', 'prior'] });
  assert.deepEqual(selectedMaterialIds({ profit_loss_ledgers: toggleMaterialSelection('profit_loss_ledgers', result, 'new') }), { profit_loss_ledgers: ['prior'] });
});

test('flow candidates are mutually exclusive and unselected uploads are excluded', () => {
  const entries = [
    { id: 'a', name: '到账.xlsx', source: 'saved' as const },
    { id: 'b', name: '到账新.xlsx', source: 'uploaded' as const, selected: false }
  ];
  assert.deepEqual(selectedMaterialIds({ receipt_flow_table: toggleMaterialSelection('receipt_flow_table', entries, 'b') }), { receipt_flow_table: ['b'] });
  assert.deepEqual(selectedMaterialUpdates({ receipt_flow_table: entries }, new Set(['receipt_flow_table'])).files, { receipt_flow_table: ['a'] });
});

test('year recognition rejects missing or conflicting years and trusts bound metadata', () => {
  assert.equal(materialYear({ name: '25年盈亏.xlsx' }), undefined);
  assert.equal(materialYear({ name: '2025-2026年盈亏.xlsx' }), undefined);
  assert.equal(materialYear({ name: '盈亏.xlsx', year: 2025 }), 2025);
  assert.equal(materialYear({ name: '2026年盈亏2026备份.xlsx' }), 2026);
});

test('a task requires selected ledgers and exactly one flow', () => {
  const ledger = { id: 'a', name: '2026年盈亏.xlsx', source: 'saved' as const };
  const flow = { id: 'b', name: '到账.xlsx', source: 'saved' as const };
  assert.equal(validateMaterialSelection({ profit_loss_ledgers: [ledger], receipt_flow_table: [flow] }), '');
  assert.match(validateMaterialSelection({ profit_loss_ledgers: [ledger, { ...ledger, id: 'c' }], receipt_flow_table: [flow] }), /同一年/);
  assert.match(validateMaterialSelection({ profit_loss_ledgers: [ledger], receipt_flow_table: [{ ...flow, selected: false }] }), /到账流转表/);
});
