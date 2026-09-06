import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('AI 助手首屏不请求可选文件，且仍保留单会话恢复', async () => {
  const [page, workspace] = await Promise.all([
    readFile('src/app/dashboard/ai-chat/page.tsx', 'utf8'),
    readFile('src/features/ai-chat/components/assistant-workspace.tsx', 'utf8')
  ]);

  assert.doesNotMatch(page, /listSelectableInputFilesPage/);
  assert.match(workspace, /conversations\/latest/);
  assert.doesNotMatch(workspace, /session list|会话列表/);
});

test('模型选择只在管理员分支显示，并且显式保存后才更新已保存值', async () => {
  const [modelSelector, workspace, page] = await Promise.all([
    readFile('src/features/ai-chat/components/assistant-model-selector.tsx', 'utf8'),
    readFile('src/features/ai-chat/components/assistant-workspace.tsx', 'utf8'),
    readFile('src/app/dashboard/ai-chat/page.tsx', 'utf8')
  ]);

  assert.match(modelSelector, /if \(!isAdmin\)/);
  assert.match(modelSelector, /设为助手默认模型/);
  assert.match(modelSelector, /setSavedModel\(saved\.model\)/);
  assert.match(modelSelector, /catch \(error\)/);
  assert.doesNotMatch(workspace, /助手默认模型/);
  assert.match(page, /isAdmin[\s\S]*\? await Promise\.all/);
});

test('没有上下文时隐藏右栏，草稿或工具状态出现后显示', async () => {
  const [context, shell] = await Promise.all([
    readFile('src/features/ai-chat/components/assistant-context-panel.tsx', 'utf8'),
    readFile('src/features/ai-chat/components/assistant-shell.tsx', 'utf8')
  ]);

  assert.match(
    context,
    /if \(!selectedFileNames\.length && !toolMessage && !pendingMessage && !draft\) return null/
  );
  assert.match(context, /已生成任务草稿/);
  assert.match(shell, /context && 'lg:grid-cols-\[minmax\(0,1fr\)_22rem\]'/);
  assert.match(shell, /grid-cols-1/);
  assert.match(shell, /lg:h-\[calc\(100dvh-13rem\)\]/);
  assert.match(shell, /lg:overflow-hidden/);
});

test('普通回答结束后只保留文件、待确认信息或草稿上下文', async () => {
  const workspace = await readFile(
    'src/features/ai-chat/components/assistant-workspace.tsx',
    'utf8'
  );

  assert.match(workspace, /if \(event\.type === 'done'\) setToolMessage\(''\)/);
  assert.match(workspace, /const hasContext =/);
  assert.match(workspace, /Boolean\(pendingMessage\)/);
  assert.match(workspace, /working && Boolean\(toolMessage\)/);
});

test('未配置管理员模型时顶部不使用连接候选值', async () => {
  const selector = await readFile(
    'src/features/ai-chat/components/assistant-model-selector.tsx',
    'utf8'
  );

  assert.match(selector, /const savedProfileModel = profile\?\.model \?\? ''/);
  assert.doesNotMatch(selector, /const initialSavedModel =/);
  assert.match(selector, /savedModel \|\| '选择模型'/);
  assert.match(selector, /setDraftModel\(nextModel\)/);
});
