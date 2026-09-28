const {test}=require('node:test');
const assert=require('node:assert/strict');
const {answer,supported,sameApplication,canSubmit}=require('../extension/rules.js');
const profile={name:'Example Candidate',email:'candidate@example.com',answers:{'Do you need sponsorship?':'Yes'}};
test('first and last names use explicit profile values only',()=>{
 assert.equal(answer('First name',profile),null);
 assert.equal(answer('First name',{...profile,first_name:'Example'}),'Example');
 assert.equal(answer('Family name',{...profile,last_name:'Candidate'}),'Candidate');
});
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

// Exercise the actual service worker with simulated Chrome/server responses.
// No browser tabs, network calls or real application submissions are made.
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
async function batchFixture(options={}) {
 const jobs=options.jobs??[{id:'selected',title:'Engineer',company:'Example',url:'https://jobs.lever.co/example/selected'}];
 const calls=[],progress=[];
 let listener,clicked=false;
 const response=(value,ok=true)=>({ok,json:async()=>value});
 const context=vm.createContext({
  URL,console,setTimeout:callback=>{callback();return 0},
  chrome:{
   runtime:{onMessage:{addListener:fn=>{listener=fn}}},
   storage:{local:{get:async()=>({server:'http://127.0.0.1:8765',token:'fictional'}),set:async value=>{progress.push(value.progress)}}},
   permissions:{contains:async()=>true},
   tabs:{create:async tab=>{calls.push({tab:tab.url});return {id:1}},get:async()=>({status:'complete',url:options.redirect||jobs[0].url})},
   scripting:{executeScript:async injection=>{
    if(injection.files)return [];
    const code=injection.func.toString();
    if(code.includes('jobPilotFill'))return [{result:{filled:3,hasResume:true,formFound:true,missing:[],challenges:[],submitCount:1}}];
    if(code.includes('jobPilotSubmit')){clicked=true;return [{result:{clicked:true}}]}
    return [{result:{success:clicked&&!options.unknown,url:jobs[0].url,excerpt:'Fixture confirmation'}}];
   }}
  },
  fetch:async(url,init)=>{
   const route=new URL(url).pathname;
   const data=init.body?JSON.parse(init.body):null;
   calls.push({route,data});
   if(route==='/api/queue')return response(jobs);
   if(route.endsWith('/claim'))return response(options.claimFails?{error:'Approval changed'}:{profile:{},job:jobs[0]},!options.claimFails);
   if(data?.action==='submitting'&&options.stopDuringSubmitting)listener({type:'stop'},{},()=>{});
   return response({ok:true});
  }
 });
 context.importScripts=file=>vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension',file),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../extension/background.js'),'utf8'),context);
 await vm.runInContext(`runBatch(${options.autoSubmit!==false},5)`,context);
 return {calls,progress,clicked,actions:calls.filter(x=>x.data?.action).map(x=>x.data.action)};
}
test('helper processes only the explicit queue returned by the server',async()=>{
 const result=await batchFixture();
 assert.deepEqual(result.calls.filter(x=>x.route?.endsWith('/claim')).map(x=>x.route),['/api/jobs/selected/claim']);
 assert.deepEqual(result.actions,['submitting','submitted']);
 assert.match(result.progress.at(-1).message,/1 confirmed submissions/);
});
test('an empty selected queue never opens or submits a job',async()=>{
 const result=await batchFixture({jobs:[]});
 assert.equal(result.clicked,false);
 assert.equal(result.calls.some(x=>x.tab),false);
 assert.deepEqual(result.actions,[]);
});
test('autofill-only mode leaves the application for review',async()=>{
 const result=await batchFixture({autoSubmit:false});
 assert.equal(result.clicked,false);
 assert.deepEqual(result.actions,['needs_review']);
});
test('Stop received during the submitting request prevents the click',async()=>{
 const result=await batchFixture({stopDuringSubmitting:true});
 assert.equal(result.clicked,false);
 // The server already recorded an attempt; keep its conservative recovery state.
 assert.deepEqual(result.actions,['submitting','submission_unknown']);
 assert.match(result.progress.at(-1).message,/Stopped/);
});
test('an unconfirmed click is never reported as a confirmed submission',async()=>{
 const result=await batchFixture({unknown:true});
 assert.equal(result.clicked,true);
 assert.deepEqual(result.actions,['submitting','submission_unknown']);
 assert.match(result.progress.at(-1).message,/0 confirmed submissions/);
});
test('a rejected approval claim never opens or fills the application',async()=>{
 const result=await batchFixture({claimFails:true});
 assert.equal(result.clicked,false);
 assert.equal(result.calls.some(x=>x.tab),false);
 assert.deepEqual(result.actions,[]);
});
test('a redirect to another job stops the worker before filling',async()=>{
 const result=await batchFixture({redirect:'https://jobs.lever.co/example/another'});
 assert.equal(result.clicked,false);
 assert.deepEqual(result.actions,['needs_review']);
});
