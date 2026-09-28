// Tests execute the actual content adapter with a minimal DOM fixture. They
// simulate employer controls and async changes, without opening employer pages.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function fixture(options = {}) {
  class Control {
    constructor(name, type = 'text', required = true) {
      Object.assign(this, {name, type, required, disabled: false, checked: false,
        tagName: 'INPUT', labels: [{textContent: name}], files: [], _value: '', attrs: {}});
    }
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
    getAttribute(name) { return this.attrs[name] ?? null; }
    getClientRects() { return [{}]; }
    closest() { return null; }
    dispatchEvent() { if (options.rejectResume && this.type === 'file') this.files = []; }
    checkValidity() {
      if (this.type === 'file') return !this.required || this.files.length > 0;
      if (this.required && !this.value) return false;
      if (this.type === 'number' && this.value) return Number.isFinite(Number(this.value));
      return true;
    }
  }
  class FixtureFile {
    constructor(parts, name) { this.name = name; this.size = parts.reduce((n, p) => n + p.length, 0); this.lastModified = 1; }
  }
  class Transfer {
    constructor() { this.files = []; this.items = {add: file => this.files.push(file)}; }
  }
  const name = new Control('Full name');
  const email = new Control('Email', 'email');
  const resume = new Control('Resume', 'file');
  const fields = [name, email, resume];
  if (options.number) fields.push(new Control('Years of Python', 'number', false));
  let clicked = 0, challenge = false, custom = false;
  const button = {textContent: 'Submit application', disabled: false, getClientRects: () => [{}], click: () => clicked++};
  const form = {
    isConnected: true,
    querySelector: selector => selector.startsWith('input[') ? email : custom ? {} : null,
    querySelectorAll: selector => selector === 'input,textarea,select' ? fields : selector.startsWith('button') ? [button] : [],
    checkValidity: () => fields.every(el => el.checkValidity())
  };
  button.form = form;
  const context = vm.createContext({
    location: {hostname: 'jobs.lever.co', href: 'https://jobs.lever.co/example/job/apply'},
    document: {
      querySelector: () => challenge ? {} : null,
      querySelectorAll: selector => selector === 'form' ? (options.multiple ? [form, form] : [form]) : selector.startsWith('form.application') ? [form] : [button]
    },
    getComputedStyle: () => ({visibility: 'visible'}),
    HTMLInputElement: Control, HTMLTextAreaElement: Control, HTMLSelectElement: Control,
    File: FixtureFile, DataTransfer: Transfer, Event: class {}, Uint8Array, URL,
    atob: value => Buffer.from(value, 'base64').toString('binary')
  });
  for (const file of ['rules.js', 'content.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, '../extension', file), 'utf8'), context);
  const payload = {
    profile: {name: 'Example Candidate', email: 'example@example.com', answers: options.number ? {'Years of Python': 'not a number'} : {}},
    resume: {name: 'example.txt', base64: Buffer.from('Fictional resume').toString('base64')}, job: {materials: {}}
  };
  return {context, fields, form, name, resume, Control, fill: () => context.jobPilotFill(payload),
    submit: () => context.jobPilotSubmit(), clicks: () => clicked,
    addChallenge: () => { challenge = true; }, addCustom: () => { custom = true; }};
}

test('unchanged recognized form can send exactly one click', () => {
  const f = fixture();
  assert.equal(f.fill().missing.length, 0);
  assert.equal(f.name.value, 'Example Candidate');
  assert.equal(f.resume.files.length, 1);
  assert.equal(f.submit().clicked, true);
  assert.equal(f.submit().clicked, false);
  assert.equal(f.clicks(), 1);
});
test('submission without a completed autofill cannot click', () => {
  const f = fixture();
  assert.equal(f.submit().clicked, false);
  assert.equal(f.clicks(), 0);
});
test('changed answer blocks the final click', () => {
  const f = fixture(); f.fill(); f.name.value = 'Changed after autofill';
  assert.equal(f.submit().clicked, false); assert.equal(f.clicks(), 0);
});
test('new question after autofill blocks submission even if optional', () => {
  const f = fixture(); f.fill(); f.fields.push(new f.Control('New screening question', 'text', false));
  assert.equal(f.submit().clicked, false);
});
test('replaced DOM controls cannot reuse the old snapshot', () => {
  const f = fixture(); f.fill();
  const replacement = new f.Control('Full name'); replacement.value = f.name.value;
  f.fields[0] = replacement;
  assert.equal(f.submit().clicked, false);
});
test('removed resume, disconnected form, and changed destination block submission', () => {
  for (const change of [f => {f.resume.files = [];}, f => {f.form.isConnected = false;}, f => {f.context.location.href = 'https://jobs.lever.co/example/other/apply';}]) {
    const f = fixture(); f.fill(); change(f); assert.equal(f.submit().clicked, false);
  }
});
test('challenge or custom widget appearing later requires review', () => {
  for (const method of ['addChallenge', 'addCustom']) {
    const f = fixture(); f.fill(); f[method](); assert.equal(f.submit().clicked, false);
  }
});
test('a form that discards the uploaded file is not submission-ready', () => {
  const f = fixture({rejectResume: true}), report = f.fill();
  assert.equal(report.hasResume, false); assert.ok(report.missing.length); assert.equal(f.submit().clicked, false);
});
test('invalid saved numeric answers require review', () => {
  const f = fixture({number: true});
  assert.ok(f.fill().missing.some(x => x.includes('invalid number')));
  assert.equal(f.submit().clicked, false);
});
test('multiple possible application forms require review', () => {
  const f = fixture({multiple: true});
  assert.equal(f.fill().formFound, false); assert.equal(f.submit().clicked, false);
});
