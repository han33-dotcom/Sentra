const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/sentra/enrollment/join.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 5; i++) await new Promise(setImmediate); };
const status = extra => ({csrf:'synthetic-csrf', joining:true, signed_in:false,
  providers_available:['google_health'], consent_version:'1.0', organization:'Synthetic pilot', ...extra});
const response = value => ({ok:true, status:200, json:async()=>value});

function browser(fetch, {hash='#invite=synthetic-private-invitation', shortTimeout=false}={}) {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {hidden:['retry','error','notice'].includes(id), textContent:'',
      checked:false, disabled:false, dataset:{}, events:{}, focus(){}, replaceChildren(){},
      addEventListener(name, handler){this.events[name]=handler;}});
    return nodes.get(id);
  };
  const group = node('group'); group.value='group_only'; group.checked=true;
  const individual = node('individual'); individual.value='individual';
  const google = node('google'); google.dataset.provider='google_health';
  const whoop = node('whoop'); whoop.dataset.provider='whoop';
  const location = {hash, search:'', pathname:'/join', assign(){}};
  const calls=[];
  const events={};
  const document = {getElementById:node, createTextNode:()=>({}), createElement:()=>({}),
    querySelectorAll:s=>s==='[data-provider]'?[google,whoop]:[google,whoop,node('save'),node('retry')],
    querySelector:s=>s.includes('value="individual"')?individual:s.includes('value="group_only"')?group:
      s==='input[name="sharing"]:checked'?(individual.checked?individual:group):null};
  vm.runInNewContext(source, {document, URLSearchParams, AbortController,
    setTimeout:shortTimeout?((fn,delay)=>setTimeout(fn,Math.min(delay,10))):setTimeout, clearTimeout,
    history:{replaceState(){location.hash='';location.search='';}},
    window:{location,addEventListener(name,handler){events[name]=handler;}},
    fetch:async(url,options)=>{calls.push({url,options});return fetch(url,options,calls.length);}});
  return {node,calls,location,events};
}

test('a failed first load keeps the invitation for an explicit retry', async()=>{
  const b=browser(async()=>{if(b.calls.length===1)throw new TypeError('Failed to fetch');return response(status());});
  await flush();
  assert.equal(b.location.hash,'');
  assert.equal(b.node('retry').hidden,false);
  assert.equal(typeof b.node('retry').events.click,'function');
  await b.node('retry').events.click(); await flush();
  assert.equal(b.calls.length,2);
  assert.equal(b.calls[1].url,'/api/session');
  assert.equal(JSON.parse(b.calls[1].options.body).invite,'synthetic-private-invitation');
  assert.equal(b.node('form-content').hidden,false);
});

test('opening an invitation during a pending returning-session load wins over the older response', async()=>{
  let release;
  const returning=new Promise(resolve=>{release=resolve;});
  const b=browser(async url=>url==='/api/status'?returning:response(status()),{hash:''});
  await flush();
  b.location.hash='#invite=new-synthetic-private-invitation';
  const next=b.events.hashchange();
  release(response(status({joining:false})));
  await next; await flush();
  assert.equal(b.node('card-heading').textContent,'Join on your terms');
  assert.equal(JSON.parse(b.calls.find(x=>x.url==='/api/session').options.body).invite,'new-synthetic-private-invitation');
  assert.equal(b.location.hash,'');
});

test('an HTML startup response gives a useful message without a JSON parsing error', async()=>{
  const b=browser(async()=>({ok:true,status:200,json:async()=>{throw new SyntaxError('Unexpected token < in private proxy body');}}));
  await flush();
  assert.doesNotMatch(b.node('error').textContent,/Unexpected token|private proxy/);
  assert.match(b.node('error').textContent,/try again|wait/i);
  assert.equal(b.node('retry').hidden,false);
});

test('a hanging request times out and leaves a recoverable invitation', async()=>{
  const b=browser(async(url,options)=>new Promise((resolve,reject)=>{
    options.signal?.addEventListener('abort',()=>reject(new Error('AbortError')));
  }),{shortTimeout:true});
  await new Promise(resolve=>setTimeout(resolve,40)); await flush();
  assert.equal(b.node('loading').hidden,true);
  assert.equal(b.node('retry').hidden,false);
  assert.match(b.node('error').textContent,/try again|wait/i);
});

test('a failed connect mutation is never automatically submitted twice', async()=>{
  const b=browser(async(url)=>{
    if(url==='/api/session')return response(status());
    throw new TypeError('Failed to fetch');
  });
  await flush(); b.node('accepted').checked=true;
  await b.node('google').events.click(); await flush();
  assert.equal(b.calls.filter(x=>x.url==='/api/connect').length,1);
  assert.equal(b.node('google').disabled,false);
  assert.match(b.node('error').textContent,/try again|wait/i);
});

test('an expired connection is not described as connected while waiting for data', async()=>{
  const b=browser(async()=>response(status({joining:false,signed_in:true,enrolled:true,
    connected:false,recently_contributing:false,sharing:'group_only',demonstration:false,
    latest_received_at:null,collection_paused:true})),{hash:''});
  await flush();
  assert.equal(b.node('connection').textContent,'Reconnect required');
  assert.match(b.node('data-detail').textContent,/reconnect/i);
  assert.doesNotMatch(b.node('data-detail').textContent,/account is connected/);
});
