const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const {normalizePrompt, promptMatches} = require('./provider-dom.js');

function fixture({submitted = false, missingAttachment = false, changedPrompt = false, fresh=false, hydration=false, stale=false, videoFirst=false, ignoredFirst=false, partialUpload=false, menuDelayed=false, menuUnavailable=false, duplicatePreview=false, transientPreview=false, distinctImages=false} = {}) {
  let listener, clicks = 0, fetched = 0, uploads=0, clock = Date.now();
  const stages = [];
  const packet = {provider: 'chatgpt', prompt: 'Create our ad.\n\nExact CTA: Save this for later.',
    expires_at: new Date(clock + (stale?360000:65000)).toISOString(),
    attachments: [{name: 'logo.png',data:'YQ==',mime_type:'image/png'}, {name: 'product.png',data:'YQ==',mime_type:'image/png'}]};
  const composer = {value: '', innerText: packet.prompt.replace(/\n/g, '\n\n').replace(/ /g, '\u00a0')};
  if (changedPrompt) composer.innerText = 'Unrelated request';
  if(fresh)composer.innerText='';
  Object.assign(composer,{tagName:'DIV',focus(){},dispatchEvent(){}});
  const users = submitted ? [{innerText: packet.prompt}] : [];
  const image = {complete: true, naturalWidth: 1122, naturalHeight: 1402,
    currentSrc: 'https://chatgpt.com/visible-generated-image', getClientRects: () => [1]};
  let previewReads=0;
  const resultImages=()=>{
    previewReads++;
    if(stale)return [];
    if(duplicatePreview)return [image,{...image}];
    if(distinctImages||transientPreview&&previewReads<3)return [image,{...image,currentSrc:'https://chatgpt.com/other-preview'}];
    return [image];
  };
  const responses = submitted ? [{querySelectorAll: resultImages}] : [];
  const send = {click() {
    assert.equal(stages.at(-1), 'submitted', 'Submission intent must be recorded before Send');
    clicks++;
    users.push({innerText: packet.prompt});
    responses.push({querySelectorAll: resultImages});
  }};
  class Clock extends Date {static now() {return clock;}}
  let resolveResult;
  const result = new Promise(resolve => {resolveResult = resolve;});
  let input;
  const makeInput=()=>({id:'upload',multiple:true,isConnected:true,getAttribute:name=>name==='aria-label'?'Attach files':null,dispatchEvent(){
    uploads++;
    if(partialUpload){this.files=[];document.body.innerText='logo.png';}
    else if(ignoredFirst && uploads===1){this.files=[];}
    else if(hydration && uploads===1){this.isConnected=false;input=makeInput();}
    else document.body.innerText='logo.png product.png';
  }});
  input=makeInput();
  let expanded=false, menuClicks=0;
  const uploadToggle={getClientRects:()=>[1],getAttribute:name=>name==='aria-label'?'Add files and more':name==='aria-expanded'?String(expanded):null,
    click(){menuClicks++;if(!menuUnavailable&&(!menuDelayed||menuClicks>=4))expanded=!expanded;}};
  const uploadMenu={getClientRects:()=>[1],getAttribute:name=>name==='aria-label'?'Add photos & files Upload from computer':null};
  const document = {body: {innerText: fresh?'':missingAttachment ? 'logo.png' : 'logo.png product.png'},
    execCommand(_name,_ui,text){composer.innerText=text;},
    querySelectorAll: selector => selector==='button,[role=menuitem],[role=option]'?[uploadToggle,...(expanded?[uploadMenu]:[])]:selector==='input[type="file"]' && fresh?(videoFirst?
      [{id:'video',multiple:true,getAttribute:name=>name==='accept'?'image/*,video/*':'Attach photos or videos',dispatchEvent(){throw new Error('Inactive video input used');}},input]:[input]):[]};
  const chrome = {runtime: {onMessage: {addListener: fn => {listener = fn;}}, sendMessage: async message => {
    if (message.action === 'provider-progress') stages.push(message.stage);
    if (message.action === 'provider-result') resolveResult(message);
    if (message.action === 'provider-refresh') resolveResult({refreshed:true});
    return {ok: true};
  }}};
  class Reader {readAsDataURL() {this.result = 'data:image/png;base64,YWJj'; this.onload();}}
  vm.runInNewContext(fs.readFileSync(__dirname + '/provider.js', 'utf8'), {
    chrome, document, URL, location: {origin: 'https://chatgpt.com'}, Date: Clock,
    getComputedStyle: () => ({visibility: 'visible'}), FileReader: Reader,
    DataTransfer:class {constructor(){this.files=[];this.items={add:file=>this.files.push(file)};}},
    File:class {constructor(_bytes,name){this.name=name;}},Event:class {},InputEvent:class {},
    atob: value=>Buffer.from(value,'base64').toString('binary'),
    setTimeout: fn => {clock += 500; queueMicrotask(fn);},
    fetch: async source => {fetched++; assert.equal(source, image.currentSrc); return {ok: true, blob: async () => ({type: 'image/png', size: 3})};},
    falkronaProviderDOM: {normalizePrompt, promptMatches, findComposer: () => composer, findSend: () => send,
      messages: kind => kind === 'user' ? users : responses}
  });
  listener({action: fresh?'generate':'resume', packet}, {}, () => {});
  return {result, stages, clicks: () => clicks, fetched: () => fetched, uploads:()=>uploads, menuClicks:()=>menuClicks};
}

test('staged rich text with all attachments sends once and returns the matching image', async () => {
  const f = fixture();
  const result = await f.result;
  assert.equal(result.image, 'data:image/png;base64,YWJj');
  assert.equal(f.clicks(), 1);
  assert.equal(f.fetched(), 1);
  assert.ok(f.stages.includes('ready_to_send'));
});

test('a manually submitted matching request is observed without another Send', async () => {
  const f = fixture({submitted: true});
  assert.ok((await f.result).image);
  assert.equal(f.clicks(), 0);
  assert.equal(f.fetched(), 1);
});

test('removed attachment pauses before Send', async () => {
  const f = fixture({missingAttachment: true});
  assert.match((await f.result).error, /confirm all attachments/);
  assert.equal(f.clicks(), 0);
  assert.equal(f.fetched(), 0);
});

test('a changed staged prompt pauses before Send', async () => {
  const f = fixture({changedPrompt: true});
  assert.match((await f.result).error, /message changed/);
  assert.equal(f.clicks(), 0);
});

test('fresh-tab hydration replacement retries only an empty unsent upload and sends once', async () => {
  const f=fixture({fresh:true,hydration:true});
  assert.ok((await f.result).image);assert.equal(f.uploads(),2);assert.equal(f.clicks(),1);
});

test('a stable fresh tab uploads once and returns the generated image', async () => {
  const f=fixture({fresh:true});
  assert.ok((await f.result).image);assert.equal(f.uploads(),1);assert.equal(f.clicks(),1);
});

test('a visible but unhydrated composer waits for its upload menu before attaching', async () => {
  const f=fixture({fresh:true,menuDelayed:true});
  assert.ok((await f.result).image);assert.equal(f.uploads(),1);assert.equal(f.clicks(),1);
  assert.equal(f.menuClicks(),5); // Three ignored opens, one acknowledged open, one close.
});

test('an upload menu that never initializes pauses without attaching or sending', async () => {
  const f=fixture({fresh:true,menuUnavailable:true});
  assert.match((await f.result).error,/controls are still loading/);
  assert.equal(f.uploads(),0);assert.equal(f.clicks(),0);
});

test('ChatGPT video input before Attach files is skipped and the request sends once', async () => {
  const f=fixture({fresh:true,videoFirst:true});
  assert.ok((await f.result).image);assert.equal(f.uploads(),1);assert.equal(f.clicks(),1);
});

test('hydration that retains but clears an inactive input retries only the empty unsent upload', async () => {
  const f=fixture({fresh:true,ignoredFirst:true});
  assert.ok((await f.result).image);assert.equal(f.uploads(),2);assert.equal(f.clicks(),1);
});

test('a partially accepted upload is never repeated or submitted', async () => {
  const f=fixture({fresh:true,partialUpload:true});
  assert.match((await f.result).error,/confirm all attachments/);
  assert.equal(f.uploads(),1);assert.equal(f.clicks(),0);
});

test('a stalled image response requests a fresh observer without another Send', async () => {
  const f=fixture({stale:true});
  assert.equal((await f.result).refreshed,true);assert.equal(f.clicks(),1);assert.equal(f.fetched(),0);
});

test('duplicate DOM previews of the same generated image are imported once', async () => {
  const f=fixture({submitted:true,duplicatePreview:true});
  assert.ok((await f.result).image);assert.equal(f.clicks(),0);assert.equal(f.fetched(),1);
});

test('overlapping temporary and finished previews settle before cardinality is checked', async () => {
  const f=fixture({submitted:true,transientPreview:true});
  assert.ok((await f.result).image);assert.equal(f.clicks(),0);assert.equal(f.fetched(),1);
});

test('genuinely distinct finished images still require the owner to choose', async () => {
  const f=fixture({submitted:true,distinctImages:true});
  assert.match((await f.result).error,/Multiple generated images/);
  assert.equal(f.clicks(),0);assert.equal(f.fetched(),0);
});
