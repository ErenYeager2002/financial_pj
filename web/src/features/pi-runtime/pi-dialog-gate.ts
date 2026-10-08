export type PiDialog = {id:string;method:'confirm'|'select'|'input'|'editor';title?:string;message?:string;options?:string[];placeholder?:string;prefill?:string;expires_at?:number};

/** Client-side availability only; the bridge revalidates pending IDs and responses. */
export function validatePiDialogReply(available:boolean, requests:PiDialog[], response:Record<string,unknown>, now=Date.now()) {
 if(!available)throw new Error('正在同步会话，请等待连接恢复后再回复。');
 const request=requests.find(item=>item.id===response.id);
 if(!request)throw new Error('此请求已结束，请等待最新会话状态。');
 if(request.expires_at!==undefined&&(!Number.isFinite(request.expires_at)||request.expires_at<=now))throw new Error('此请求已过期，请等待工具后续结果。');
 if(response.type!=='extension_ui_response'||Object.keys(response).some(key=>!['type','id','cancelled','confirmed','value'].includes(key)))throw new Error('无效的工具回复。');
 if(response.cancelled===true)return {type:'extension_ui_response',id:request.id,cancelled:true};
 if(request.method==='confirm'){
  if(typeof response.confirmed!=='boolean')throw new Error('请选择确认或拒绝。');
  return {type:'extension_ui_response',id:request.id,confirmed:response.confirmed};
 }
 if(typeof response.value!=='string'||(request.method==='select'&&!request.options?.includes(response.value)))throw new Error('请填写有效的工具回复。');
 return {type:'extension_ui_response',id:request.id,value:response.value};
}
