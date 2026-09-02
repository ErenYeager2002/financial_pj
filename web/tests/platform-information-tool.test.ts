import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createPlatformInformationTool,
  platformInformationPath
} from '../src/features/ai-chat/platform-information-tool.ts';

test('finance user can read the complete owner-scoped platform areas through one read-only tool', async () => {
  const requested: string[] = [];
  const tool = createPlatformInformationTool('finance_user', async (path) => {
    requested.push(path);
    return { items: [{ id: 'visible-item' }] };
  });

  const result = await tool.execute('call-1', {
    resource: 'task_center',
    page: 2
  });

  assert.deepEqual(requested, ['/api/task-center?page=2&page_size=20']);
  assert.equal(result.content[0]?.type, 'text');
  assert.match(result.content[0]?.type === 'text' ? result.content[0].text : '', /visible-item/);
  assert.equal(
    platformInformationPath('finance_user', { resource: 'skills' }),
    '/api/catalog/skills'
  );
});

test('platform information detail queries require an explicit owner-scoped record id', () => {
  assert.equal(
    platformInformationPath('finance_user', {
      resource: 'workflow_detail',
      id: 'workflow-id'
    }),
    '/api/workflows/workflow-id'
  );
  assert.throws(
    () => platformInformationPath('finance_user', { resource: 'run_detail' }),
    /记录标识/
  );
});

test('assistant can read the supporting information shown on task and workflow detail pages', () => {
  assert.equal(
    platformInformationPath('finance_user', { resource: 'run_steps', id: 'run-id' }),
    '/api/runs/run-id/steps'
  );
  assert.equal(
    platformInformationPath('finance_user', { resource: 'run_approvals', id: 'run-id' }),
    '/api/runs/run-id/approvals'
  );
  assert.equal(
    platformInformationPath('finance_user', { resource: 'run_events', id: 'run-id', page: 3 }),
    '/api/runs/run-id/event-history?offset=100&limit=50'
  );
  assert.equal(
    platformInformationPath('finance_user', { resource: 'workflows', page: 3 }),
    '/api/workflows?offset=100&limit=50'
  );
  assert.equal(
    platformInformationPath('finance_user', { resource: 'workflow_batches', page: 2 }),
    '/api/workflow-batches?offset=50&limit=50'
  );
  assert.equal(
    platformInformationPath('finance_user', {
      resource: 'workflow_fetched_data',
      id: 'workflow-id',
      page: 2,
      query: 'AR-100'
    }),
    '/api/workflows/workflow-id/fetched-data?dataset=ar_groups&offset=50&limit=50&query=AR-100'
  );
  assert.equal(
    platformInformationPath('finance_user', {
      resource: 'workflow_batch_fetched_data',
      id: 'batch-id',
      date: '2026-09-01',
      issues_only: true
    }),
    '/api/workflow-batches/batch-id/fetched-data?dataset=ar_groups&offset=0&limit=50&issues_only=true&reconciliation_date=2026-09-01'
  );
  assert.throws(
    () =>
      platformInformationPath('finance_user', {
        resource: 'workflow_batch_fetched_data',
        id: 'batch-id'
      }),
    /核销日期/
  );
});

test('finance user cannot use the assistant to read administrator information', async () => {
  let called = false;
  const tool = createPlatformInformationTool('finance_user', async () => {
    called = true;
    return {};
  });

  await assert.rejects(() => tool.execute('call-2', { resource: 'users' }), /只有平台管理员/);
  assert.equal(called, false);
});

test('administrator can read management information without exposing credential endpoints', () => {
  assert.equal(platformInformationPath('skill_admin', { resource: 'users' }), '/api/admin/users');
  assert.equal(
    platformInformationPath('skill_admin', { resource: 'audit_events', cursor: 'audit:150' }),
    '/api/admin/audit-events?limit=50&before_id=150'
  );
  assert.equal(
    platformInformationPath('skill_admin', { resource: 'model_providers' }),
    '/api/model-providers'
  );
  assert.throws(
    () =>
      platformInformationPath('skill_admin', {
        resource: 'service_credentials' as never
      }),
    /不支持的平台信息类型/
  );
});

test('tool responses remove credentials, local paths, technical hashes and file identifiers before model use', async () => {
  const tool = createPlatformInformationTool('finance_user', async () => ({
    counts: { active: 2 },
    recent_files: [
      {
        id: 'private-file-id',
        name: '八月回款.xlsx',
        kind: 'input',
        size_bytes: 1024,
        sha256: 'private-file-hash',
        download_url: '/api/files/private-file-id/download'
      }
    ],
    nested: {
      amount: 1250,
      business_summary: '收入/成本 客户/项目',
      password: 'private-password',
      api_key_hint: 'sk-private',
      source_path: 'D:\\private\\skill',
      file_id: 'nested-private-file-id',
      message:
        'password=plain-password Authorization: Bearer header-token token: plain-token {"api_key":"quoted-token"} /app/private/report.json'
    },
    files: {
      result_file: 'artifact-private-file-id',
      input_file: {
        file_id: 'input-private-file-id',
        name: '银行流水.xlsx',
        sha256: 'input-private-hash',
        kind: 'input'
      }
    },
    artifacts: [
      {
        file_id: 'artifact-private-file-id',
        name: '核销结果.xlsx',
        kind: 'output'
      }
    ]
  }));
  const result = await tool.execute('call-sensitive', { resource: 'overview' });
  const text = result.content[0]?.type === 'text' ? result.content[0].text : '';

  assert.match(text, /"alias": "F1"/);
  assert.match(text, /"result_file": "F2"/);
  assert.match(text, /"alias": "F2"/);
  assert.match(text, /"input_file": \{\s+"alias": "F3",\s+"kind": "input"/);
  assert.doesNotMatch(text, /"F4"/);
  assert.match(text, /1250/);
  assert.match(text, /收入\/成本 客户\/项目/);
  assert.doesNotMatch(
    text,
    /八月回款\.xlsx|核销结果\.xlsx|银行流水\.xlsx|private-file-id|artifact-private-file-id|input-private-file-id|private-file-hash|input-private-hash|private-password|plain-password|header-token|plain-token|quoted-token|sk-private|D:\\\\private|\/app\/private/
  );
});

test('audit information returns an opaque stable cursor without exposing event ids', async () => {
  const tool = createPlatformInformationTool('skill_admin', async () => [
    { id: 10, action: 'file.read' },
    { id: 9, action: 'task.read' }
  ]);

  const result = await tool.execute('call-audit', { resource: 'audit_events' });
  const text = result.content[0]?.type === 'text' ? result.content[0].text : '';

  assert.match(text, /"next_cursor": "audit:9"/);
  assert.doesNotMatch(text, /"id":/);
});

test('administrator user data sent to the model excludes platform and Clerk identifiers', async () => {
  const tool = createPlatformInformationTool('skill_admin', async () => [
    {
      id: 'platform-user-id',
      username: 'finance.user',
      display_name: '财务用户',
      role: 'finance_user',
      status: 'active',
      department_id: 'finance',
      clerk_user_id: 'clerk-user-id',
      clerk_organization_id: 'clerk-org-id'
    }
  ]);
  const result = await tool.execute('call-admin-users', { resource: 'users' });
  const text = result.content[0]?.type === 'text' ? result.content[0].text : '';

  assert.match(text, /finance\.user/);
  assert.doesNotMatch(text, /platform-user-id|clerk-user-id|clerk-org-id|department_id/);
});
