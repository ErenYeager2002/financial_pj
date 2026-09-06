import assert from 'node:assert/strict';
import test from 'node:test';

import { runOutputFileDownloadHref } from '../src/features/runs/run-output-files.ts';

test('任务结果下载使用文件下载接口', () => {
  assert.equal(
    runOutputFileDownloadHref('909059fb-13bc-4382-bcaf-1e0686296406'),
    '/api/platform/files/909059fb-13bc-4382-bcaf-1e0686296406/download'
  );
  assert.equal(
    runOutputFileDownloadHref('file/id'),
    '/api/platform/files/file%2Fid/download'
  );
});
