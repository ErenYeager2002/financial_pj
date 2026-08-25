import assert from 'node:assert/strict';
import test from 'node:test';

import { isThemeToggleShortcut } from '../src/components/themes/theme-shortcut.ts';

test('ignores a keydown-like event without a string key', () => {
  const incompleteEvent = {
    shiftKey: true,
    metaKey: false,
    ctrlKey: true
  } as unknown as KeyboardEvent;

  assert.equal(isThemeToggleShortcut(incompleteEvent), false);
});

test('matches only Cmd/Ctrl+Shift+D', () => {
  assert.equal(
    isThemeToggleShortcut({ key: 'D', shiftKey: true, metaKey: false, ctrlKey: true }),
    true
  );
  assert.equal(
    isThemeToggleShortcut({ key: 'd', shiftKey: false, metaKey: false, ctrlKey: true }),
    false
  );
  assert.equal(
    isThemeToggleShortcut({ key: 'x', shiftKey: true, metaKey: true, ctrlKey: false }),
    false
  );
});
