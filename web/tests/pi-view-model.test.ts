import assert from 'node:assert/strict';
import test from 'node:test';
import {projectPiSessionStatus, type PiSessionFacts} from '../src/features/pi-runtime/pi-view-model.ts';
const idle: PiSessionFacts = {connection:'live', mode:'rpc', running:false, working:false, activityKnown:true, dialogCount:0, sending:false, uploading:false, uncertainDelivery:false};

test('initial unknown state does not masquerade as a stopped environment', () => {
 const state=projectPiSessionStatus({...idle,connection:'connecting',activityKnown:false});
 assert.equal(state.executionState,'unknown');assert.equal(state.canSend,false);assert.equal(state.canManageEnvironment,false);assert.ok(state.message);
});
test('confirmed stopped environment can accept a new user request', () => {
 const state=projectPiSessionStatus(idle);
 assert.equal(state.executionState,'idle');assert.equal(state.canSend,true);assert.equal(state.canConfigure,false);assert.equal(state.message,'');
});
test('a live transport without agent activity is still unknown', () => {
 const state=projectPiSessionStatus({...idle,running:true,activityKnown:false});
 assert.equal(state.executionState,'unknown');assert.equal(state.canSend,false);assert.equal(state.canConfigure,false);
});
test('connection loss overrides a stale idle or running projection', () => {
 for(const working of [true,false]){
  const state=projectPiSessionStatus({...idle,connection:'recovering',running:true,working});
  assert.equal(state.executionState,'unknown');assert.equal(state.canSend,false);assert.equal(state.canInterrupt,false);assert.equal(state.canManageEnvironment,false);
 }
});
test('a busy observed agent can accept follow-up but not model changes', () => {
 const state=projectPiSessionStatus({...idle,running:true,working:true});
 assert.equal(state.executionState,'running');assert.equal(state.canSend,true);assert.equal(state.canConfigure,false);assert.equal(state.canInterrupt,true);
});
test('pending tool input is represented independently of idle agent flags', () => {
 const state=projectPiSessionStatus({...idle,running:true,dialogCount:1});
 assert.equal(state.executionState,'waiting_input');assert.equal(state.canConfigure,false);
});
test('delivery uncertainty cannot become success or allow a second send', () => {
 const state=projectPiSessionStatus({...idle,uncertainDelivery:true});
 assert.equal(state.executionState,'idle');assert.equal(state.canSend,false);
});
test('upload and send remain local admission barriers', () => {
 for(const barrier of [{uploading:true},{sending:true}])assert.equal(projectPiSessionStatus({...idle,...barrier}).canSend,false);
});
test('successful observation restores actions without resubmitting any request', () => {
 const stale={...idle,running:true,connection:'recovering' as const};
 assert.equal(projectPiSessionStatus(stale).canSend,false);
 const state=projectPiSessionStatus({...stale,connection:'live'});
 assert.equal(state.canSend,true);assert.equal(state.canConfigure,true);assert.equal(state.executionState,'idle');
});

test('terminal and unrecognized modes do not expose RPC mutation controls', () => {
 for(const mode of ['terminal','']){
  const state=projectPiSessionStatus({...idle,running:true,working:true,mode});
  assert.equal(state.canSend,false);assert.equal(state.canConfigure,false);assert.equal(state.canInterrupt,false);assert.equal(state.canManageEnvironment,true);assert.ok(state.message);
 }
});

test('a pending extension response is waiting input even while its prompt response is outstanding',()=>{
 const state=projectPiSessionStatus({...idle,running:true,dialogCount:1,sending:true});
 assert.equal(state.activityLabel,'等待你的回复');assert.equal(state.submitLabel,'等待回复');
 assert.equal(state.canSend,false);assert.equal(state.canReplyToDialog,true);
 const lost=projectPiSessionStatus({...idle,running:true,dialogCount:1,sending:true,connection:'recovering'});
 assert.equal(lost.activityLabel,'等待状态恢复');assert.equal(lost.canReplyToDialog,false);
});
