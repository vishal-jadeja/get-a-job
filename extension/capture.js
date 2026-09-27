/* User-triggered activeTab capture. Reads posting text, never form input values. */
async function captureCurrentPosting() {
  const [tab] = await chrome.tabs.query({active:true,currentWindow:true});
  if(!tab?.id || !tab.url?.startsWith('https://'))throw Error('Open a public HTTPS job posting first');
  const result = await chrome.scripting.executeScript({target:{tabId:tab.id},func:()=>{
    const postings=[];
    const scan=value=>{
      if(!value||typeof value!=='object')return;
      if(Array.isArray(value)){value.forEach(scan);return;}
      const type=value['@type'];
      if(type==='JobPosting'||Array.isArray(type)&&type.includes('JobPosting'))postings.push(value);
      if(value['@graph'])scan(value['@graph']);
    };
    for(const script of document.querySelectorAll('script[type="application/ld+json"]')){
      try{scan(JSON.parse(script.textContent))}catch{}
    }
    const job=postings.length===1?postings[0]:null;
    const asText=value=>typeof value==='string'?value:'';
    const locationItem=Array.isArray(job?.jobLocation)?job.jobLocation[0]:job?.jobLocation;
    const address=locationItem?.address||{};
    const description=asText(job?.description);
    const parsed=new DOMParser().parseFromString(description,'text/html');
    parsed.querySelectorAll('script,style').forEach(x=>x.remove());
    return {title:asText(job?.title)||document.querySelector('h1')?.innerText||document.title,
      company:asText(job?.hiringOrganization?.name),
      location:[address.addressLocality,address.addressRegion,address.addressCountry].filter(x=>typeof x==='string').join(', '),
      description:description?(parsed.body.textContent||'').slice(0,60000):(document.querySelector('main,article')?.innerText||'').slice(0,60000),
      url:location.href,source:'browser',posted_at:asText(job?.datePosted)};
  }});
  return result[0]?.result;
}
document.addEventListener('DOMContentLoaded',()=>{
 const section=document.createElement('section');
 section.innerHTML='<hr><h3>Save a job from this tab</h3><p class="help">Capture posting details, review them, then save to your workspace. Nothing is applied for.</p><button id="capture-job" type="button">Preview current posting</button><form id="capture-form" hidden><label>Title<input name="title" required></label><label>Company<input name="company" required></label><label>Location<input name="location"></label><label>Posting URL<input name="url" type="url" required></label><label>Description<textarea name="description" rows="5"></textarea></label><button type="submit">Save to JobPilot</button></form>';
 document.body.append(section);
 const form=document.getElementById('capture-form'),capture=document.getElementById('capture-job');
 capture.onclick=async()=>{
  capture.disabled=true;
  try{const job=await captureCurrentPosting();if(!job)throw Error('Could not read this page');for(const key of ['title','company','location','url','description'])form.elements[key].value=job[key]||'';form.hidden=false;}
  catch(err){document.getElementById('status').textContent=err.message}finally{capture.disabled=false}
 };
 form.onsubmit=async event=>{
  event.preventDefault();const button=form.querySelector('button');button.disabled=true;
  try{const job={...Object.fromEntries(new FormData(form)),source:'browser'};const result=await chrome.runtime.sendMessage({type:'save-job',job});if(result.error)throw Error(result.error);document.getElementById('status').textContent=result.added?'Job saved. Review it in Discover.':'This job is already in your workspace.';form.hidden=true;}
  catch(err){document.getElementById('status').textContent=err.message}finally{button.disabled=false}
 };
});
