import assert from 'node:assert/strict';
import test from 'node:test';
import { PiObservationLoop, piObservationDelay, type PiObservationClock } from '../src/features/pi-runtime/pi-observation-loop.ts';

function clock() {
 const pending = new Map<number, {run:()=>void; delay:number}>(); let id=0;
 const adapter:PiObservationClock={set(run,delay){pending.set(++id,{run,delay});return id},clear(handle){pending.delete(handle as number)}};
 return {adapter,pending,fire(){const first=pending.entries().next().value;assert.ok(first);pending.delete(first[0]);first[1].run()}};
}
async function settle(){await Promise.resolve();await Promise.resolve();}

test('background observation slows down and returning wakes exactly one fresh read', async()=>{
 const timers=clock();let visible=true;let calls=0;
 const loop=new PiObservationLoop(async()=>{calls++},()=>piObservationDelay(visible,true),timers.adapter);
 loop.wake();await settle();assert.equal(calls,1);assert.equal([...timers.pending.values()][0].delay,500);
 visible=false;timers.fire();await settle();assert.equal(calls,2);assert.equal([...timers.pending.values()][0].delay,5000);
 visible=true;loop.wake();await settle();assert.equal(calls,3);assert.equal(timers.pending.size,1);
 loop.dispose();assert.equal(timers.pending.size,0);
});


test('wake during a slow read coalesces and never overlaps network observations',async()=>{
 const timers=clock();let calls=0;let finish:()=>void=()=>{};
 const loop=new PiObservationLoop(()=>{calls++;return new Promise<void>(resolve=>{finish=resolve})},()=>500,timers.adapter);
 loop.wake();loop.wake();loop.wake();assert.equal(calls,1);assert.equal(timers.pending.size,0);
 finish();await settle();assert.equal(calls,2);assert.equal(timers.pending.size,0);
 finish();await settle();assert.equal(calls,2);assert.equal(timers.pending.size,1);
 loop.dispose();
});

test('dispose while a read is in flight cannot restart observation or invoke execution controls',async()=>{
 const timers=clock();let calls=0;let finish:()=>void=()=>{};
 const loop=new PiObservationLoop(()=>{calls++;return new Promise<void>(resolve=>{finish=resolve})},()=>500,timers.adapter);
 loop.wake();loop.wake();loop.dispose();finish();await settle();loop.wake();
 assert.equal(calls,1);assert.equal(timers.pending.size,0);
});

test('a failed observation retains bounded retry observation without replaying submitted work',async()=>{
 const timers=clock();let calls=0;
 const loop=new PiObservationLoop(async()=>{calls++;throw new Error('transport unavailable')},()=>5000,timers.adapter);
 loop.wake();await settle();assert.equal(calls,1);assert.equal([...timers.pending.values()][0].delay,5000);
 timers.fire();await settle();assert.equal(calls,2);assert.equal(timers.pending.size,1);loop.dispose();
});

test('foreground stopped environments use slower observation while background remains bounded',()=>{
 assert.equal(piObservationDelay(true,false),1800);
 assert.equal(piObservationDelay(false,false),5000);
});


test('cancelled old observation yields an immediate fresh read when the page resumes',async()=>{
 const timers=clock();let calls=0;const oldObservation=new AbortController();
 const loop=new PiObservationLoop(()=>{
  calls++;if(calls>1)return Promise.resolve();
  return new Promise<void>((_,reject)=>oldObservation.signal.addEventListener('abort',()=>reject(new Error('old read cancelled')),{once:true}));
 },()=>5000,timers.adapter);
 loop.wake();assert.equal(calls,1);oldObservation.abort();loop.wake();
 await settle();await settle();assert.equal(calls,2);assert.equal(timers.pending.size,1);loop.dispose();
});
