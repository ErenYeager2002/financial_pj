const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {runGroup}=require('../process_control.cjs');
test('timeout removes a term-ignoring descendant',async()=>{
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'financial-refactor-process-'));
  try {
    const pidfile=path.join(tmp,'pid');
    const child="process.on('SIGTERM',()=>{});require('node:fs').writeFileSync(process.env.PIDFILE,String(process.pid));setInterval(()=>{},1000)";
    const parent="require('node:child_process').spawn(process.execPath,['-e',process.argv[1]],{stdio:'inherit'});setInterval(()=>{},1000)";
    const result=await runGroup(process.execPath,['-e',parent,child],{env:{...process.env,PIDFILE:pidfile},timeout:1000});
    assert.equal(result.error.code,'TIMEOUT');
    const pid=fs.readFileSync(pidfile,'utf8');
    await new Promise(resolve=>setTimeout(resolve,50));
    const stat='/proc/'+pid+'/stat';
    assert.ok(!fs.existsSync(stat)||fs.readFileSync(stat,'utf8').split(' ')[2]==='Z');
  }finally{fs.rmSync(tmp,{recursive:true,force:true});}
});
test('successful output remains available',async()=>{
  const result=await runGroup(process.execPath,['-e',"console.log('synthetic')"],{timeout:2000});
  assert.equal(result.status,0);assert.equal(result.stdout.trim(),'synthetic');
});
