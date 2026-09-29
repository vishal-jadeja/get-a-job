/* Public company research, professional contacts, and YC engineering discovery. */
let ycFilter = '', ycRecent = false, researchPoll;
function networkingPanel(job) {
 return `<section class="panel networking-panel"><div class="panel-heading"><div><h2>People behind this opportunity</h2><p class="help">Public company links, relevant peers, and hiring contacts. Verify current employment before reaching out.</p></div>${wsButton('Find / refresh contacts','network-research','primary',`data-id="${job.id}"`)}</div>${job.description_partial?`<div class="section-note">This YC listing contains a summary. ${wsButton('Load complete posting','yc-details','small',`data-id="${job.id}"`)} before assessing your fit or preparing an application.</div>`:''}<div id="job-networking" data-id="${job.id}"><p class="help">Loading saved research…</p></div></section>`;
}
async function loadNetworking(id) {
 const data=await api('jobs/'+id+'/networking'), box=$('#job-networking');
 if(!box||box.dataset.id!==id)return;
 const company=data.companies||[],people=data.people||[];
 box.innerHTML=`<div class="network-summary"><span class="status">${e(titleCase(data.status))}${data.stale?' · refresh recommended':''}</span><span class="help">${data.checked_at?'Checked '+e(new Date(data.checked_at).toLocaleString()):'No public lookup yet'}${data.previous_results_at?' · Showing earlier results from '+e(new Date(data.previous_results_at).toLocaleDateString()):''}</span></div>
 ${data.errors?.length?`<div class="section-note">${data.errors.map(e).join('<br>')}<br>You can use the search links below or add a contact manually.</div>`:''}
 <h3>Company LinkedIn</h3>${company.map(c=>`<article class="network-candidate"><a href="${e(c.url)}" target="_blank" rel="noopener noreferrer"><strong>${e(c.name)}</strong> ↗</a><p class="help">${e(c.evidence||c.summary||'Company-linked profile')}</p><small>${c.verification==='yc_public_page'?'Linked from the public YC page':'Search-result candidate · verify company identity'}</small></article>`).join('')||'<p class="help">No verified company link saved. Open the company search or run a lookup.</p>'}
 <h3>People to consider</h3><div class="network-people">${people.map(p=>`<article class="network-candidate"><div class="panel-heading"><a href="${e(p.url)}" target="_blank" rel="noopener noreferrer"><strong>${e(p.name)}</strong> ↗</a><span class="status">${e(titleCase(p.kind))}</span></div><p>${e(p.role)}</p><p class="help">${e(p.evidence)}</p><p class="help">${p.verification==='yc_public_page'?'Listed on YC’s public company page':'Public search snippet; current employment unverified'} · <a href="${e(p.source_url)}" target="_blank" rel="noopener noreferrer">Source</a></p><div class="heading-actions">${wsButton('Draft personal message','network-draft','small',`data-id="${id}" data-person="${e(p.url)}"`)}${wsButton('Save contact','network-save','small',`data-id="${id}" data-person="${e(p.url)}"`)}</div></article>`).join('')||'<p class="help">No matching public contacts found yet. We never invent people or their job titles.</p>'}</div>
 <details><summary>Search manually</summary><div class="heading-actions">${Object.entries(data.search_links).map(([key,item])=>`<a class="button small" href="${e(item.url)}" target="_blank" rel="noopener noreferrer">${e(titleCase(key))} ↗</a>`).join('')}</div></details><div class="detail-actions">${wsButton('Draft job-specific introduction','network-draft','',`data-id="${id}"`)}</div><p class="help">Only public company names and job titles are sent to search. No LinkedIn login, connection requests, or messages are automated.</p>`;
}
function networkingSettings() {
 const config=state.networking?.settings||{automatic:true,max_per_run:5};
 return `<section class="panel"><h2>Automatic company & contact research</h2><p class="help">After importing jobs, or discovering suitable matches, look for company LinkedIn pages, peers, and HR/recruiting contacts. Results are cached by company and role for seven days. Search uses the configured Firecrawl service; guest limits or account credits may apply. Manual search links and outreach drafts work without it.</p><form id="networking-settings"><label class="checkbox-label"><input type="checkbox" name="automatic" ${config.automatic?'checked':''}>Find public contacts after discovery and import</label><label>Maximum company/role lookups per run<input type="number" name="max_per_run" min="1" max="20" value="${config.max_per_run}"></label><p class="help">Each lookup makes up to three public search requests. Jobs beyond the cap still get personalized drafts and manual search links; use Find contacts to research them individually.</p><button class="button primary">Save research settings</button></form><p class="help" id="network-progress">${e(state.networking?.progress?.message||'Ready')}</p></section>`;
}
function ycView() {
 const latest=state.yc?.listed_urls;
 const all=state.jobs.filter(j=>j.source==='yc'&&(!latest||latest.includes(j.url)));
 const batchYear=j=>{const m=(j.yc_batch||'').match(/^[A-Z](\d{2})$/);return m?2000+Number(m[1]):0};
 const batchOrder=j=>batchYear(j)*10+({W:1,P:2,S:3,F:4}[(j.yc_batch||'')[0]]||0);
 const activity=j=>{const m=(j.yc_activity||'').match(/^(?:about\s+)?(\d+)\s+(minute|hour|day|week|month|year)s?(?:\s+ago)?$/i);return m?Number(m[1])*({minute:1/1440,hour:1/24,day:1,week:7,month:30,year:365}[m[2].toLowerCase()]):99999};
 const jobs=all.filter(j=>(!ycRecent||(batchYear(j)>=new Date().getFullYear()-1&&batchYear(j)<=new Date().getFullYear()))&&`${j.company} ${j.title} ${j.location} ${j.yc_batch}`.toLowerCase().includes(ycFilter.toLowerCase())).sort((a,b)=>batchOrder(b)-batchOrder(a)||activity(a)-activity(b)||a.company.localeCompare(b.company));
 const groups=new Map();for(const j of jobs){if(!groups.has(j.company))groups.set(j.company,[]);groups.get(j.company).push(j)}
 const status=state.yc||{};
 return heading('YC ENGINEERING OPPORTUNITIES','Startups that are hiring.','Discover public YC engineering postings, then explore the company and people behind each role.',wsButton('Refresh YC jobs','yc-discover','primary'))+
 `<div class="stats">${stat('Companies discovered',new Set(all.map(j=>j.company)).size,'Across the imported public listings')}${stat('Engineering postings',all.length,'Deduplicated job URLs and YC IDs')}${stat('Public pages checked',status.pages||0,'Main listing + linked locations')}${stat('Last checked',status.checked_at?date(status.checked_at):'—','Open the source to confirm availability')}</div>
 <div class="section-note"><strong>How this list is ranked:</strong> newer YC batches first, then the listing’s reported activity. This is a hiring-signal sort, not a popularity ranking. Coverage is limited to YC’s public engineering pages; more jobs may require a YC account. <a href="https://www.ycombinator.com/jobs/role/software-engineer" target="_blank" rel="noopener noreferrer">YC source ↗</a></div>
 <div class="toolbar"><input id="yc-search" type="search" aria-label="Search YC companies and jobs" placeholder="Company, role, batch, or location…" value="${e(ycFilter)}"><label class="checkbox-label"><input type="checkbox" id="yc-recent" ${ycRecent?'checked':''}>Current and previous year batches only</label></div><p class="help" id="yc-progress">${e(status.message||'Run discovery to get current public engineering jobs.')}</p>${status.errors?.length?`<details><summary>${status.errors.length} source pages could not be read</summary><p class="help">${status.errors.map(e).join('<br>')}</p></details>`:''}
 ${groups.size?[...groups].map(([company,roles])=>`<section class="panel"><div class="panel-heading"><div><h2>${e(company)} <span class="count">${e(roles[0].yc_batch)}</span></h2><p class="help">${roles.length} engineering openings found · listing activity: ${e(roles[0].yc_activity||'not provided')}</p></div><a class="button small" href="${e(roles[0].company_url)}" target="_blank" rel="noopener noreferrer">YC company ↗</a></div>${roles.map(j=>`<div class="yc-job-row"><div><button class="text-button" data-job="${j.id}">${e(j.title)}</button><p class="help">${e(j.location)} · ${j.description_partial?'Summary only — load full requirements':j.match.score+'% profile match'}</p></div><div class="heading-actions">${j.description_partial?wsButton('Load full job','yc-details','small',`data-id="${j.id}"`):''}<button class="button small" data-job="${j.id}">Job & contacts</button></div></div>`).join('')}</section>`).join(''):`<section class="panel">${empty('↗','No YC postings in this view','Refresh public YC engineering jobs, or broaden the search and batch filters.')}</section>`}`;
}
function watchResearch() {
 clearTimeout(researchPoll);
 researchPoll=setTimeout(async()=>{
  try{const progress=await api('research/status');state.yc=progress.yc;if(state.networking)state.networking.progress=progress.networking;
   if($('#yc-progress'))$('#yc-progress').textContent=progress.yc.message;
   if($('#network-progress'))$('#network-progress').textContent=progress.networking.message;
   if(progress.yc.running||progress.networking.running)watchResearch();
   else{await refresh();if($('#detail-dialog').open&&detailId)await loadNetworking(detailId);toast(progress.networking.completed?progress.networking.message:progress.yc.message)}
  }catch(err){toast(err.message,true)}
 },2000);
}
async function networkingAction(target) {
 const action=target.dataset.ws,id=target.dataset.id;
 if(action==='yc-discover'){const result=await api('yc/discover',{});toast(result.started?'YC discovery started.':'A discovery run is already active.');watchResearch();return true}
 if(action==='yc-details'){toast('Loading the public job requirements…');await api('jobs/'+id+'/yc-details',{});await refresh();await detail(id);watchResearch();return true}
 if(action==='network-research'){const r=await api('jobs/'+id+'/networking',{});toast(r.started?'Looking for public company and contact links…':'Research is already running.');watchResearch();return true}
 if(action==='network-save'){await api('jobs/'+id+'/save-contact',{person_url:target.dataset.person});await refresh(false);toast('Contact saved with source notes. Verify their current role before connecting.');return true}
 if(action==='network-draft'){
  const draft=await api('jobs/'+id+'/outreach',{person_url:target.dataset.person||'',contact_id:target.dataset.contact||''});
  wsDialog('A short, personal introduction',`<p class="help">${e(draft.note)}</p>${draft.warning?`<p class="section-note">${e(draft.warning)}</p>`:''}<label>Connection note · ${draft.connection.length} characters<textarea id="network-connection" rows="4">${e(draft.connection)}</textarea></label>${wsButton('Copy connection note','network-copy','small','data-field="network-connection"')}<label>Job-specific message<textarea id="network-message" rows="6">${e(draft.message)}</textarea></label>${wsButton('Copy message','network-copy','primary','data-field="network-message"')}<details><summary>Why this draft mentions your fit</summary><p class="help">Matching saved skills: ${e(draft.skills.join(', ')||'None yet')}</p><p class="preview">${e(draft.evidence||'No matching experience bullet selected.')}</p></details><p><a href="${e(draft.job_url)}" target="_blank" rel="noopener noreferrer">Original job posting ↗</a></p>`);return true;
 }
 if(action==='network-copy'){await navigator.clipboard.writeText($('#'+target.dataset.field).value);toast('Draft copied. Review it before sending.');return true}
 return false;
}
document.addEventListener('change',event=>{if(event.target.id==='yc-recent'){ycRecent=event.target.checked;render()}});
let ycSearchTimer;
document.addEventListener('input',event=>{if(event.target.id==='yc-search'){ycFilter=event.target.value;clearTimeout(ycSearchTimer);ycSearchTimer=setTimeout(()=>{render();$('#yc-search').focus()},250)}});
