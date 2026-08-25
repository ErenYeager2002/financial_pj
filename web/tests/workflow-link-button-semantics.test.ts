import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const panel = readFileSync(
  new URL('../src/features/workflow-agent/components/workflow-agent-panel.tsx', import.meta.url),
  'utf8'
);
const batchProgress = readFileSync(
  new URL('../src/features/workflow-agent/components/workflow-batch-progress.tsx', import.meta.url),
  'utf8'
);

function linkButtons(source: string): string[] {
  const matches: string[] = [];
  const linkRender = /render=\{(?:\s*)?<Link/g;
  for (const match of source.matchAll(linkRender)) {
    const renderIndex = match.index;
    const buttonIndex = source.lastIndexOf('<Button', renderIndex);
    if (buttonIndex >= 0) matches.push(source.slice(buttonIndex, renderIndex));
  }
  return matches;
}

test('工作流中的 Link 型 Button 声明非原生按钮语义', () => {
  const matches = [...linkButtons(panel), ...linkButtons(batchProgress)];
  assert.equal(matches.length, 2);
  for (const button of matches) {
    assert.match(button, /nativeButton=\{false\}/);
  }
});
