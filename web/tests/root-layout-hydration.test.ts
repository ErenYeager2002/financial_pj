import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const layout = readFileSync(new URL('../src/app/layout.tsx', import.meta.url), 'utf8');
const themeProvider = readFileSync(
  new URL('../src/components/themes/theme-provider.tsx', import.meta.url),
  'utf8'
);
const packageJson = JSON.parse(
  readFileSync(new URL('../package.json', import.meta.url), 'utf8')
) as { scripts?: Record<string, string> };

test('根布局不在客户端重建时渲染内联脚本', () => {
  assert.doesNotMatch(layout, /from ['"]next\/script['"]/);
  assert.doesNotMatch(layout, /<Script\b/);
  assert.doesNotMatch(layout, /theme-color-init/);
});

test('暗色主题通过挂载后的客户端组件同步浏览器主题色', () => {
  assert.match(layout, /themeColors=\{META_THEME_COLORS\}/);
  assert.match(themeProvider, /useTheme\(\)/);
  assert.match(themeProvider, /meta\[name=["']theme-color["']\]/);
});

test('hydration 回归测试已接入项目测试命令', () => {
  const command = packageJson.scripts?.['test:hydration'] ?? '';
  assert.match(command, /tests\/format\.test\.ts/);
  assert.match(command, /tests\/root-layout-hydration\.test\.ts/);
});
