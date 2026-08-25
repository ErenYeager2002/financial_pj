import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const history = readFileSync(
  new URL(
    '../src/features/workflow-agent/components/workflow-material-history.tsx',
    import.meta.url
  ),
  'utf8'
);
const panel = readFileSync(
  new URL('../src/features/workflow-agent/components/workflow-agent-panel.tsx', import.meta.url),
  'utf8'
);
const fileList = readFileSync(
  new URL('../src/features/files/components/file-list.tsx', import.meta.url),
  'utf8'
);
const service = readFileSync(
  new URL('../src/features/workflow-agent/api/service.ts', import.meta.url),
  'utf8'
);

test('任务材料区显示当前版本与可恢复的历史版本', () => {
  assert.match(panel, /当前使用创建时固定的业务版本|本任务固定使用创建时的业务版本/);
  assert.match(panel, /WorkflowMaterialHistory/);
  assert.match(history, /当前版本/);
  assert.match(history, /历史版本/);
  assert.match(history, /恢复为新版本/);
});

test('版本历史展示来源任务、年度、发布时间和完整哈希', () => {
  assert.match(history, /来源任务/);
  assert.match(history, /发布于/);
  assert.match(history, /year/);
  assert.match(history, /SHA-256 \{file\.sha256\}/);
});

test('文件中心按 Skill 只展示当前业务材料且不提供恢复操作', () => {
  assert.match(fileList, /WorkflowMaterialHistory skillId=\{key\}/);
  assert.doesNotMatch(fileList, /WorkflowMaterialHistory skillId=\{key\} allowRestore/);
  assert.match(
    history,
    /versions\.filter\(\(version\) => version\.state === 'current'\)\.slice\(0, 1\)/
  );
  assert.match(history, /查看当前业务材料/);
});

test('材料版本使用共享数据层并在展开后才加载', () => {
  assert.doesNotMatch(history, /\bfetch\(/);
  assert.match(history, /enabled: expanded/);
  assert.match(history, /onToggle=/);
  assert.match(service, /platformClientRequest/);
});
