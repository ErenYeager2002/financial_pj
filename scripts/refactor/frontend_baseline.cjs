// Runs only synthetic/static checks in a disposable container with network disabled.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {runGroup} = require('./process_control.cjs');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '../..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'financial-refactor-web-'));
const digest = p => fs.existsSync(p) ? crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex') : null;
const results = [];
async function main() {
try {
  fs.cpSync(path.join(root, 'web'), path.join(tmp, 'web'), {recursive: true, filter: src => {
    const rel = path.relative(path.join(root, 'web'), src);
    return !rel.split(path.sep).some(part => ['node_modules','.next','.git'].includes(part) || part.startsWith('.env'));
  }});
  fs.cpSync(path.join(root, 'contracts'), path.join(tmp, 'contracts'), {recursive: true});
  fs.symlinkSync('/app/web/node_modules', path.join(tmp, 'web/node_modules'));
  for (const script of ['format:check','typecheck','lint','test:navigation','test:run-access','test:platform-data','test:agent-wire','test:hydration','contracts:check','build']) {
    const started = Date.now();
    const result = await runGroup('npm', ['run', script], {cwd:path.join(tmp,'web'), env:{...process.env, HOME:tmp, NEXT_TELEMETRY_DISABLED:'1'}, encoding:'utf8', timeout:240000, maxBuffer:8*1024*1024});
    results.push({script, exit_code:result.status, signal:result.signal, error:result.error?.code, seconds:(Date.now()-started)/1000, output:(result.stdout||'')+(result.stderr||'')});
  }
  console.log(JSON.stringify({schema_version:'frontend-baseline-v1', dependency_mode:'preinstalled-builder; not clean install proof', source_lock_sha256:digest(path.join(root,'web/pnpm-lock.yaml')), builder_lock_sha256:digest('/app/web/pnpm-lock.yaml'), results}));
  process.exitCode = results.every(r=>r.exit_code===0) ? 0 : 1;
} finally {
  if(path.dirname(tmp)!==os.tmpdir() || !path.basename(tmp).startsWith('financial-refactor-web-')) throw Error('cleanup boundary');
  fs.rmSync(tmp, {recursive:true, force:true});
}

}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
