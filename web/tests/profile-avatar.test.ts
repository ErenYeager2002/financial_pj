import assert from 'node:assert/strict';
import test from 'node:test';

import { platformAvatarUrl } from '../src/features/profile/avatar.ts';

const session = {
  user_id: 'avatar-user',
  username: 'avatar-user',
  display_name: '头像用户',
  role: 'finance_user',
  department_id: 'finance',
  must_change_password: false,
  auth_provider: 'session',
  avatar_updated_at: null
} as const;

test('uses initials until an avatar has been uploaded', () => {
  assert.equal(platformAvatarUrl(session), undefined);
});

test('cache-busts the private avatar URL after upload', () => {
  assert.equal(
    platformAvatarUrl({ ...session, avatar_updated_at: '2026-08-25T03:00:00+00:00' }),
    '/api/platform/profile/avatar?v=2026-08-25T03%3A00%3A00%2B00%3A00'
  );
});
