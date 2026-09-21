import assert from 'node:assert/strict';
import test from 'node:test';
import {submitDraftRequest, sameDraftInput} from '../src/features/run-setup/draft-submission.ts';

const input = {draftId:'draft',parameters:{b:2,a:1},files:{reports:['one','two']}};
const consumed = {state:'consumed',run_id:'original',parameters:{a:1,b:2},files:input.files};

function requests(responses: Response[]) {
  const calls: Array<{path:string;method:string}> = [];
  const fetcher: typeof fetch = async (path,init) => {
    calls.push({path:String(path),method:init?.method ?? 'GET'});
    const response = responses.shift();
    assert.ok(response,'Unexpected extra request');
    return response;
  };
  return {calls,fetcher};
}

test('lost confirmation response replays the original consumed draft',async()=>{
  const {calls,fetcher}=requests([Response.json({detail:'consumed'},{status:409}),Response.json(consumed),Response.json({id:'original'})]);
  const response=await submitDraftRequest(input,fetcher);
  assert.equal((await response.json()).id,'original');
  assert.deepEqual(calls.map(v=>v.method),['PATCH','GET','POST']);
  assert.equal(calls[2].path,'/api/platform/task-drafts/draft/confirm');
});

test('changed input or file order never confirms a consumed draft',async()=>{
  assert.equal(sameDraftInput(consumed,{...input,files:{reports:['two','one']}}),false);
  const {calls,fetcher}=requests([Response.json({detail:'consumed'},{status:409}),Response.json(consumed)]);
  const response=await submitDraftRequest({...input,parameters:{a:99}},fetcher);
  assert.equal(response.status,409);
  assert.deepEqual(calls.map(v=>v.method),['PATCH','GET']);
});

test('ordinary update confirms once and permission failures remain rejected',async()=>{
  const ready=requests([Response.json({state:'ready'}),Response.json({id:'new'})]);
  assert.equal((await submitDraftRequest(input,ready.fetcher)).status,200);
  assert.deepEqual(ready.calls.map(v=>v.method),['PATCH','POST']);
  const denied=requests([Response.json({detail:'denied'},{status:403})]);
  assert.equal((await submitDraftRequest(input,denied.fetcher)).status,403);
  assert.equal(denied.calls.length,1);
});

test('unchanged ready draft reaches fixed-version recovery after publication',async()=>{
  const ready={...consumed,state:'ready',run_id:null};
  const {calls,fetcher}=requests([Response.json({detail:'version changed'},{status:409}),Response.json(ready),Response.json({id:'recovered'})]);
  assert.equal((await (await submitDraftRequest(input,fetcher)).json()).id,'recovered');
  assert.deepEqual(calls.map(v=>v.method),['PATCH','GET','POST']);
  assert.equal(sameDraftInput({...ready,state:'expired'},input),false);
  assert.equal(sameDraftInput(ready,{...input,parameters:{a:5}}),false);
});
