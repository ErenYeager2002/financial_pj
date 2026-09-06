import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  PlatformFileOption,
  PlatformFileOptionPage
} from '../src/features/platform-api/types.ts';
import {
  createSelectableInputFilePageLoader,
  isSelectableInputFileDisabled,
  MAX_SELECTED_FILES,
  selectedFileCountMessage,
  selectedFileLimitMessage,
  toggleSelectedFileIds
} from '../src/features/ai-chat/components/selectable-input-file-picker-state.ts';

function option(id: string, name = id): PlatformFileOption {
  return {
    id,
    name,
    kind: 'input',
    size_bytes: 100,
    skill_id: '',
    skill_name: '',
    skill_version: '',
    business_date: '',
    same_content_count: 1,
    source_task_id: '',
    source_task_type: '',
    created_at: null
  };
}

function page(
  items: PlatformFileOption[],
  pageNumber = 1,
  total = items.length,
  pageSize = 25
): PlatformFileOptionPage {
  return {
    items,
    total,
    page: pageNumber,
    page_size: pageSize,
    pages: total ? Math.ceil(total / pageSize) : 0
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' }
  });
}

test('选择第20个文件成功，并且同一文件不会重复加入', () => {
  const firstNineteen = Array.from({ length: MAX_SELECTED_FILES - 1 }, (_, index) =>
    `file-${index + 1}`
  );

  const selected = toggleSelectedFileIds(firstNineteen, 'file-20', true);

  assert.equal(selected.length, MAX_SELECTED_FILES);
  assert.equal(selected.at(-1), 'file-20');
  assert.deepEqual(toggleSelectedFileIds(selected, 'file-20', true), selected);
});

test('尝试选择第21个文件时状态仍为20个', () => {
  const selected = Array.from({ length: MAX_SELECTED_FILES }, (_, index) => `file-${index + 1}`);

  assert.deepEqual(toggleSelectedFileIds(selected, 'file-21', true), selected);
  assert.equal(selected.length, MAX_SELECTED_FILES);
});

test('达到上限时显示提示，已选文件仍可取消', () => {
  const selected = Array.from({ length: MAX_SELECTED_FILES }, (_, index) => `file-${index + 1}`);

  assert.equal(selectedFileLimitMessage(selected.length), '最多选择 20 个文件。');
  assert.equal(selectedFileCountMessage(20), '已选择 20 / 20 个文件');
  assert.equal(isSelectableInputFileDisabled(selected, 'file-21', false), true);
  assert.equal(isSelectableInputFileDisabled(selected, 'file-20', false), false);
  assert.deepEqual(
    toggleSelectedFileIds(selected, 'file-20', false),
    selected.slice(0, MAX_SELECTED_FILES - 1)
  );
});

test('换页和搜索请求不会清空跨页选择', async () => {
  let selected = toggleSelectedFileIds([], 'file-page-1', true);
  const requests: string[] = [];
  const loader = createSelectableInputFilePageLoader(async (input) => {
    const url = String(input);
    requests.push(url);
    const query = new URL(url, 'http://localhost').searchParams.get('query');
    return jsonResponse(
      query ? page([option('file-search', '搜索结果')], 1, 1) : page([option('file-page-2')], 2, 26)
    );
  });

  const nextPage = await loader.request(2, 25);
  selected = toggleSelectedFileIds(selected, nextPage?.items?.[0]?.id ?? '', true);
  const searchedPage = await loader.request(1, 25, '  报表  ');

  assert.equal(searchedPage?.items?.[0]?.id, 'file-search');
  assert.deepEqual(selected, ['file-page-1', 'file-page-2']);
  assert.match(requests[0], /page=2/);
  assert.match(requests[1], /query=%E6%8A%A5%E8%A1%A8/);
});

test('分页请求失败时保留当前页面和选择', async () => {
  const currentPage = page([option('file-current')]);
  const selected = toggleSelectedFileIds([], 'file-current', true);
  const loader = createSelectableInputFilePageLoader(async () =>
    jsonResponse({ detail: '文件列表服务暂时不可用。' }, 503)
  );

  await assert.rejects(loader.request(2, 25), /文件列表服务暂时不可用/);
  assert.deepEqual(currentPage.items?.map((item) => item.id), ['file-current']);
  assert.deepEqual(selected, ['file-current']);
});

test('快速发起两次查询时，旧请求结果不会覆盖新请求结果', async () => {
  let resolveOld: ((response: Response) => void) | undefined;
  let resolveNew: ((response: Response) => void) | undefined;
  const loader = createSelectableInputFilePageLoader(async (input) => {
    const query = new URL(String(input), 'http://localhost').searchParams.get('query');
    return new Promise<Response>((resolve) => {
      if (query === 'old') {
        resolveOld = resolve;
      } else {
        resolveNew = resolve;
      }
    });
  });

  const oldRequest = loader.request(1, 25, 'old');
  const newRequest = loader.request(1, 25, 'new');
  assert.ok(resolveOld);
  assert.ok(resolveNew);

  const newPage = page([option('new-result')]);
  resolveNew?.(jsonResponse(newPage));
  assert.deepEqual(await newRequest, newPage);

  resolveOld?.(jsonResponse(page([option('old-result')])));
  assert.equal(await oldRequest, null);
});
