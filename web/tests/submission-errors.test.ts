import assert from 'node:assert/strict';
import test from 'node:test';
import { platformApiError, platformErrorBody, PlatformApiError } from '../src/features/platform-api/errors.ts';

test('BFF preserves submission status, code and receipt without unrelated fields', () => {
  const id = '12345678-1234-4234-8234-123456789abc';
  const error = platformApiError(409, {detail:{code:'SUBMISSION_IN_PROGRESS',request_id:id,token:'private',trace:'private'}}, 'fallback');
  assert.equal(error.status,409);
  assert.equal(error.detail?.code,'SUBMISSION_IN_PROGRESS');
  assert.equal(error.detail?.request_id,id);
  assert.match(error.message,/正在准备/);
  const body = platformErrorBody(error);
  assert.doesNotMatch(JSON.stringify(body),/private|token|trace/);
  const client = platformApiError(409,body,'fallback');
  assert.deepEqual(client.detail,error.detail);
});

test('invalid receipt, unknown codes and generic errors do not gain metadata', () => {
  const error = platformApiError(409,{detail:{code:'IDEMPOTENCY_CONFLICT',request_id:'https://private.invalid'}},'fallback');
  assert.equal(error.detail?.request_id,undefined);
  assert.match(error.message,/同一提交标识/);
  assert.equal(platformApiError(500,{detail:{code:'PRIVATE',token:'secret'}},'fallback').detail,undefined);
  assert.deepEqual(platformErrorBody(new PlatformApiError(400,'existing message')),{detail:'existing message'});
});
