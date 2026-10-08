import test from 'node:test';
import assert from 'node:assert/strict';
import {PiControlRequests,interruptPiReply,queueMessages,takePiQueuedMessages} from '../src/features/pi-runtime/pi-control-requests.ts';
test('HTTP acceptance does not complete a control operation; exact RPC ack does',async()=>{
 const controls=new PiControlRequests(1000);let done=false;
 const result=controls.request('one','abort',async()=>({accepted:true})).then(()=>{done=true});
 await Promise.resolve();await Promise.resolve();assert.equal(done,false);
 assert.equal(controls.receive({type:'response',id:'other',command:'abort',success:true}),false);
 assert.equal(controls.receive({type:'response',id:'one',command:'clear_queue',success:true}),false);
 assert.equal(done,false);controls.receive({type:'response',id:'one',command:'abort',success:true});await result;
});
test('lost ack times out without retransmission',async()=>{const controls=new PiControlRequests(5);let count=0;await assert.rejects(controls.request('one','abort',async()=>{count++}),/不会自动重发/);assert.equal(count,1)});
test('RPC rejection is not success',async()=>{const controls=new PiControlRequests();const result=controls.request('one','abort',async()=>{});const check=assert.rejects(result,/denied/);controls.receive({type:'response',id:'one',command:'abort',success:false,error:'denied'});await check});
test('disconnect rejects pending operation and late acknowledgement cannot continue it',async()=>{const controls=new PiControlRequests();const result=controls.request('one','clear_queue',async()=>{});const check=assert.rejects(result,/观察已变化/);controls.reset();await check;assert.equal(controls.receive({type:'response',id:'one',command:'clear_queue',success:true}),false)});
test('clear is acknowledged and draft restored before abort is sent',async()=>{const events:string[]=[];await interruptPiReply(true,async type=>{events.push(type);return {steering:['adjust'],followUp:['continue']}},messages=>events.push(...messages));assert.deepEqual(events,['clear_queue','adjust','continue','abort'])});
test('abort-only preserves queue and does not restore or clear anything',async()=>{const events:string[]=[];await interruptPiReply(false,async type=>{events.push(type)},()=>assert.fail());assert.deepEqual(events,['abort'])});
test('unknown clear result never dispatches a dependent abort',async()=>{const events:string[]=[];await assert.rejects(interruptPiReply(true,async type=>{events.push(type);throw new Error('unknown')},()=>assert.fail()),/unknown/);assert.deepEqual(events,['clear_queue'])});
test('malformed clear acknowledgement cannot silently discard drafts or proceed',async()=>{await assert.rejects(interruptPiReply(true,async()=>({steering:['valid'],followUp:[1]}),()=>assert.fail()),/响应无效/);assert.deepEqual(queueMessages({steering:['a','a'],followUp:['b']}),['a','a','b'])});

test('unmount before dispatch prevents a queued transport call',async()=>{const controls=new PiControlRequests();let sent=0;const response=controls.request('one','abort',async()=>{sent++});const check=assert.rejects(response,/观察已变化/);controls.reset();await check;await Promise.resolve();assert.equal(sent,0)});

test('queue retrieval restores acknowledged text without abort or prompt',async()=>{const events:string[]=[];const count=await takePiQueuedMessages(async type=>{events.push(type);return {steering:['adjust'],followUp:['next']}},messages=>events.push(...messages));assert.deepEqual(events,['clear_queue','adjust','next']);assert.equal(count,2)});
test('unknown queue retrieval never restores guessed text or sends a second operation',async()=>{let calls=0;await assert.rejects(takePiQueuedMessages(async()=>{calls++;throw new Error('lost ack')},()=>assert.fail()),/lost ack/);assert.equal(calls,1)});
