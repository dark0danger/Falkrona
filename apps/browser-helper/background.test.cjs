const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function fixture(granted = true, provider = 'gemini') {
  let listener, opened = 0;
  const sent = [], created = [];
  let closed = false;
  const local = {connection: {origin: 'https://owner.example', provider}};
  const session = {};
  const registered = [];
  const store = data => ({get: async key => ({[key]: structuredClone(data[key])}), set: async values => Object.assign(data, structuredClone(values))});
  const chrome = {storage: {local: store(local), session: store(session)},
    runtime: {onMessage: {addListener: fn => {listener = fn;}}},
    tabs: {create: async options => {created.push(options); closed=false; return {id: ++opened + 100};}, get: async () => {if(closed)throw new Error('No tab');return {status: 'complete'};}, sendMessage: async (tabId, message) => {sent.push({tabId, message}); return {accepted: true};}},
    permissions: {contains: async () => granted},
    scripting: {executeScript: async () => [], getRegisteredContentScripts:async()=>registered,
      registerContentScripts:async scripts=>registered.push(...scripts)}};
  vm.runInNewContext(fs.readFileSync(__dirname + '/background.js', 'utf8'), {chrome, URL, Date, setTimeout});
  const owner = {tab: {id: 1}, frameId: 0, url: 'https://owner.example/studio'};
  const packet = {run_id: 'a'.repeat(36), workspace_id: 'b'.repeat(36), provider, url: provider==='gemini'?'https://gemini.google.com/app':'https://chatgpt.com/',
    nonce: 'random', expires_at: new Date(Date.now()+60000).toISOString(), prompt: 'Generate a complete ad',
    attachments: [{role: 'logo'}, {role: 'product'}]};
  const call = (message, sender = owner) => new Promise(resolve => listener(message, sender, resolve));
  return {call, owner, packet, session, local, sent, created, registered, closeProvider:()=>{closed=true;}, opened: () => opened};
}
test('helper rejects unconnected origins and subframes', async () => {
  const f = fixture();
  assert.ok((await f.call({action: 'status'}, {...f.owner, url: 'https://attacker.example/'})).error);
  assert.ok((await f.call({action: 'status'}, {...f.owner, frameId: 2})).error);
  assert.equal((await f.call({action: 'status'})).connected, true);
});
test('one run opens one fresh tab and never resubmits after an interruption', async () => {
  const f = fixture();
  await f.call({action: 'start', packet: f.packet});
  await f.call({action: 'start', packet: f.packet});
  f.session.job.stage = 'paused';
  f.session.job.submitted = true;
  await f.call({action: 'start', packet: f.packet});
  assert.equal(f.opened(), 1);
  const wrongTab = await f.call({action: 'start', packet: f.packet}, {...f.owner, tab: {id: 2}});
  assert.ok(wrongTab.error);
});
test('an explicit resume may restart a known pre-submission login pause', async () => {
  const f = fixture();
  await f.call({action: 'start', packet: f.packet});
  f.session.job.stage = 'paused';
  f.session.job.submitted = false;
  await f.call({action: 'start', packet: f.packet});
  assert.equal(f.opened(), 1);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.sent.at(-1).message.action, 'resume');
  assert.equal(f.sent.at(-1).message.observeOnly, false);
});
test('returns only an image from the bound provider tab after a submitted request', async () => {
  const f = fixture();
  await f.call({action: 'start', packet: f.packet});
  const provider = {tab: {id: f.session.job.providerTab}, frameId: 0, url: 'https://gemini.google.com/app/123'};
  const result = {action: 'provider-result', image: 'data:image/png;base64,YWJj'};
  assert.ok((await f.call(result, provider)).error);
  await f.call({action: 'provider-progress', stage: 'submitted'}, provider);
  assert.ok((await f.call(result, {...provider, tab: {id: 999}})).error);
  assert.equal((await f.call(result, provider)).ok, true);
  const returned = await f.call({action: 'poll', runId: f.packet.run_id});
  assert.equal(returned.image, result.image);
  assert.equal(returned.stage, 'complete');
});
test('provider and attachment roles cannot be silently changed', async () => {
  const f = fixture();
  assert.ok((await f.call({action: 'start', packet: {...f.packet, provider: 'chatgpt'}})).error);
  assert.ok((await f.call({action: 'start', packet: {...f.packet, attachments: [{role:'logo'}, {role:'reference'}]}})).error);
  assert.equal(f.opened(), 0);
});
test('a fresh owner packet renews an expired completed import without a second Send', async () => {
  const f=fixture();await f.call({action:'start',packet:f.packet});
  await new Promise(resolve=>setImmediate(resolve));
  const provider={tab:{id:f.session.job.providerTab},frameId:0,url:'https://gemini.google.com/app/abc123'};
  await f.call({action:'provider-progress',stage:'submitted'},provider);
  await f.call({action:'provider-result',image:'data:image/png;base64,YWJj'},provider);
  f.session.job.expiresAt=new Date(Date.now()-1000).toISOString();
  assert.equal((await f.call({action:'poll',runId:f.packet.run_id})).stage,'paused');
  const sent=f.sent.length;
  assert.equal((await f.call({action:'start',packet:f.packet})).stage,'complete');
  assert.equal((await f.call({action:'poll',runId:f.packet.run_id})).image,'data:image/png;base64,YWJj');
  assert.equal(f.sent.length,sent);assert.equal(f.opened(),1);
});

test('extension startup restores its bridge only with an existing owner-origin grant', async () => {
  const allowed=fixture(), revoked=fixture(false);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(allowed.registered.length,1);
  assert.equal(allowed.registered[0].matches[0],'https://owner.example/*');
  assert.equal(revoked.registered.length,0);
});

test('resume after extension reload cannot create another request when job tracking is missing', async () => {
  const f = fixture();
  assert.equal((await f.call({action: 'status'})).helper_version, '0.1.5');
  const result = await f.call({action: 'start', packet: f.packet, resumeOnly: true});
  assert.equal(result.stage, 'paused');
  assert.match(result.error, /nothing was resent/);
  assert.equal(f.opened(), 0);
});

test('extension reload preserves bound submission metadata and resumes observation', async () => {
  const f = fixture();
  await f.call({action:'start',packet:f.packet});
  const provider={tab:{id:f.session.job.providerTab},frameId:0,url:'https://gemini.google.com/app/abc123'};
  await f.call({action:'provider-progress',stage:'submitted'},provider);
  assert.equal(f.local.jobs[f.packet.run_id].submitted,true);
  assert.equal(f.local.jobs[f.packet.run_id].image,undefined);
  delete f.session.job;
  await f.call({action:'start',packet:f.packet,resumeOnly:true});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.opened(),1);
  assert.equal(f.sent.at(-1).message.action,'resume');
  assert.equal(f.sent.at(-1).message.observeOnly,true);
});

test('a closed submitted tab reopens only its bound conversation for observation', async () => {
  const f=fixture();await f.call({action:'start',packet:f.packet});
  const url='https://gemini.google.com/app/abc123';
  await f.call({action:'provider-progress',stage:'submitted'},{tab:{id:f.session.job.providerTab},frameId:0,url});
  delete f.session.job;f.closeProvider();
  await f.call({action:'start',packet:f.packet});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.created.at(-1).url,url);
  assert.equal(f.sent.at(-1).message.observeOnly,true);
});

test('a closed submitted tab without a conversation URL pauses without sending again', async () => {
  const f=fixture();await f.call({action:'start',packet:f.packet});
  await f.call({action:'provider-progress',stage:'submitted'},{tab:{id:f.session.job.providerTab},frameId:0,url:f.packet.url});
  delete f.session.job;f.closeProvider();
  const result=await f.call({action:'start',packet:f.packet});
  assert.equal(result.stage,'paused');assert.match(result.error,/nothing was resent/);
  assert.equal(f.opened(),1);
});

test('a stale ChatGPT view gets one fresh observer of the same submitted conversation', async () => {
  const f=fixture(true,'chatgpt');await f.call({action:'start',packet:f.packet});
  const provider={tab:{id:f.session.job.providerTab},frameId:0,url:'https://chatgpt.com/c/abc123'};
  assert.equal((await f.call({action:'provider-refresh',packet:f.packet},provider)).ok,false);
  await f.call({action:'provider-progress',stage:'submitted'},provider);
  assert.ok((await f.call({action:'provider-refresh',packet:f.packet},{...provider,tab:{id:999}})).error);
  assert.equal((await f.call({action:'provider-refresh',packet:f.packet},provider)).ok,true);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.created.at(-1).url,provider.url);assert.equal(f.sent.at(-1).message.observeOnly,true);
  const fresh={...provider,tab:{id:f.session.job.providerTab}};
  assert.equal((await f.call({action:'provider-refresh',packet:f.packet},fresh)).ok,false);
  assert.equal(f.opened(),2);
});
