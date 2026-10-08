import type {PiPoll} from './pi-protocol';
/** Starting a process is not the same as the observer switching to its stream. */
export class PiStartObservation {
 private pending:{generation:number;minimum:number;resolve:()=>void;reject:(error:Error)=>void;timer:ReturnType<typeof setTimeout>}|null=null;
 wait(result:unknown,minimumObservation:number,timeoutMs=20000):Promise<void>{
  if(!result||typeof result!=='object')return Promise.reject(new Error('无法确认新环境的运行状态，消息尚未发送。'));
  const value=result as Record<string,unknown>;
  if(value.running!==true||value.mode!=='rpc'||!Number.isSafeInteger(value.generation)||Number(value.generation)<1)return Promise.reject(new Error('无法确认新环境的运行代次，消息尚未发送。'));
  this.cancel();
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{this.pending=null;reject(new Error('新环境已启动，但观察连接尚未就绪；消息尚未发送，请恢复连接后再试。'))},timeoutMs);this.pending={generation:Number(value.generation),minimum:minimumObservation,resolve,reject,timer}});
 }
 observe(sequence:number,poll:PiPoll,stable:boolean){
  const pending=this.pending;
  if(!pending||!stable||sequence<pending.minimum||poll.running!==true||poll.mode!=='rpc'||poll.generation!==pending.generation||!poll.instance_id||!poll.activity)return;
  clearTimeout(pending.timer);this.pending=null;pending.resolve();
 }
 cancel(){const pending=this.pending;if(!pending)return;clearTimeout(pending.timer);this.pending=null;pending.reject(new Error('会话观察已结束，消息尚未发送。'))}
}
