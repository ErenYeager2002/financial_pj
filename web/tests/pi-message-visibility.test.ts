import assert from 'node:assert/strict';
import test from 'node:test';
import {isVisiblePiCustomMessage} from '../src/features/pi-runtime/pi-message-visibility.ts';
test('extension private context is never promoted into displayed messages',()=>{
 for(const display of [false,undefined,null,'true',1,{}])assert.equal(isVisiblePiCustomMessage({role:'custom',display}),false);
 assert.equal(isVisiblePiCustomMessage({role:'custom',display:true}),true);
 for(const role of ['system','custom_message','compactionSummary','branchSummary'])assert.equal(isVisiblePiCustomMessage({role,display:true}),false);
});
