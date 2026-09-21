const test = require('node:test');
const assert = require('node:assert/strict');
const ts = require(process.env.REFACTOR_TYPESCRIPT_PATH || 'typescript');
const {classify} = require('../ts_facts.cjs');
function scan(text,name='web/src/components/demo.tsx') {return classify(ts,ts.createSourceFile(name,text,ts.ScriptTarget.Latest,true),name);}
test('JSX ownership, aliased SDK bindings and symbolic query keys',()=>{
 const facts=scan(`import {generateText as generate} from 'ai';
 import OpenAI from 'openai'; import './demo.css';
 const client = new OpenAI({apiKey:'secret-not-exported'});
 export function Panel(){const x=useQuery({queryKey: keys.detail(user.id)}); return <main><Child /></main>;}
 const response=generate({prompt:'private-prompt'});client.responses.create({input:'private-input'});
 function unrelated(){return create();}`);
 assert.deepEqual(facts.components.map(x=>x.symbol),['Panel']);
 assert.deepEqual(facts.jsx_references.map(x=>x.symbol),['main','Child']);
 assert.equal(facts.query_key_shapes[0].shape.symbol,'keys.detail');
 assert.equal(facts.query_key_shapes[0].shape.arguments[0].symbol,'user.id');
 assert.equal(facts.model_call_candidates.length,2);
 assert.equal(facts.model_call_candidates[0].binding.imported,'generateText');
 assert.equal(facts.model_call_candidates[1].evidence,'sdk-instance-call');
 assert.equal(facts.style_imports[0].module,'./demo.css');
 assert.ok(!JSON.stringify(facts).includes('private-prompt'));
 assert.ok(!JSON.stringify(facts).includes('secret-not-exported'));
});
test('array and shorthand query keys preserve structure without data literals',()=>{
 const facts=scan(`const x={queryKey:['private-key',user.id]};const y={queryKey};`);
 assert.equal(facts.query_key_shapes[0].shape.items[0].kind,'literal');
 assert.equal(facts.query_key_shapes[1].shape.symbol,'queryKey');
 assert.ok(!JSON.stringify(facts).includes('private-key'));
});
test('unrelated calls are not classified as model requests and build configs are marked',()=>{
 const facts=scan(`import {create} from './other';const r=create();`,'web/next.config.ts');
 assert.equal(facts.model_call_candidates.length,0);assert.equal(facts.build_config,true);
});

test('repository Pi SDK imports are tracked without matching unrelated module prefixes',()=>{
 const facts=scan(`import {streamSimple} from '@earendil-works/pi-ai/api/openai-completions.lazy';
 import {create} from 'airtable';streamSimple({});create({});`);
 assert.equal(facts.model_call_candidates.length,1);
 assert.equal(facts.model_call_candidates[0].callee,'streamSimple');
});
