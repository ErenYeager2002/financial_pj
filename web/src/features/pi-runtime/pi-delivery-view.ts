import type {PiDeliveryReceipt} from './pi-protocol';
export type PiDeliveryView = {id:string;state:PiDeliveryReceipt['delivery_state']|'submitting'|'transport_accepted'};
const confirmed=(state:PiDeliveryView['state'])=>state==='pi_accepted'||state==='rejected';
/** Legacy durable pi_accepted means bridge stdin written, not an observed Pi RPC response. */
export function applyTransportReceipt(current:PiDeliveryView|null,receipt:PiDeliveryReceipt):PiDeliveryView|null{
 if(!current||current.id!==receipt.client_request_id||confirmed(current.state))return current;
 return {id:current.id,state:receipt.delivery_state==='pi_accepted'?'transport_accepted':receipt.delivery_state};
}
export function markDeliveryUncertain(current:PiDeliveryView|null,id:string):PiDeliveryView|null{
 return current?.id===id&&!confirmed(current.state)?{id,state:'unknown'}:current;
}
export function deliveryUnconfirmed(delivery:PiDeliveryView|null){
 return Boolean(delivery&&['submitting','prepared','dispatching','transport_accepted','unknown'].includes(delivery.state));
}
export function deliveryMessage(state:PiDeliveryView['state']){
 if(state==='submitting')return '正在提交消息…';
 if(state==='pi_accepted')return 'Pi 已确认接收消息；执行结果请以对话和任务状态为准。';
 if(state==='rejected')return 'Pi 拒绝了这条消息。';
 if(state==='transport_accepted')return '消息已写入会话通道，Pi 的接收结果尚待确认；请先查看聊天记录，避免重复发送。';
 return '消息投递状态未知，请先查询回执及聊天历史。';
}
