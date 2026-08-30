import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { extname } from 'node:path';
import test from 'node:test';

const sourceRoot = new URL('../src/', import.meta.url);

function sourceFiles(directory: URL): URL[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const child = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, directory);
    if (entry.isDirectory()) return sourceFiles(child);
    return ['.ts', '.tsx'].includes(extname(entry.name)) ? [child] : [];
  });
}

test('界面不显示只解释布局或控件位置的文案', () => {
  const bannedPatterns = [
    /框内显示.{0,20}滚动/,
    /在框内滚动/,
    /点击.{0,30}在下方/,
    /在上方填写/,
    /当前只显示.{0,30}这里会显示/,
    /每个 Skill 在同一行显示/,
    /查看版本来源、校验结果和当前发布状态/,
    /集中查看平台功能状态/
  ];

  const violations = sourceFiles(sourceRoot).flatMap((file) => {
    const source = readFileSync(file, 'utf8');
    return bannedPatterns
      .filter((pattern) => pattern.test(source))
      .map((pattern) => `${file.pathname}: ${pattern.source}`);
  });

  assert.deepEqual(violations, []);
});
