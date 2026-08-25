import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const routeSource = readFileSync(
  new URL('../src/app/api/platform/workflows/[workflowId]/fetched-data/route.ts', import.meta.url),
  'utf8'
);
const batchRouteSource = readFileSync(
  new URL(
    '../src/app/api/platform/workflow-batches/[batchId]/fetched-data/route.ts',
    import.meta.url
  ),
  'utf8'
);

function routeUuidValidator(): RegExp {
  const declaration = routeSource.match(/const UUID = (\/.*\/i);/);
  assert.ok(declaration, '取数数据路由必须声明工作流 UUID 校验器');
  return Function(`return ${declaration[1]}`)() as RegExp;
}

test('取数数据路由接受平台生成的标准工作流 UUID', () => {
  assert.equal(routeUuidValidator().test('8b70c168-dce1-45cf-882c-efd17a292bd6'), true);
});

test('取数数据路由拒绝非 UUID 工作流标识', () => {
  assert.equal(routeUuidValidator().test('not-a-workflow-id'), false);
});

test('单日和批次取数路由转发 AR 分组搜索与异常筛选', () => {
  for (const source of [routeSource, batchRouteSource]) {
    assert.match(source, /'query'/);
    assert.match(source, /'issues_only'/);
  }
});
