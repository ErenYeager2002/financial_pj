import assert from 'node:assert/strict';
import test from 'node:test';
import {validatePiDialogReply as validate,type PiDialog} from '../src/features/pi-runtime/pi-dialog-gate.ts';
import {projectPiSessionStatus} from '../src/features/pi-runtime/pi-view-model.ts';
const request:PiDialog={id:'current',method:'confirm',expires_at:200};
const response={type:'extension_ui_response',id:'current',confirmed:true};
test('disconnect, unknown activity, stopped and terminal states block tool responses',()=>{
 const live={connection:'live' as const,running:true,mode:'rpc',working:true,activityKnown:true,dialogCount:1,sending:false,uploading:false,uncertainDelivery:false};
 assert.equal(projectPiSessionStatus(live).canReplyToDialog,true);
 for(const facts of [{...live,connection:'recovering' as const},{...live,connection:'connecting' as const},{...live,activityKnown:false},{...live,running:false},{...live,mode:'terminal'},{...live,dialogCount:0}]){
  const available=projectPiSessionStatus(facts).canReplyToDialog;
  assert.equal(available,false);assert.throws(()=>validate(available,[request],response,100));
 }
});
test('closed or previous generation request cannot be submitted',()=>{
 assert.throws(()=>validate(true,[],response,100));
 assert.throws(()=>validate(true,[{...request,id:'new'}],response,100));
});
test('expiration is checked at click time, including the exact boundary',()=>{
 for(const time of [200,201])assert.throws(()=>validate(true,[request],response,time));
 assert.deepEqual(validate(true,[request],response,199),response);
});
test('confirm and reject require explicit booleans and cancellation is preserved',()=>{
 for(const confirmed of [true,false])assert.equal(validate(true,[request],{...response,confirmed},100).confirmed,confirmed);
 assert.throws(()=>validate(true,[request],{...response,confirmed:'true'},100));
 assert.deepEqual(validate(true,[request],{...response,cancelled:true},100),{type:'extension_ui_response',id:'current',cancelled:true});
});
test('text, editor and selection retain their respective response contracts',()=>{
 for(const method of ['input','editor'] as const)assert.equal(validate(true,[{...request,method}],{type:response.type,id:'current',value:''},100).value,'');
 const select:PiDialog={...request,method:'select',options:['one','two']};
 assert.throws(()=>validate(true,[select],{...response,value:'other'},100));
 assert.equal(validate(true,[select],{type:response.type,id:'current',value:'two'},100).value,'two');
});
test('protocol mutations and extra authorization fields are rejected',()=>{
 assert.throws(()=>validate(true,[request],{...response,type:'prompt'},100));
 assert.throws(()=>validate(true,[request],{...response,approved:true},100));
});
