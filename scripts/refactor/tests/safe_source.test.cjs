const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {safeSource} = require('../safe_source.cjs');
test('source guard rejects parent symlink and traversal', () => {
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'financial-refactor-path-'));
  try {
    const root=path.join(tmp,'source');const outside=path.join(tmp,'outside');
    fs.mkdirSync(root);fs.mkdirSync(outside);
    fs.writeFileSync(path.join(root,'valid.ts'),'export const value=1');
    fs.writeFileSync(path.join(outside,'private.ts'),'synthetic-only');
    fs.symlinkSync(outside,path.join(root,'link'));
    assert.equal(safeSource(root,'valid.ts'),path.join(root,'valid.ts'));
    assert.throws(()=>safeSource(root,'link/private.ts'),/UNSAFE_SOURCE_PATH/);
    assert.throws(()=>safeSource(root,'../outside/private.ts'),/UNSAFE_SOURCE_PATH/);
  } finally {fs.rmSync(tmp,{recursive:true,force:true});}
});
