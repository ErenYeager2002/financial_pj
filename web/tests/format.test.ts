import assert from 'node:assert/strict';
import test from 'node:test';

import { formatDate } from '../src/lib/format.ts';

test('平台时间在 UTC 服务端和上海浏览器中显示一致', () => {
  const previousTimeZone = process.env.TZ;
  process.env.TZ = 'UTC';
  try {
    assert.equal(
      formatDate('2026-09-02T06:30:00Z', {
        hour: '2-digit',
        minute: '2-digit'
      }),
      '2026年9月2日 14:30'
    );
  } finally {
    if (previousTimeZone === undefined) delete process.env.TZ;
    else process.env.TZ = previousTimeZone;
  }
});
