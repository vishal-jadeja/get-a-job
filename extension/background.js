importScripts('rules.js');
const origins=['https://jobs.lever.co/*','https://jobs.eu.lever.co/*','https://boards.greenhouse.io/*','https://job-boards.greenhouse.io/*','https://jobs.ashbyhq.com/*'];
let running=false,stopRequested=false;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function api(path,data){const {server,token}=await chrome.storage.local.get(['server','token']);if(!server||!token)throw Error('Connect the helper first');const response=await fetch(server+'/api/'+path,{method:data===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.error||'Local server error');return result;}
async function status(message,extra={}){await chrome.storage.local.set({progress:{message,running,...extra}});}
async function action(id,kind,detail=''){return api('jobs/'+id+'/action',{action:kind,detail});}
async function waitForTab(id){for(let i=0;i<40;i++){if(stopRequested)throw Error('Stopped by user');const tab=await chrome.tabs.get(id);if(tab.status==='complete')return tab;await delay(500)}throw Error('Application page did not finish loading');}
async function execute(id,func,args=[]){const result=await chrome.scripting.executeScript({target:{tabId:id},func,args});return result[0]?.result;}
async function confirmation(id){return execute(id,()=>{const text=document.body?.innerText||'';const success=/thank you for applying|application (?:has been|was) (?:successfully )?submitted|application submitted successfully|we have received your application/i.test(text);return {success,url:location.href,excerpt:success?(text.match(/.{0,60}(?:thank you for applying|application (?:has been|was) (?:successfully )?submitted|application submitted successfully|we have received your application).{0,100}/i)||[])[0]:''};});}
async function runBatch(autoSubmit,limit){
 if(running)throw Error('A batch is already running');running=true;stopRequested=false;await status('Loading approved applications…');
 try{
  const queue=(await api('queue')).slice(0,Math.min(20,Math.max(1,Number(limit)||5)));
  let completed=0,review=0;
  for(const job of queue){
   if(stopRequested)break;
   if(!JobPilotRules.supported(job.url)){await status('Unsupported job site: '+job.company+' — open manually');review++;continue}
   if(!await chrome.permissions.contains({origins}))throw Error('Grant job-site permissions with Start batch');
   let claimed=false,submitting=false;
   try{
    const payload=await api('jobs/'+job.id+'/claim',{});claimed=true;
    await status(`Filling ${job.title} at ${job.company}…`,{completed,review});
    const tab=await chrome.tabs.create({url:job.url,active:true});
    const loaded=await waitForTab(tab.id);
    if(!JobPilotRules.sameApplication(job.url,loaded.url))throw Error('Application redirected to a different job or site; review manually');
    await delay(1500);
    await chrome.scripting.executeScript({target:{tabId:tab.id},files:['rules.js','content.js']});
    const report=await execute(tab.id,data=>globalThis.jobPilotFill(data),[payload]);
    if(stopRequested)throw Error('Stopped by user before submission');
    if(autoSubmit&&JobPilotRules.canSubmit(loaded.url,report)){
      if((await confirmation(tab.id)).success)throw Error('Page already shows a success message; verify manually');
      await delay(2000); // Allow résumé processing and dynamic validation to finish.
      if(!JobPilotRules.sameApplication(job.url,(await chrome.tabs.get(tab.id)).url))throw Error('Application destination changed; review manually');
      if(stopRequested)throw Error('Stopped before submission');
      await action(job.id,'submitting','Attempt started by approved Lever adapter');submitting=true;
      const result=await execute(tab.id,()=>globalThis.jobPilotSubmit());
      if(!result.clicked)throw Error(result.error);
      let confirmed=null;
      for(let i=0;i<12;i++){await delay(1000);try{const r=await confirmation(tab.id);if(r.success&&new URL(r.url).hostname===new URL(job.url).hostname){confirmed=r;break}}catch{}}
      if(confirmed){await action(job.id,'submitted',confirmed.excerpt+' | '+confirmed.url);completed++;submitting=false;}
      else{await action(job.id,'submission_unknown','Submit clicked, but no recognized confirmation was observed. Check the tab or confirmation email. Do not retry automatically.');review++;submitting=false;}
    }else{
      const issues=[...report.missing,...report.challenges];
      await action(job.id,'needs_review',`Filled ${report.filled} fields. ${issues.length?'Review: '+issues.join('; '):'Ready for your final review and manual submission.'}`);review++;
    }
   }catch(error){
    if(claimed){try{await action(job.id,submitting?'submission_unknown':'needs_review',String(error.message))}catch{}}
    await status('Needs review: '+error.message,{completed,review:++review});
   }
   await delay(1200);
  }
  running=false;await status(`${stopRequested?'Stopped':'Batch complete'} · ${completed} confirmed submissions · ${review} need review`,{completed,review});
 }catch(error){running=false;await status(error.message);}
}
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
 if(message.type==='save-job'){api('import',{jobs:[message.job]}).then(result=>respond(result)).catch(err=>respond({error:err.message}));return true}
 if(message.type==='stop'){stopRequested=true;respond({ok:true});return}
 if(message.type==='run'){if(running){respond({error:'A batch is already running'});return}runBatch(!!message.autoSubmit,message.limit);respond({ok:true});return}
 if(message.type==='ping'){api('queue').then(queue=>respond({ok:true,count:queue.length})).catch(err=>respond({error:err.message}));return true}
});
