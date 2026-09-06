import assert from 'node:assert/strict';
import test from 'node:test';

import type { PlatformFileGroupSummary } from '../src/features/platform-api/types.ts';
import {
  fileCenterPaginationItems,
  fileCenterSearchParams,
  fileGroupKey,
  normalizeFileCenterPageSize,
  pageAfterFileDelete,
  parseFileCenterSearchParams,
  resolveFileCenterState
} from '../src/features/files/file-center-pagination.ts';

function group(
  skillId: string,
  fileCount: number,
  unassigned = false
): PlatformFileGroupSummary {
  return {
    skill_id: skillId,
    skill_name: unassigned ? '未归类文件' : skillId,
    unassigned,
    file_count: fileCount,
    latest_created_at: null
  };
}

test('同一 Skill 使用一个稳定分组键，数量来自聚合摘要', () => {
  const first = group('ar-hexiao-daily', 25);
  const second = group('ar-hexiao-daily', 23);
  assert.equal(fileGroupKey(first), fileGroupKey(second));
  assert.equal(first.file_count, 25);
  assert.equal(second.file_count, 23);
  assert.equal(fileGroupKey(group('', 4, true)), 'unassigned');
});

test('组内分页包含首页、末页和省略号', () => {
  assert.deepEqual(fileCenterPaginationItems(6, 12), [1, 'ellipsis', 5, 6, 7, 'ellipsis', 12]);
  assert.deepEqual(fileCenterPaginationItems(2, 5), [1, 2, 3, 4, 5]);
});

test('筛选、分组、页码和每页数量写入客户端导航 URL', () => {
  const params = fileCenterSearchParams({
    kind: 'input',
    query: '  报表  ',
    group: group('ar-hexiao-daily', 48),
    page: 3,
    pageSize: 50
  });
  assert.equal(params.get('kind'), 'input');
  assert.equal(params.get('query'), '报表');
  assert.equal(params.get('skill_id'), 'ar-hexiao-daily');
  assert.equal(params.get('page'), '3');
  assert.equal(params.get('page_size'), '50');
  assert.equal(normalizeFileCenterPageSize('invalid'), 25);

  const firstPageParams = fileCenterSearchParams({
    group: group('ar-hexiao-daily', 48),
    page: 1,
    pageSize: 25
  });
  assert.equal(firstPageParams.get('page'), '1');
  assert.equal(firstPageParams.get('page_size'), '25');
});

test('删除组内当前页最后一个文件时返回上一页', () => {
  assert.equal(pageAfterFileDelete(4, 1), 3);
  assert.equal(pageAfterFileDelete(1, 1), 1);
  assert.equal(pageAfterFileDelete(4, 2), 4);
});

test('文件中心在分组缺失时选择首个分组并修正页码', () => {
  const state = parseFileCenterSearchParams({
    kind: 'output',
    query: '  结果  ',
    skill_id: 'missing-skill',
    page: '99',
    page_size: '50'
  });
  const resolved = resolveFileCenterState(state, [group('current-skill', 51)]);
  assert.equal(resolved.kind, 'output');
  assert.equal(resolved.query, '结果');
  assert.equal(resolved.pageSize, 50);
  assert.equal(resolved.activeGroup?.skill_id, 'current-skill');
  assert.equal(resolved.page, 1);
  assert.equal(resolved.requestedGroupFound, false);
});
