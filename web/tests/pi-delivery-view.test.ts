import test from 'node:test';
import assert from 'node:assert/strict';
import {applyTransportReceipt,markDeliveryUncertain,deliveryUnconfirmed,deliveryMessage} from '../src/features/pi-runtime/pi-delivery-view.ts';
const receipt={client_request_id:'one',delivery_state:'pi_accepted' as const,updated_at:'now'};
test('durable stdin-write receipt cannot claim a Pi acknowledgement',()=>{
 const view=applyTransportReceipt({id:'one',state:'submitting'},receipt);
 assert.deepEqual(view,{id:'one',state:'transport_accepted'});assert.equal(deliveryUnconfirmed(view),true);
 assert.match(deliveryMessage(view!.state),/尚待确认/);
});
test('late transport receipt never downgrades actual Pi acceptance or rejection',()=>{
 for(const state of ['pi_accepted','rejected'] as const){const current={id:'one',state};assert.equal(applyTransportReceipt(current,receipt),current);assert.equal(markDeliveryUncertain(current,'one'),current)}
});
test('old receipt cannot replace a newer intentional send',()=>{
 const current={id:'two',state:'submitting' as const};assert.equal(applyTransportReceipt(current,receipt),current);assert.equal(markDeliveryUncertain(current,'one'),current);
});
test('restored receipt remains unconfirmed without a live Pi response',()=>{
 const view=applyTransportReceipt({id:'one',state:'unknown'},receipt);assert.equal(deliveryUnconfirmed(view),true);
 assert.equal(deliveryUnconfirmed({id:'one',state:'pi_accepted'}),false);assert.equal(deliveryUnconfirmed({id:'one',state:'rejected'}),false);
});
test('missing transport evidence remains unknown without manufacturing success',()=>{
 assert.deepEqual(markDeliveryUncertain({id:'one',state:'transport_accepted'},'one'),{id:'one',state:'unknown'});
 assert.equal(applyTransportReceipt(null,receipt),null);
});

test('a settling previous turn cannot unlock a new submitting delivery',()=>{assert.equal(deliveryUnconfirmed({id:'new',state:'submitting'}),true)});
