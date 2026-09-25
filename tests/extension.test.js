const {test}=require('node:test');
const assert=require('node:assert/strict');
const {answer,supported,sameApplication,canSubmit}=require('../extension/rules.js');
const profile={name:'Example Candidate',email:'candidate@example.com',answers:{'Do you need sponsorship?':'Yes'}};
test('exact saved answers can be reused without inferring sensitive details',()=>{
 assert.equal(answer('Do you need sponsorship? *',profile),'Yes');
 assert.equal(answer('Are you authorized to work in Canada?',profile),null);
 assert.equal(answer('Gender',profile),null);
 assert.equal(answer('First name',profile),null);
});
test('known contact fields only',()=>{
 assert.equal(answer('Email address (required)',profile),profile.email);
 assert.equal(answer('Manager email address',profile),null);
 assert.equal(answer('Full name',profile),profile.name);
});
test('supported hostname cannot be spoofed with a suffix or credentials',()=>{
 assert.equal(supported('https://jobs.lever.co/company/job'),true);
 assert.equal(supported('https://jobs.lever.co.evil.test/x'),false);
 assert.equal(supported('http://jobs.lever.co/company/job'),false);
 assert.equal(supported('https://user:password@jobs.lever.co/company/job'),false);
 assert.equal(supported('https://jobs.lever.co:8443/company/job'),false);
});
test('same-host redirects cannot silently change the approved job',()=>{
 assert.equal(sameApplication('https://jobs.lever.co/company/a','https://jobs.lever.co/company/a/apply'),true);
 assert.equal(sameApplication('https://jobs.lever.co/company/a','https://jobs.lever.co/company/b/apply'),false);
});
test('only complete standard Lever forms can enter submit',()=>{
 const report={filled:3,hasResume:true,formFound:true,missing:[],challenges:[],submitCount:1};
 assert.equal(canSubmit('https://jobs.lever.co/example/x',report),true);
 for(const patch of [{missing:['Sponsorship']},{challenges:['CAPTCHA']},{hasResume:false},{submitCount:2},{formFound:false}])assert.equal(canSubmit('https://jobs.lever.co/example/x',{...report,...patch}),false);
 assert.equal(canSubmit('https://jobs.ashbyhq.com/example/x',report),false);
});
