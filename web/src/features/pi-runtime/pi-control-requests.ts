/** Correlate control acknowledgements; HTTP acceptance is not execution completion. */
export type ControlType = 'abort' | 'clear_queue';
type Pending = {type:ControlType; resolve:(data:unknown)=>void; reject:(cause:Error)=>void; timer:ReturnType<typeof setTimeout>};
export class PiControlRequests {
 private pending = new Map<string,Pending>();
 private timeoutMs:number;
 constructor(timeoutMs=30000) {this.timeoutMs=timeoutMs}
 request(id:string,type:ControlType,send:()=>Promise<unknown>):Promise<unknown> {
  if(this.pending.has(id))return Promise.reject(new Error('重复的控制请求编号'));
  return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>this.fail(id,new Error('控制结果尚未确认，请查看会话状态；不会自动重发。')),this.timeoutMs);
   this.pending.set(id,{type,resolve,reject,timer});
   Promise.resolve().then(()=>this.pending.has(id)?send():undefined).catch(()=>this.fail(id,new Error('控制请求的接收状态未知，请查看会话状态；不会自动重发。')));
  });
 }
 receive(event:Record<string,unknown>):boolean {
  if(event.type!=='response'||typeof event.id!=='string')return false;
  const request=this.pending.get(event.id);
  if(!request||event.command!==request.type)return false;
  this.pending.delete(event.id);clearTimeout(request.timer);
  if(event.success===true)request.resolve(event.data);
  else request.reject(new Error(typeof event.error==='string'?event.error:'Pi 未确认控制操作成功。'));
  return true;
 }
 private fail(id:string,error:Error){const request=this.pending.get(id);if(!request)return;this.pending.delete(id);clearTimeout(request.timer);request.reject(error)}
 reset(){for(const id of this.pending.keys())this.fail(id,new Error('会话观察已变化，控制结果待核实；不会自动重发。'))}
}
export function queueMessages(value:unknown):string[]{
 if(!value||typeof value!=='object')throw new Error('排队消息响应无效，请核对会话状态。');
 const data=value as Record<string,unknown>;
 if(!Array.isArray(data.steering)||!Array.isArray(data.followUp)||![...data.steering,...data.followUp].every(item=>typeof item==='string'))throw new Error('排队消息响应无效，请核对会话状态。');
 return [...data.steering,...data.followUp];
}
export async function interruptPiReply(clearQueue:boolean,command:(type:ControlType)=>Promise<unknown>,restore:(messages:string[])=>void):Promise<void>{
 if(clearQueue)await takePiQueuedMessages(command,restore);
 await command('abort');
}

/** Retrieve only queued text. Never abort the running reply or submit a new prompt. */
export async function takePiQueuedMessages(command:(type:ControlType)=>Promise<unknown>,restore:(messages:string[])=>void):Promise<number>{
 const messages=queueMessages(await command('clear_queue'));restore(messages);return messages.length;
}
