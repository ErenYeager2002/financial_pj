import type {projectPiSessionStatus} from './pi-view-model';
export type PiSessionCapabilities={protocol:'pi-session-capabilities-v1';session_id:string;can_send:boolean;can_configure:boolean;can_start:boolean;can_upload:boolean;can_approve_input:boolean;rpc_commands:string[];reason:string};
export function checkedPiCapabilities(value:unknown,sessionId:string):PiSessionCapabilities{
 if(!value||typeof value!=='object')throw new Error('无法确认当前会话权限。');
 const item=value as Record<string,unknown>;
 if(item.protocol!=='pi-session-capabilities-v1'||item.session_id!==sessionId||['can_send','can_configure','can_start','can_upload','can_approve_input'].some(key=>typeof item[key]!=='boolean')||!Array.isArray(item.rpc_commands)||item.rpc_commands.some(command=>typeof command!=='string')||typeof item.reason!=='string')throw new Error('无法确认当前会话权限。');
 return item as PiSessionCapabilities;
}
export function applyPiCapabilities(status:ReturnType<typeof projectPiSessionStatus>,capabilities:PiSessionCapabilities|null){
 return {...status,
  canSend:status.canSend&&capabilities?.can_send===true,
  canConfigure:status.canConfigure&&capabilities?.can_configure===true,
  canStartEnvironment:status.canManageEnvironment&&capabilities?.can_start===true,
  canUpload:status.connectionState==='live'&&capabilities?.can_upload===true,
  canListCommands:capabilities?.can_configure===true,
  canApproveInput:capabilities?.can_approve_input===true,
  message:status.message||(capabilities?capabilities.reason:'正在确认会话权限…')};
}
export function permitsPiDialogResponse(capabilities:PiSessionCapabilities|null,response:Record<string,unknown>){
 return response.cancelled===true||response.confirmed===false||capabilities?.can_approve_input===true;
}
