const {test} = require('node:test');
const assert = require('node:assert/strict');
const {normalizePrompt,findSend,messages,promptMatches} = require('./provider-dom.js');
global.getComputedStyle = element => ({visibility: element.hidden ? 'hidden' : 'visible'});
const node = (label, options = {}) => ({textContent: '', disabled: false, getClientRects: () => [1],
  getAttribute: name => name === 'aria-label' ? label : options[name] ?? null, ...options});
test('rich-text paragraphs, NBSP and invisible editor markers do not block the complete prompt', () => {
  const prompt = 'Generate ONE ad.\n\nExact headline: Fresh coffee.\nExact CTA: Save this.';
  const rendered = 'Generate ONE ad.\n\n\nExact headline: Fresh\u00a0coffee.\n\nExact CTA: Save this.\u200b';
  assert.equal(normalizePrompt(rendered), normalizePrompt(prompt));
  assert.notEqual(normalizePrompt(rendered.replace('Fresh', 'Bad')), normalizePrompt(prompt));
  assert.notEqual(normalizePrompt(rendered.slice(0, 40)), normalizePrompt(prompt));
});
test('uses the unique enabled Send control in the composer form', () => {
  const send = node('Send', {type: 'submit'}), unrelated = node('Send message');
  const form = {querySelectorAll: () => [node('Dictate'), node('Start Voice'), send]};
  const composer = {closest: () => form};
  assert.equal(findSend(composer), send);
  send.disabled = true; assert.equal(findSend(composer), null);
  send.disabled = false; form.querySelectorAll = () => [send, unrelated];
  assert.equal(findSend(composer), null); // Ambiguous send must never click twice.
  form.querySelectorAll = () => [node('Send', {'aria-disabled': 'true'})];
  assert.equal(findSend(composer), null);
});
test('recognizes current ChatGPT message headings and binds a result to the full original prompt', () => {
  const prompt = 'Generate ONE ad. Exact headline: Fresh coffee.';
  const user = {innerText: 'You said:\n'+prompt}, assistant = {innerText: 'ChatGPT said:\nGenerated image 1'};
  const root = {querySelectorAll: selector => selector === 'main h4' ? [
    {textContent:'You said:',parentElement:user},{textContent:'ChatGPT said:',parentElement:assistant}] : []};
  assert.deepEqual(messages('user',root), [user]);
  assert.deepEqual(messages('assistant',root), [assistant]);
  assert.equal(promptMatches(user,prompt), true);
  assert.equal(promptMatches(user,prompt+' Different product'), false);
});
