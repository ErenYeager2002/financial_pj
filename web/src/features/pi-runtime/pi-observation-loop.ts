/** Schedule browser observation only. It never starts, stops or replays execution. */
export type PiObservationClock = {set(run:()=>void, delay:number):unknown; clear(handle:unknown):void};
const browserClock:PiObservationClock = {
 set:(run,delay)=>setTimeout(run,delay),
 clear:handle=>clearTimeout(handle as ReturnType<typeof setTimeout>)
};
export function piObservationDelay(visible:boolean,running:boolean){return !visible?5000:running?500:1800;}

/** Wake coalesces visibility changes; at most one observation can be in flight. */
export class PiObservationLoop {
 private observe:()=>Promise<void>;
 private delay:()=>number;
 private clock:PiObservationClock;
 private timer:unknown;
 private busy=false;
 private requested=false;
 private disposed=false;
 constructor(observe:()=>Promise<void>,delay:()=>number,clock:PiObservationClock=browserClock){
  this.observe=observe;this.delay=delay;this.clock=clock;
 }
 wake(){
  if(this.disposed)return;
  if(this.timer!==undefined){this.clock.clear(this.timer);this.timer=undefined;}
  if(this.busy){this.requested=true;return;}
  this.busy=true;
  void this.run();
 }
 dispose(){this.disposed=true;this.requested=false;if(this.timer!==undefined){this.clock.clear(this.timer);this.timer=undefined;}}
 private async run(){
  // The caller projects transport errors; scheduling is independent of success.
  try{await this.observe();}catch{}finally{
   this.busy=false;
   if(!this.disposed){if(this.requested){this.requested=false;this.wake();}else this.timer=this.clock.set(()=>{this.timer=undefined;this.wake();},this.delay());}
  }
 }
}
