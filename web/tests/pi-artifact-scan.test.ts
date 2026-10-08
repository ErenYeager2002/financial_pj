import assert from 'node:assert/strict';
import test from 'node:test';
import {scanPiArtifacts, type PiDirectoryPage, type PiDirectoryQuery} from '../src/features/pi-runtime/pi-artifact-scan.ts';
const file = (name: string) => ({name,kind:'file' as const,size:12});
const directory = (name: string) => ({name,kind:'directory' as const,size:0});
const page = (entries: PiDirectoryPage['entries'],next_offset: number|null=null): PiDirectoryPage => ({entries,next_offset});

test('collects nested and paginated files while excluding hidden and dependency directories', async () => {
 const calls: PiDirectoryQuery[]=[];
 const result=await scanPiArtifacts(async query=>{
  calls.push(query);
  if(query.path==='results')return page([file('report.xlsx')]);
  if(query.offset===1)return page([file('second.csv')]);
  return page([file('first.csv'),directory('results'),directory('.private'),directory('node_modules'),directory('venv'),directory('__pycache__'),directory('site-packages')],1);
 },new AbortController().signal);
 assert.deepEqual(result.files.map(item=>item.path),['first.csv','results/report.xlsx','second.csv']);
 assert.equal(result.truncated,false);assert.deepEqual(calls,[{path:'',offset:0},{path:'results',offset:0},{path:'',offset:1}]);
});
test('a cancelled scan never starts an old-session request', async () => {
 const c=new AbortController();c.abort();let calls=0;
 await assert.rejects(scanPiArtifacts(async()=>{calls++;return page([])},c.signal),{name:'AbortError'});assert.equal(calls,0);
});
test('cancellation with a late page prevents further directory requests', async () => {
 const c=new AbortController();let calls=0;
 await assert.rejects(scanPiArtifacts(async(_query,signal)=>{assert.equal(signal,c.signal);calls++;c.abort();return page([directory('next')],1)},c.signal),{name:'AbortError'});assert.equal(calls,1);
});
test('request budget bounds repeated pagination and reports truncation', async () => {
 let calls=0;const result=await scanPiArtifacts(async()=>{calls++;return page([],0)},new AbortController().signal,{maxRequests:2});
 assert.equal(calls,2);assert.equal(result.truncated,true);
});
test('file budget also bounds a single oversized page', async () => {
 const result=await scanPiArtifacts(async()=>page([file('a'),file('b'),file('c')]),new AbortController().signal,{maxFiles:2});
 assert.deepEqual(result.files.map(item=>item.path),['a','b']);assert.equal(result.truncated,true);
});
test('an exact complete page is not falsely called truncated', async () => {
 const result=await scanPiArtifacts(async()=>page([file('a'),file('b')]),new AbortController().signal,{maxFiles:2});
 assert.equal(result.files.length,2);assert.equal(result.truncated,false);
});
test('remaining directories at the file limit are reported as truncated', async () => {
 const result=await scanPiArtifacts(async()=>page([file('a'),directory('more')]),new AbortController().signal,{maxFiles:1});
 assert.equal(result.truncated,true);
});
test('a listing failure is not represented as a successful complete inventory', async () => {
 await assert.rejects(scanPiArtifacts(async()=>{throw new Error('read failed')},new AbortController().signal),/read failed/);
});
test('invalid limits are rejected before reading', async () => {
 for(const maxFiles of [0,-1,1.2])await assert.rejects(scanPiArtifacts(async()=>page([]),new AbortController().signal,{maxFiles}),/Invalid artifact scan limits/);
});
