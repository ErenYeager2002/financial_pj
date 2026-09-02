import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AssistantResponse } from '../src/features/ai-chat/assistant-response.ts';

test('AI reply renders readable Markdown hierarchy without executing raw HTML', () => {
  const html = renderToStaticMarkup(
    createElement(AssistantResponse, {
      content: `## 本月核销情况

#### 待处理明细

目前有 **2 个待处理事项**。

- 核对到账记录
- 检查异常金额

> 金额以平台记录为准。

| 状态 | 数量 |
| --- | ---: |
| 待处理 | 2 |

\`AR-1001\`

![外部图](https://tracking.example/private.png)

<script>alert('unsafe')</script>`
    })
  );

  assert.match(html, /<h3[^>]*>本月核销情况<\/h3>/);
  assert.match(html, /<h5[^>]*>待处理明细<\/h5>/);
  assert.match(html, /<strong[^>]*>2 个待处理事项<\/strong>/);
  assert.match(html, /<ul[^>]*>\s*<li[^>]*>[\s\S]*核对到账记录/);
  assert.match(html, /<blockquote[^>]*>[\s\S]*金额以平台记录为准/);
  assert.match(html, /<table[^>]*>[\s\S]*<th[^>]*>状态<\/th>[\s\S]*<td[^>]*>待处理<\/td>/);
  assert.match(html, /<code[^>]*>AR-1001<\/code>/);
  assert.match(html, /图片：外部图/);
  assert.doesNotMatch(html, /<script|<img|<link|unsafe|tracking\.example/);
});

test('plain AI reply stays a compact paragraph', () => {
  const html = renderToStaticMarkup(
    createElement(AssistantResponse, { content: '任务正在处理中，请稍后查看。' })
  );

  assert.match(html, /^<p[^>]*>任务正在处理中，请稍后查看。<\/p>$/);
});
