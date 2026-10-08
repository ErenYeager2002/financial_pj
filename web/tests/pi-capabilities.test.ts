import test from 'node:test';
import assert from 'node:assert/strict';
import {checkedPiCapabilities,applyPiCapabilities,permitsPiDialogResponse} from '../src/features/pi-runtime/pi-capabilities.ts';
import {projectPiSessionStatus} from '../src/features/pi-runtime/pi-view-model.ts';
const status=projectPiSessionStatus({connection:'live',running:true,mode:'rpc',working:false,activityKnown:true,dialogCount:1,sending:false,uploading:false,uncertainDelivery:false});
const policy={protocol:'pi-session-capabilities-v1',session_id:'one',can_send:true,can_configure:true,can_start:true,can_upload:true,can_approve_input:true,rpc_commands:['prompt'],reason:''};
test('unknown capabilities do not authorize new work but retain observed stop/refusal',()=>{
 const value=applyPiCapabilities(status,null);assert.equal(value.canSend,false);assert.equal(value.canUpload,false);assert.equal(value.canStartEnvironment,false);assert.equal(value.canManageEnvironment,true);assert.equal(value.canReplyToDialog,true);
});
test('capabilities must belong to this session and use the understood protocol',()=>{
 for(const value of [null,{...policy,session_id:'other'},{...policy,protocol:'future'},{...policy,can_send:'yes'},{...policy,rpc_commands:[{}]}])assert.throws(()=>checkedPiCapabilities(value,'one'));
});
test('revoked permission blocks approval but allows explicit refusal and cancellation',()=>{
 const cap=checkedPiCapabilities({...policy,can_send:false,can_configure:false,can_start:false,can_upload:false,can_approve_input:false,reason:'revoked'},'one');const view=applyPiCapabilities(status,cap);assert.equal(view.canSend,false);assert.equal(view.canApproveInput,false);assert.equal(view.message,'revoked');assert.equal(permitsPiDialogResponse(cap,{confirmed:true}),false);assert.equal(permitsPiDialogResponse(cap,{value:'yes'}),false);assert.equal(permitsPiDialogResponse(cap,{confirmed:false}),true);assert.equal(permitsPiDialogResponse(cap,{cancelled:true}),true);
});
test('upload authorization is independent from prompt authorization',()=>{
 const view=applyPiCapabilities(status,checkedPiCapabilities({...policy,can_upload:false},'one'));assert.equal(view.canSend,true);assert.equal(view.canUpload,false);
});
test('permission cannot override unknown runtime or delivery state',()=>{
 const cap=checkedPiCapabilities(policy,'one');const unknown={...status,canSend:false,canConfigure:false,canManageEnvironment:false,connectionState:'recovering' as const};const view=applyPiCapabilities(unknown,cap);assert.equal(view.canSend,false);assert.equal(view.canConfigure,false);assert.equal(view.canUpload,false);assert.equal(view.canStartEnvironment,false);
});
