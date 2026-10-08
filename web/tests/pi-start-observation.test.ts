import test from 'node:test';
import assert from 'node:assert/strict';
import {PiStartObservation} from '../src/features/pi-runtime/pi-start-observation.ts';
const started={running:true,mode:'rpc',generation:2};
const poll={...started,instance_id:'new-instance',activity:{busy:false,phase:'idle'},events:[],next:1};
test('new message waits for a fresh stable observation after start response',async()=>{
 const gate=new PiStartObservation();let dispatched=false;const waiting=gate.wait(started,5).then(()=>{dispatched=true});
 gate.observe(4,poll,true);await Promise.resolve();assert.equal(dispatched,false);
 gate.observe(5,poll,false);await Promise.resolve();assert.equal(dispatched,false);
 gate.observe(6,poll,true);await waiting;assert.equal(dispatched,true);
});
test('old generation, stopped state, wrong mode and absent activity never release send',async()=>{
 const gate=new PiStartObservation();let dispatched=false;const waiting=gate.wait(started,1).then(()=>{dispatched=true});
 for(const bad of [{...poll,generation:1},{...poll,running:false},{...poll,mode:'terminal'},{...poll,instance_id:''},{...poll,activity:null}]){gate.observe(2,bad,true);await Promise.resolve();assert.equal(dispatched,false)}
 gate.observe(3,poll,true);await waiting;
});
test('timeout rejects before message dispatch and a late observation cannot release it',async()=>{
 const gate=new PiStartObservation();let dispatched=false;await assert.rejects(gate.wait(started,1,5).then(()=>{dispatched=true}),/消息尚未发送/);gate.observe(2,poll,true);assert.equal(dispatched,false);
});
test('unmount cancels observation without stopping the backend or sending work',async()=>{
 const gate=new PiStartObservation();const waiting=gate.wait(started,1);gate.cancel();await assert.rejects(waiting,/消息尚未发送/);
});
test('unrecognized start result fails closed without creating a wait',async()=>{
 const gate=new PiStartObservation();for(const result of [{running:true,mode:'rpc'}, {...started,generation:0},{...started,generation:'2'},{...started,mode:'terminal'},null])await assert.rejects(gate.wait(result,1),/消息尚未发送/);
});
