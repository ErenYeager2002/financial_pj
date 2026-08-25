import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const calendar = readFileSync(
  new URL('../src/components/ui/calendar.tsx', import.meta.url),
  'utf8'
);

test('calendar day identity is independent of the server and browser locale', () => {
  assert.doesNotMatch(calendar, /data-day=\{[^}]*toLocaleDateString/);
  assert.match(calendar, /data-day=\{format\(day\.date, 'yyyy-MM-dd'\)\}/);
});
