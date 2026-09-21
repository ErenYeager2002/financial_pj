import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {submissionKey,completeSubmission,submissionFingerprint} from '../src/features/run-setup/submission-intent.ts';

function storage() {
  const values=new Map<string,string>();
  return {values,getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);},removeItem:(key:string)=>{values.delete(key);}};
}
let counter=0;
function key(){return '12345678-1234-4234-8234-'+String(++counter).padStart(12,'0');}

test('network retries and page reconstruction reuse the saved intent',()=>{
  const store=storage();
  const input={parameters:{b:2,a:1},files:{report:'private-file-id'}};
  const first=submissionKey('tool',input,key,store);
  assert.equal(submissionKey('tool',{files:input.files,parameters:{a:1,b:2}},key,store),first);
  const reloaded={getItem:store.getItem,setItem:store.setItem,removeItem:store.removeItem};
  assert.equal(submissionKey('tool',input,key,reloaded),first);
  assert.doesNotMatch([...store.values.values()].join(),/private-file-id|parameters/);
});

test('editing input creates a new intent and stale success cannot erase it',()=>{
  const store=storage();
  const first=submissionKey('tool',{files:['one','two']},key,store);
  const changed=submissionKey('tool',{files:['two','one']},key,store);
  assert.notEqual(first,changed);
  completeSubmission('tool',first,store);
  assert.equal(submissionKey('tool',{files:['two','one']},key,store),changed);
  completeSubmission('tool',changed,store);
  assert.notEqual(submissionKey('tool',{files:['two','one']},key,store),changed);
});

test('fingerprint works without browser secure-context WebCrypto',()=>{
  const descriptor=Object.getOwnPropertyDescriptor(globalThis,'crypto');
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:undefined});
  try {
    for(const text of ['', '中文', ' a ', 'x'.repeat(1024)]) {
      assert.equal(submissionFingerprint({text}),createHash('sha256').update(JSON.stringify({text})).digest('hex'));
    }
  } finally {
    if(descriptor)Object.defineProperty(globalThis,'crypto',descriptor);
    else delete (globalThis as {crypto?:Crypto}).crypto;
  }
});

test('storage failures and malformed saved intents never silently create new requests',()=>{
  const store=storage();
  submissionKey('tool',{},key,store);
  const location=[...store.values.keys()][0];
  store.setItem(location,'broken');
  assert.throws(()=>submissionKey('tool',{},key,store),/核对/);
  assert.throws(()=>submissionKey('tool',{},key,{...store,setItem:()=>{throw new Error('blocked');},getItem:()=>null}),/blocked/);
  assert.doesNotThrow(()=>completeSubmission('tool','old',store));
});
