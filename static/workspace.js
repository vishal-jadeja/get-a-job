/* Planning screens and job workspaces. Data is persisted through authenticated APIs. */
const work = () => state.workspace || {metadata:{},tasks:[],contacts:[],searches:[],weekly_goal:10,queue_ids:null};
const meta = id => work().metadata[id] || {favorite:false,priority:'normal',tags:[],salary:'',deadline:'',prep_notes:''};
const localDay = () => { const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const dayLabel = value => value ? new Date(value+'T12:00:00').toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}) : 'No date';
const wsButton = (label, action, cls='', extra='') => `<button type="button" class="button ${cls}" data-ws="${action}" ${extra}>${label}</button>`;
let pipelineLayout='board', plannerFilter='open', dirtyForm=false;
const taskJob = task => state.jobs.find(j=>j.id===task.job_id);
function wsDialog(title, content) {
 const dialog=$('#workspace-dialog');
 $('#workspace-content').innerHTML=`<div class="modal-heading"><h2>${e(title)}</h2><button type="button" class="icon-button close-modal" aria-label="Close">×</button></div>${content}`;
 if(!dialog.open)dialog.showModal();
}
function taskRow(task) {
 const job=taskJob(task),late=!task.done&&task.due_on&&task.due_on<localDay();
 return `<div class="task-row"><input type="checkbox" data-task-done="${task.id}" aria-label="Complete ${e(task.title)}" ${task.done?'checked':''}><div class="task-main ${task.done?'completed':''}"><button class="text-button" data-ws="edit-task" data-id="${task.id}">${e(task.title)}</button><small>${e(titleCase(task.kind))}${job?` · <button class="text-button" data-job="${job.id}">${e(job.company)}</button>`:''}</small></div><span class="due ${late?'overdue':''}">${late?'Overdue · ':''}${dayLabel(task.due_on)}${task.time?' at '+e(task.time):''}</span></div>`;
}
function todayView() {
 const w=work(),today=localDay(),tasks=w.tasks.filter(t=>!t.done).sort((a,b)=>(a.due_on||'9999').localeCompare(b.due_on||'9999'));
 const weekStart=new Date();weekStart.setHours(0,0,0,0);weekStart.setDate(weekStart.getDate()-((weekStart.getDay()+6)%7));
 const submitted=appliedJobs().filter(j=>new Date(j.submitted_at)>=weekStart).length;
 const ready=state.jobs.filter(j=>j.status==='prepared'),approved=state.jobs.filter(j=>j.status==='approved');
 const shortlist=state.jobs.filter(j=>meta(j.id).favorite&&j.status!=='archived');
 const deadlines=state.jobs.filter(j=>meta(j.id).deadline&&!j.submitted_at&&j.status!=='archived').sort((a,b)=>meta(a.id).deadline.localeCompare(meta(b.id).deadline));
 const profileChecks=[['Name and email',!!(state.profile.name&&state.profile.email)],['Career evidence',!!(state.profile.experience.length||state.profile.projects.length||state.profile.resume_text)],['Target roles',!!state.profile.roles.length],['Original résumé',!!state.profile.resume_file]];
 return heading('',`Make your next move${state.profile.name?', '+e(state.profile.name.split(' ')[0]):''}.`,'Your applications, priorities, and follow-through in one place.',wsButton('+ Add task','new-task')+button('Find jobs','discover','primary'))+
 `<div class="today-strip"><div><span class="muted">This week · since Monday</span><div class="goal-number">${submitted}<span> / ${w.weekly_goal} applications</span></div><progress max="${w.weekly_goal}" value="${submitted}" aria-label="Weekly application progress"></progress>${wsButton('Edit goal','goal','link')}</div><a href="#discover" class="today-metric"><strong>${shortlist.length}</strong><span>Shortlisted</span></a><a href="#applications" class="today-metric"><strong>${ready.length}</strong><span>Drafts to review</span></a><a href="#automation" class="today-metric"><strong>${approved.length}</strong><span>Approved to apply</span></a><a href="#planner" class="today-metric"><strong>${tasks.filter(t=>t.due_on&&t.due_on<=today).length}</strong><span>Tasks due</span></a></div>
 ${profileChecks.some(x=>!x[1])?`<section class="setup-banner"><div><h2>Set yourself up for stronger applications</h2><div class="checklist">${profileChecks.map(([label,done])=>`<span>${done?'✓':'○'} ${label}</span>`).join('')}</div></div><a href="#profile" class="button primary">Complete profile</a></section>`:''}
 <div class="grid-two"><section class="panel"><div class="panel-heading"><h2>Next on your list</h2><a href="#planner" class="button link">Open planner</a></div>${tasks.slice(0,6).map(taskRow).join('')||empty('✓','Your next steps, in one place','Add a follow-up, an application deadline, or an interview to keep momentum.',wsButton('Plan a next step','new-task'))}</section><section class="panel"><div class="panel-heading"><h2>Your priority opportunities</h2><a href="#discover" class="button link">Discover jobs</a></div>${[...shortlist.filter(j=>meta(j.id).priority==='high'),...shortlist.filter(j=>meta(j.id).priority!=='high')].slice(0,4).map(compactJob).join('')||matchedJobs().slice(0,4).map(compactJob).join('')||empty('⌕','Find your first opportunity','Connect employer boards or paste a posting to start your shortlist.',button('Add a job','import'))}</section></div>
 <div class="grid-two"><section class="panel"><div class="panel-heading"><h2>Application deadlines</h2><span class="count">${deadlines.length}</span></div>${deadlines.slice(0,5).map(j=>`<div class="deadline-row"><button class="text-button" data-job="${j.id}"><strong>${e(j.title)}</strong><small>${e(j.company)}</small></button><span class="due ${meta(j.id).deadline<today?'overdue':''}">${dayLabel(meta(j.id).deadline)}</span></div>`).join('')||'<p class="help">Add deadlines in a job’s workspace. They’ll appear here.</p>'}</section><section class="panel"><div class="panel-heading"><h2>Recent activity</h2></div>${activities(4)}</section></div>`;
}
function plannerView() {
 const tasks=work().tasks.filter(t=>plannerFilter==='all'||plannerFilter==='done'?plannerFilter==='all'||t.done:!t.done&&(plannerFilter!=='interview'||t.kind==='interview')).sort((a,b)=>(a.due_on||'9999').localeCompare(b.due_on||'9999')||a.time.localeCompare(b.time));
 return heading('','A plan you can follow.','Interviews, follow-ups, and application tasks. All dates and times use your local calendar.',wsButton('Export calendar','calendar')+wsButton('+ Add task','new-task','primary'))+
 `<div class="view-tabs" role="group" aria-label="Filter tasks">${[['open','Open tasks'],['interview','Interviews'],['done','Completed'],['all','All tasks']].map(([key,label])=>wsButton(label,'planner-filter',plannerFilter===key?'active':'',`data-value="${key}"`)).join('')}</div><section class="panel">${tasks.map(taskRow).join('')||empty('✓','Nothing in this view','Plan the next action for an application, or schedule an interview.',wsButton('Add a task','new-task'))}</section><div class="section-note">Calendar export includes open dated tasks. Import it into your calendar for notifications; JobPilot itself shows reminders while the app is open.</div>`;
}
function contactsView() {
 const contacts=work().contacts;
 return heading('','Keep the conversation going.','Recruiters, referrals, and people you want to follow up with.',wsButton('+ Add contact','new-contact','primary'))+
 (contacts.length?`<div class="contacts-grid">${contacts.map(c=>`<article class="panel contact-card"><div class="panel-heading"><div><h2>${e(c.name)}</h2><p class="muted">${e(c.company||'Independent contact')}</p></div><div class="company-icon">${e(c.name.slice(0,2).toUpperCase())}</div></div>${c.email?`<p>${e(c.email)}</p>`:''}${c.url?`<a href="${e(c.url)}" target="_blank" rel="noopener noreferrer">Open profile</a>`:''}<p class="contact-notes">${e(c.notes||'Add notes about your conversation, referral, or next step.')}</p><div class="heading-actions">${wsButton('Edit','edit-contact','',`data-id="${c.id}"`)}${wsButton('Draft outreach','outreach','',`data-id="${c.id}"`)}${wsButton('Follow up','contact-task','',`data-id="${c.id}"`)}</div></article>`).join('')}</div>`:`<section class="panel">${empty('◎','Build your network alongside your pipeline','Save contact details and conversation notes. Draft messages and schedule follow-ups from here.',wsButton('Add your first contact','new-contact'))}</section>`);
}
function recordForm(kind, id='', seed={}) {
 const record=work()[kind].find(r=>r.id===id)||seed;
 const options=`<option value="">No linked application</option>${state.jobs.map(j=>`<option value="${j.id}" ${record.job_id===j.id?'selected':''}>${e(j.company)} — ${e(j.title)}</option>`).join('')}`;
 const field=(name,label,type='text')=>`<label>${label}<input name="${name}" type="${type}" value="${e(record[name]||'')}" ${['name','title'].includes(name)?'required maxlength="500"':''}></label>`;
 const content=kind==='tasks'?`${field('title','Task title')}<div class="form-grid"><label>Type<select name="kind">${['follow_up','interview','application','other'].map(k=>`<option value="${k}" ${record.kind===k?'selected':''}>${titleCase(k)}</option>`).join('')}</select></label>${field('due_on','Date','date')}${field('time','Time (optional, local)','time')}<label>Application<select name="job_id">${options}</select></label></div>`:`<div class="form-grid">${field('name','Name')}${field('company','Company')}${field('email','Email','email')}${field('url','Profile URL','url')}</div><label>Application<select name="job_id">${options}</select></label>`;
 wsDialog((id?'Edit ':'Add ')+(kind==='tasks'?'task':'contact'),`<form id="workspace-record-form" data-kind="${kind}" data-id="${id}">${content}<label>Notes<textarea name="notes" rows="5" maxlength="12000">${e(record.notes||'')}</textarea></label><div class="form-footer">${id?wsButton('Delete','delete-record','',`data-kind="${kind}" data-id="${id}"`):'<span></span>'}<button class="button primary">Save ${kind==='tasks'?'task':'contact'}</button></div></form>`);
}
function discoveryTools() {
 const sources=[...new Set(state.jobs.map(j=>j.source||'manual'))].sort();
 return `<div class="discovery-tools"><label class="checkbox-label"><input type="checkbox" id="favorite-filter" ${filters.favorite?'checked':''}>Shortlisted only</label><select id="source-filter" aria-label="Job source"><option value="all">All sources</option>${sources.map(s=>`<option value="${e(s)}" ${filters.source===s?'selected':''}>${e(titleCase(s))}</option>`).join('')}</select><input id="tag-filter" aria-label="Filter by tag" placeholder="Filter by tag" value="${e(filters.tag||'')}"><select id="sort-filter" aria-label="Sort jobs">${[['match','Best match'],['newest','Newest first'],['priority','High priority'],['deadline','Deadline soonest'],['company','Company A–Z']].map(([key,label])=>`<option value="${key}" ${filters.sort===key?'selected':''}>${label}</option>`).join('')}</select>${wsButton('Save search','save-search')}<select id="saved-search" aria-label="Load saved search"><option value="">Saved searches (${work().searches.length})</option>${work().searches.map(s=>`<option value="${s.id}">${e(s.name)}</option>`).join('')}</select>${wsButton('Manage','manage-searches','small')}</div>`;
}
function filterWorkspaceJobs(jobs) {
 jobs=jobs.filter(j=>(!filters.favorite||meta(j.id).favorite)&&(!filters.source||filters.source==='all'||(j.source||'manual')===filters.source)&&(!filters.tag||meta(j.id).tags.some(t=>t.toLowerCase().includes(filters.tag.toLowerCase()))));
 return jobs.sort((a,b)=>{
  if(filters.sort==='newest')return b.created_at.localeCompare(a.created_at);
  if(filters.sort==='company')return a.company.localeCompare(b.company);
  if(filters.sort==='deadline')return (meta(a.id).deadline||'9999').localeCompare(meta(b.id).deadline||'9999');
  if(filters.sort==='priority'){const rank={high:0,normal:1,low:2};return rank[meta(a.id).priority]-rank[meta(b.id).priority]||b.match.score-a.match.score;}
  return b.match.score-a.match.score;
 });
}
function workspaceJobsView(application=false) {
 const jobs=filteredJobs(application),size=24;
 page=Math.min(page,Math.max(0,Math.ceil(jobs.length/size)-1));
 const visible=jobs.slice(page*size,(page+1)*size),board=application&&pipelineLayout==='board';
 const statuses=['all','discovered','prepared','approved','in_progress','submitting','needs_review','submission_unknown','submitted','interview','offer','rejected','archived'];
 const table=`<div class="panel table-scroll"><table><thead><tr><th>Select</th><th>Opportunity</th><th>Status</th><th>Match</th><th>Next deadline</th><th>Submitted</th></tr></thead><tbody>${visible.map(j=>`<tr><td><input type="checkbox" data-select="${j.id}" aria-label="Select ${e(j.title)} at ${e(j.company)}" ${selected.has(j.id)?'checked':''}></td><td><button class="text-button" data-job="${j.id}"><strong>${e(j.title)}</strong></button><br><span class="muted">${e(j.company)} · ${e(j.location)}</span></td><td>${badge(j.status)}</td><td>${score(j)}</td><td>${meta(j.id).deadline?dayLabel(meta(j.id).deadline):'—'}</td><td>${date(j.submitted_at)}</td></tr>`).join('')}</tbody></table></div>`;
 return heading('',application?'Your application pipeline.':'Find work worth pursuing.',application?'Review drafts, manage your queue, and follow each opportunity through.':'Search, shortlist, and compare opportunities against your career evidence.',button('+ Add job','import')+(application?button('Export CSV','csv'):wsButton('Search the web','web-search')+button('Find jobs','discover','primary')))+
 (application?queuePanel()+`<div class="view-tabs" role="group" aria-label="Pipeline view">${wsButton('Board','layout',board?'active':'','data-value="board"')}${wsButton('List','layout',!board?'active':'','data-value="list"')}</div>`:'')+
 `<div class="toolbar"><input id="job-search" type="search" aria-label="Search jobs" placeholder="Search role, company, or location" value="${e(filters.query)}"><select id="status-filter" aria-label="Application status">${statuses.map(s=>`<option value="${s}" ${filters.status===s?'selected':''}>${s==='all'?'All statuses':titleCase(s)}</option>`).join('')}</select>${!application?`<label class="checkbox-label"><input type="checkbox" id="eligible-filter" ${filters.eligible?'checked':''}>Matches only</label>`:''}</div>${discoveryTools()}
 <div class="bulk-bar"><label class="checkbox-label"><input type="checkbox" id="select-page">Select page</label><span class="selected-count">${selected.size} selected · ${jobs.length} opportunities</span>${button('Prepare','batch-prepare','small')}${button('Approve','batch-approve','small')}${wsButton('Download materials','batch-download','small')}${wsButton('Compare','compare','small')}${button('Archive','batch-archive','small')}${filters.status==='archived'?button('Restore','batch-restore','small'):''}</div>
 ${jobs.length?(board?pipelineBoard(visible):application?table:`<div class="job-grid">${visible.map(j=>jobCard(j).replace('</article>',jobExtras(j)+'</article>')).join('')}</div>`):`<section class="panel">${empty('⌕','No opportunities in this view','Broaden your filters, add a job, or run discovery. Prepare a shortlisted job to bring it into your application pipeline.',button('Add a job','import'))}</section>`}
 <div class="pagination"><span>Page ${page+1} of ${Math.max(1,Math.ceil(jobs.length/size))} · ${jobs.length} results</span><div class="heading-actions"><button class="button small" data-action="prev" ${page===0?'disabled':''}>Previous</button><button class="button small" data-action="next" ${(page+1)*size>=jobs.length?'disabled':''}>Next</button></div></div><p class="help">Match scores describe recognized evidence, not hiring odds. Review each application before approving it. Jobs with uncertain submission outcomes stay out of the queue.</p>`;
}
function jobExtras(job) {
 const m=meta(job.id);
 return `<div class="job-extras">${wsButton(m.favorite?'★ Shortlisted':'☆ Shortlist','favorite','small',`data-id="${job.id}" aria-pressed="${!!m.favorite}"`)}${m.priority==='high'?'<span class="priority-label">High priority</span>':''}${m.deadline?`<span class="help">Due ${dayLabel(m.deadline)}</span>`:''}${m.tags.map(t=>`<span class="chip">${e(t)}</span>`).join('')}</div>`;
}
function pipelineBoard(jobs) {
 const groups=[['Drafts',['prepared']],['Ready',['approved']],['In progress',['in_progress','submitting']],['Review needed',['needs_review','submission_unknown']],['Applied',['submitted']],['Interviews',['interview']],['Offers',['offer']],['Closed',['rejected','archived']]];
 return `<div class="pipeline-board">${groups.map(([label,statuses])=>{const list=jobs.filter(j=>statuses.includes(j.status));return `<section class="pipeline-column"><div class="pipeline-title"><h2>${label}</h2><span class="count">${list.length}</span></div>${list.map(j=>`<article class="pipeline-card"><div class="pipeline-card-top"><span class="muted">${e(j.company)}</span><input type="checkbox" data-select="${j.id}" aria-label="Select ${e(j.title)}" ${selected.has(j.id)?'checked':''}></div><button class="text-button" data-job="${j.id}"><strong>${e(j.title)}</strong></button><small>${e(j.location)}</small>${badge(j.status)}<div class="pipeline-next">${work().tasks.filter(t=>!t.done&&t.job_id===j.id).length} open tasks · ${j.match.score}% match</div></article>`).join('')||'<p class="help column-empty">No applications here yet.</p>'}</section>`}).join('')}</div>`;
}
function queuePanel() {
 const ids=work().queue_ids,approved=state.jobs.filter(j=>j.status==='approved'),queue=ids===null?approved:ids.map(id=>approved.find(j=>j.id===id)).filter(Boolean);
 return `<section class="panel queue-panel"><div><h2>Application queue <span class="count">${queue.length}</span></h2><p class="help">${ids===null?'All approved applications are available to the helper.':'The helper will process only this selected queue, in order.'} Review every draft before approving.</p>${queue.length?`<p class="queue-summary">${queue.slice(0,5).map(j=>e(j.company)).join(', ')}${queue.length>5?' and '+(queue.length-5)+' more':''}</p>`:''}</div><div class="heading-actions">${wsButton('Queue selected','queue','primary')}${wsButton('Clear queue','clear-queue')}<a class="button" href="#automation">Open helper setup</a></div></section>`;
}
function applicationResumeSelector(job) {
 return `<section class="panel application-resume"><form id="job-resume-form" data-id="${job.id}"><h3>Résumé for this application</h3><label>Select from Résumé library<select name="resume_id" ${job.submitted_at||['in_progress','submitting','submission_unknown'].includes(job.status)?'disabled':''}><option value="" ${!job.resume_asset?'selected':''}>Profile default: ${e(state.profile.resume_file?.name||'No file uploaded')}</option>${(work().resumes||[]).map(r=>`<option value="${r.id}" ${job.resume_asset?.id===r.id?'selected':''}>${e(r.name)}</option>`).join('')}</select></label>${!job.submitted_at&&!['in_progress','submitting','submission_unknown'].includes(job.status)?'<button class="button primary">Use selected résumé</button>':''}<p class="help">Current attachment: <strong>${e(job.resume_asset?.name||state.profile.resume_file?.name||'No résumé selected')}</strong></p><p class="help">Add files under Career profile → Résumé library. Changing the attachment clears prepared materials and approval; prepare and review again before applying.</p></form></section>`;
}
function workspaceDetail(job) {
 const m=meta(job.id),tasks=work().tasks.filter(t=>t.job_id===job.id),canEdit=['prepared','approved','needs_review'].includes(job.status)&&job.materials;
 return `<section class="job-workspace"><div class="panel-heading"><h3>Your workspace</h3>${wsButton(m.favorite?'★ Shortlisted':'☆ Shortlist','favorite','',`data-id="${job.id}" aria-pressed="${!!m.favorite}"`)}</div>
 <form id="job-variant-form" data-id="${job.id}"><label>Résumé tailoring profile<select name="variant_id" ${job.submitted_at||['in_progress','submitting','submission_unknown','archived'].includes(job.status)?'disabled':''}><option value="" ${!job.resume_variant_id?'selected':''}>Automatically match the role</option><option value="general" ${job.resume_variant_id==='general'?'selected':''}>General career profile</option>${(work().resume_variants||[]).map(v=>`<option value="${v.id}" ${job.resume_variant_id===v.id?'selected':''}>${e(v.name)}</option>`).join('')}</select></label>${!job.submitted_at&&!['in_progress','submitting','submission_unknown','archived'].includes(job.status)?'<button class="button small">Use tailoring profile</button>':''}${job.materials?.tailoring?`<p class="help">Prepared with <strong>${e(job.materials.tailoring.variant_name)}</strong> for ${e(job.materials.tailoring.target_role)}. ${job.materials.tailoring.experience_count} experience bullets and ${job.materials.tailoring.project_count} projects, ranked against this posting.</p>`:'<p class="help">Prepare materials to create a job-specific résumé. Role profiles are managed in Career profile.</p>'}</form>

 <form id="job-metadata-form" data-id="${job.id}"><div class="form-grid"><label>Priority<select name="priority">${['low','normal','high'].map(v=>`<option ${m.priority===v?'selected':''}>${v}</option>`).join('')}</select></label><label>Application deadline<input type="date" name="deadline" value="${e(m.deadline)}"></label><label>Compensation / salary range<input name="salary" maxlength="200" placeholder="e.g. ₹25–35 LPA · advertised" value="${e(m.salary)}"></label><label>Tags (comma separated)<input name="tags" value="${e(m.tags.join(', '))}" placeholder="Dream company, Remote, Referral"></label></div><button class="button">Save tracking details</button></form>
 <div class="panel-heading workspace-section"><h3>Next steps</h3>${wsButton('+ Add task','job-task','small',`data-id="${job.id}"`)}</div>${tasks.map(taskRow).join('')||'<p class="help">Set a follow-up or schedule an interview for this application.</p>'}
 <div class="heading-actions workspace-section">${canEdit?wsButton('Edit résumé & cover letter','edit-materials','primary',`data-id="${job.id}"`):''}${job.materials?wsButton('Draft history','versions','',`data-id="${job.id}"`):''}${wsButton('Interview prep','prep','',`data-id="${job.id}"`)}${job.status==='archived'?wsButton('Restore application','restore','',`data-id="${job.id}"`):(!['in_progress','submitting','submission_unknown'].includes(job.status)?wsButton('Archive','archive','',`data-id="${job.id}"`):'')}</div></section>`;
}
async function editMaterials(jid, draft=null) {
 const job=await api('jobs/'+jid),material=draft||job.materials;
 wsDialog('Edit application materials',`<p class="help">${e(job.title)} at ${e(job.company)}. Saving clears approval and records a new revision. Your original uploaded attachment stays unchanged.</p><form id="materials-form" data-id="${jid}"><label>Résumé draft<textarea name="resume" rows="16" required maxlength="60000">${e(material.resume)}</textarea></label><label>Cover letter<textarea name="cover_letter" rows="10" required maxlength="30000">${e(material.cover_letter)}</textarea></label><div class="form-footer"><span class="help">Use only experience and claims you can support.</span><button class="button primary">Save draft revision</button></div></form>`);
}
async function interviewPrep(jid) {
 const job=await api('jobs/'+jid),m=meta(jid);
 wsDialog('Prepare for your interview',`<p class="muted">${e(job.title)} at ${e(job.company)}</p><div class="prep-grid"><section><h3>Prepare your evidence</h3><ul class="detail-list">${job.match.covered_skills.slice(0,6).map(skill=>`<li>Describe a specific time you used ${e(skill)}. What did you do, and what changed?</li>`).join('')||'<li>Which project best demonstrates your fit for this role?</li>'}<li>Walk through a challenge using situation, task, action, and result.</li><li>Why this company and this role?</li></ul><h3>Questions to ask</h3><ul class="detail-list"><li>What would success look like in the first 90 days?</li><li>What are the team’s biggest challenges?</li><li>How is performance and growth supported?</li><li>What are the next steps and timeline?</li></ul></section><section><h3>Gaps to discuss honestly</h3><div class="chips">${job.match.missing_skills.map(s=>`<span class="chip missing">${e(s)}</span>`).join('')||'<p>No recognized skill gaps.</p>'}</div><p class="help">These are preparation prompts based on your saved profile, not predictions of interview questions.</p>${wsButton('Schedule interview','schedule-interview','',`data-id="${jid}"`)}</section></div><form id="prep-form" data-id="${jid}"><label>Your stories, company research, and interview notes<textarea name="prep_notes" rows="12" maxlength="20000" placeholder="Situation → Task → Action → Result\nResearch the company\nQuestions for the interviewer">${e(m.prep_notes)}</textarea></label><button class="button primary">Save preparation notes</button></form>`);
}
async function workspaceAction(target) {
 if(await intelligenceAction(target))return;
 if(await networkingAction(target))return;
 const name=target.dataset.ws,id=target.dataset.id;
 if(name==='new-variant'||name==='edit-variant')return variantForm(id||'');
 if(name==='latex')return download('jobs/'+id+'/resume.tex','resume-'+id+'.tex');
 if(name==='pdf'){toast('Compiling your résumé PDF. The first run may download LaTeX packages.');await download('jobs/'+id+'/resume.pdf','resume-'+id+'.pdf');await refresh(false);if($('#detail-dialog').open)await detail(id);toast('Résumé PDF downloaded');return;}
 if(name==='use-pdf'){toast('Preparing the tailored PDF attachment…');await api('jobs/'+id+'/use-generated-pdf',{});await refresh();await detail(id);toast('Tailored PDF selected. Review and approve the application.');return;}
 if(name==='batch-pdfs'){
  if(!selected.size||selected.size>20)throw Error('Select 1–20 prepared applications');let completed=0;const errors=[];
  for(const jid of [...selected]){toast(`Generating PDF ${completed+errors.length+1} of ${selected.size}…`);try{await api('jobs/'+jid+'/generate-pdf',{});completed++;}catch(err){errors.push(err.message);}}
  await refresh();toast(`${completed} PDFs generated${errors.length?' · '+errors.length+' failed: '+errors[0]:'. Download materials to get the complete ZIP.'}`,!!errors.length);return;
 }
 if(name==='web-search')return wsDialog('Search job postings with Firecrawl',`<form id="web-search-form"><label>Search query<input name="query" value="${e([state.profile.roles[0]||'',state.profile.locations[0]||'','jobs'].join(' ').trim())}" required minlength="2" maxlength="500" placeholder="Python engineer India site:jobs.lever.co"></label><p class="help">Sends this query to Firecrawl. Returns up to 10 web results; inspect a result before importing. Account credits or guest limits apply.</p><button class="button primary">Search web</button></form><div id="web-results"></div>`);
 if(name==='extract-result'){const url=target.dataset.url;$('#workspace-dialog').close();$('#import-dialog').showModal();$('#import-form [name="url"]').value=url;return extractPosting();}
 if(name==='extract-url')return extractPosting();
 if(name==='new-task')return recordForm('tasks');
 if(name==='new-contact')return recordForm('contacts');
 if(name==='edit-task')return recordForm('tasks',id);
 if(name==='edit-contact')return recordForm('contacts',id);
 if(name==='job-task'||name==='schedule-interview')return recordForm('tasks','',{job_id:id,kind:name==='schedule-interview'?'interview':'follow_up'});
 if(name==='contact-task'){const c=work().contacts.find(x=>x.id===id);return recordForm('tasks','',{title:'Follow up with '+c.name,job_id:c.job_id,notes:c.company});}
 if(name==='planner-filter'){plannerFilter=target.dataset.value;render();return;}
 if(name==='layout'){pipelineLayout=target.dataset.value;render();return;}
 if(name==='calendar')return download('calendar.ics','jobpilot-planner.ics');
 if(name==='backup')return download('backup.zip','jobpilot-backup.zip');
 if(name==='export-json')return download('export','jobpilot-export.json');
 if(name==='restore-workspace'){
  const result=await api('backup/restore',{restore_id:pendingRestoreId,confirm:true});
  pendingRestoreId=null;location.reload();return;
 }
 if(name==='goal')return wsDialog('Set your weekly goal',`<form id="goal-form"><label>Confirmed applications per week<input type="number" min="1" max="500" name="goal" value="${work().weekly_goal}" required></label><p class="help">Choose a sustainable target. Only confirmed submissions count.</p><button class="button primary">Save goal</button></form>`);
 if(name==='favorite'){await api('workspace/metadata',{job_id:id,favorite:!meta(id).favorite});await refresh(false);render();if($('#detail-dialog').open)await detail(id);return;}
 if(name==='save-search')return wsDialog('Save this search',`<form id="search-form"><label>Search name<input name="name" required maxlength="500" placeholder="e.g. Remote Python roles"></label><p class="help">Saves your current search, filters, shortlist setting, and sort order.</p><button class="button primary">Save search</button></form>`);
 if(name==='manage-searches')return wsDialog('Saved searches',work().searches.map(s=>`<div class="deadline-row"><span>${e(s.name)}</span>${wsButton('Delete','delete-record','small',`data-kind="searches" data-id="${s.id}"`)}</div>`).join('')||'<p>No searches saved yet.</p>');
 if(name==='delete-record'){
  const record=work()[target.dataset.kind].find(r=>r.id===id);await api('workspace/remove',{kind:target.dataset.kind,id});$('#workspace-dialog').close();await refresh();
  wsDialog('Removed',`<p>${e(record.title||record.name)} was removed.</p>${wsButton('Undo','undo-record','primary')}`);$('#workspace-dialog').undoRecord={kind:target.dataset.kind,record};return;
 }
 if(name==='undo-record'){const item=$('#workspace-dialog').undoRecord;const record={...item.record};delete record.id;await api('workspace/'+item.kind,record);$('#workspace-dialog').close();await refresh();toast('Restored');return;}
 if(name==='edit-materials')return editMaterials(id);
 if(name==='prep')return interviewPrep(id);
 if(name==='versions'){
  const versions=await api('jobs/'+id+'/versions');wsDialog('Draft history',versions.length?versions.map(v=>`<details><summary>Revision ${v.id} · ${e(new Date(v.created_at).toLocaleString())}</summary><h3>Résumé</h3><pre class="preview">${e(v.resume)}</pre><h3>Cover letter</h3><pre class="preview">${e(v.cover_letter)}</pre></details>`).join(''):'<p>No edits yet. Editing materials records the original draft and each saved revision.</p>');return;
 }
 if(name==='archive'||name==='restore'){await api('jobs/'+id+'/action',{action:name});await refresh();await detail(id);toast(name==='archive'?'Archived. Use Restore application to bring it back.':'Application restored');return;}
 if(name==='queue'||name==='clear-queue'){
  if(name==='queue'&&!selected.size)throw Error('Select approved applications first');await api('application-queue',{ids:name==='queue'?[...selected]:[]});await refresh();toast(name==='queue'?'Application queue saved. Start the batch from the browser helper.':'Application queue cleared');return;
 }
 if(name==='batch-download'){
  if(!selected.size)throw Error('Select prepared applications first');return download('bundles','application-materials.zip',{ids:[...selected]});
 }
 if(name==='compare'){
  const jobs=state.jobs.filter(j=>selected.has(j.id));if(jobs.length<2||jobs.length>4)throw Error('Select 2–4 jobs to compare');
  const rows=[['Company',j=>e(j.company)],['Location',j=>e(j.location||'Not listed')],['Match',j=>score(j)],['Skill gaps',j=>e(j.match.missing_skills.join(', ')||'No recognized gaps')],['Compensation',j=>e(meta(j.id).salary||'Not recorded')],['Deadline',j=>dayLabel(meta(j.id).deadline)],['Priority',j=>e(titleCase(meta(j.id).priority))],['Status',j=>badge(j.status)],['Review',j=>`<button class="button" data-job="${j.id}">Open workspace</button>`]];
  wsDialog('Compare opportunities',`<div class="table-scroll"><table class="comparison"><thead><tr><th>Decision factor</th>${jobs.map(j=>`<th>${e(j.title)}</th>`).join('')}</tr></thead><tbody>${rows.map(([label,value])=>`<tr><th>${label}</th>${jobs.map(j=>`<td>${value(j)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);return;
 }
 if(name==='outreach'){
  const c=work().contacts.find(x=>x.id===id),job=state.jobs.find(j=>j.id===c.job_id);
  if(job)return networkingAction({dataset:{ws:'network-draft',id:job.id,contact:c.id}});
  const message=`Hi ${c.name},\n\n${job?`I'm interested in the ${job.title} role at ${job.company}.`:`I'd like to learn more about opportunities${c.company?' at '+c.company:''}.`} ${state.profile.headline?`My background: ${state.profile.headline}.`:''}\n\nWould you be open to a brief conversation about the team and the hiring process?\n\nThank you,\n${state.profile.name}`;
  wsDialog('Draft outreach',`<p class="help">Review and personalize this draft before sending it in your email or messaging app.</p><label>Message<textarea id="outreach-draft" rows="13">${e(message)}</textarea></label>${wsButton('Copy draft','copy-outreach','primary')}`);return;
 }
 if(name==='copy-outreach'){await navigator.clipboard.writeText($('#outreach-draft').value);toast('Draft copied');}
}
async function workspaceSubmit(form, fd) {
 if(await intelligenceSubmit(form,fd))return true;
 const data=Object.fromEntries(fd),id=form.dataset.id;
 if(form.id==='networking-settings'){await api('networking/settings',{automatic:fd.has('automatic'),max_per_run:Number(data.max_per_run)});dirtyForm=false;await refresh();toast('Networking settings saved');return true;}
 if(form.id==='firecrawl-form'){await api('integrations/firecrawl',data);form.reset();dirtyForm=false;await refresh();toast('Firecrawl configuration updated for this server session');return true;}
 if(form.id==='web-search-form'){
  const results=$('#web-results');results.innerHTML='<p role="status">Searching public job postings…</p>';
  try{const response=await api('web/search',data);results.innerHTML=response.results.map(r=>`<article class="web-result"><h3><a href="${e(r.url)}" target="_blank" rel="noopener noreferrer">${e(r.title)}</a></h3><p class="help">${e(r.description)}</p>${wsButton('Preview import','extract-result','small',`data-url="${e(r.url)}"`)}</article>`).join('')||'<p>No results. Try another role, location, or employer.</p>';dirtyForm=false;}catch(err){results.innerHTML='';throw err}return true;
 }
 if(form.id==='workspace-record-form')await api('workspace/'+form.dataset.kind,{...data,...(id?{id}:{})});
 else if(form.id==='goal-form')await api('workspace/goal',data);
 else if(form.id==='search-form')await api('workspace/searches',{name:data.name,filters});
 else if(form.id==='variant-form'){for(const key of ['skills','experience','projects'])data[key]=fd.getAll(key);await api('workspace/resume-variants',{...data,...(id?{id}:{})});}
 else if(form.id==='job-variant-form'){await api('jobs/'+id+'/resume-variant',data);dirtyForm=false;await refresh();await detail(id);toast('Tailoring profile saved. Prepare fresh materials for this job.');return true;}
 else if(form.id==='job-resume-form'){await api('jobs/'+id+'/resume',data);dirtyForm=false;await refresh();await detail(id);toast('Attachment saved. Prepare and review materials before approving.');return true;}
 else if(form.id==='job-metadata-form'){await api('workspace/metadata',{job_id:id,...data,tags:commas(data.tags)});await refresh(false);dirtyForm=false;toast('Tracking details saved');return true;}
 else if(form.id==='materials-form')await api('jobs/'+id+'/materials',data);
 else if(form.id==='prep-form')await api('workspace/metadata',{job_id:id,...data});
 else return false;
 $('#workspace-dialog').close();dirtyForm=false;await refresh();if($('#detail-dialog').open)await detail(detailId);toast('Saved');return true;
}
document.addEventListener('click',async event=>{
 const target=event.target.closest('[data-ws]');if(!target)return;event.preventDefault();target.disabled=true;
 try{await workspaceAction(target)}catch(err){toast(err.message,true)}finally{target.disabled=false}
});
async function extractPosting() {
 const form=$('#import-form'),url=$('[name="url"]',form).value.trim(),feedback=$('#import-feedback');
 if(!url)throw Error('Paste the job posting URL first');
 if(dirtyForm&&(['title','company','description'].some(k=>$(`[name="${k}"]`,form).value))&&!confirm('Replace the current import fields with extracted content?'))return;
 feedback.textContent='Reading the job posting with Firecrawl…';
 const extractButton=$('[data-ws="extract-url"]');extractButton.disabled=true;
 try{
  const result=await api('web/extract',{url});
  for(const key of ['title','company','location','url','description'])$(`[name="${key}"]`,form).value=result.job[key]||'';
  form.dataset.source='firecrawl';dirtyForm=true;feedback.textContent='Posting extracted. Check the title, company, location, and requirements before saving.';
 }catch(err){feedback.textContent=err.message;throw err}finally{extractButton.disabled=false;}
}
function firecrawlSettings() {
 return `<section class="panel"><div class="panel-heading"><h2>Firecrawl web discovery</h2><span class="count">${state.integrations?.firecrawl.configured?'Key configured':'Guest access'}</span></div><p class="help">Search the web or extract a posting from its URL. Only the URL or search query goes to Firecrawl; your résumé and career profile are not sent. Calls use your account credits or guest limits.</p><form id="firecrawl-form"><label>API key (optional)<input type="password" name="key" autocomplete="off" placeholder="Enter a key, or leave blank to use guest access"></label><p class="help">Keys entered here stay in server memory until restart. To persist configuration, set FIRECRAWL_API_KEY in the server environment. Keys are excluded from exports.</p><button class="button">Update connection</button></form></section>`;
}
document.addEventListener('change',async event=>{
 const t=event.target;
 try{
  if(t.id==='workspace-backup-upload'&&t.files[0]){
   const file=t.files[0];if(file.size>64*1024*1024)throw Error('Choose a backup ZIP smaller than 64 MB');
   t.disabled=true;toast('Checking backup…');
   try {
    const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file)});
    const preview=await api('backup/preview',{base64:encoded});pendingRestoreId=preview.restore_id;
    wsDialog('Review workspace import',`<p><strong>${e(preview.name||'Unnamed profile')}</strong> · ${preview.jobs} jobs · ${preview.resumes} library résumés</p><p class="help">Default résumé: ${e(preview.default_resume||'None')}</p><p>This will replace the workspace shown on this computer. Your current data is preserved in a separate workspace and a backup ZIP. The two workspaces are not merged.</p><p class="help">Reconnect Gmail and the browser helper after importing. Scheduled discovery and email sync will be off; pending approvals must be reviewed again. Submitted application history is preserved.</p>${wsButton('Restore this workspace','restore-workspace','primary')}`);
   } finally {t.disabled=false;t.value='';}
   return;
  }
  if(t.id==='resume-library-upload'&&t.files[0]){
   const file=t.files[0];if(file.size>5*1024*1024)throw Error('Choose a file smaller than 5 MB');
   const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file)});
   await api('workspace/resumes',{name:file.name,base64:encoded});await refresh(false);$('#resume-library-list').innerHTML=resumeLibraryList();t.value='';toast('Résumé variant saved. Choose it in an application workspace.');return;
  }
  if(t.dataset.taskDone){await api('workspace/tasks',{id:t.dataset.taskDone,done:t.checked});await refresh();if($('#detail-dialog').open)await detail(detailId);return;}
  const filter={ 'favorite-filter':'favorite','source-filter':'source','sort-filter':'sort','tag-filter':'tag'}[t.id];
  if(filter){filters[filter]=t.type==='checkbox'?t.checked:t.value;page=0;render();return;}
  if(t.id==='saved-search'&&t.value){filters={query:'',status:'all',eligible:true,...work().searches.find(s=>s.id===t.value).filters};page=0;render();}
 }catch(err){if(t.type==='checkbox')t.checked=!t.checked;toast(err.message,true)}
});
document.addEventListener('input',event=>{if(event.target.closest('form'))dirtyForm=true;});
document.addEventListener('click',event=>{
 const link=event.target.closest('a[href^="#"]');
 if(link&&link.getAttribute('href')!=='#'&&dirtyForm&&!confirm('Discard unsaved edits and switch pages?')){event.preventDefault();event.stopImmediatePropagation();}
},true);
document.addEventListener('cancel',event=>{
 if(dirtyForm&&!confirm('Discard unsaved edits?'))event.preventDefault();else dirtyForm=false;
},true);
window.addEventListener('beforeunload',event=>{if(dirtyForm){event.preventDefault();event.returnValue='';}});
function resumeLibraryList(){return (work().resumes||[]).map(r=>`<p class="help"><strong>${e(r.name)}</strong><br>Added ${date(r.created_at)}</p>`).join('')||'<p class="help">No variants yet.</p>';}
function resumeLibrary(){return `<section class="panel"><h2>Résumé library</h2><p class="help">Keep versions for different roles and choose an attachment per application. Files stay local until you run the helper.</p><div id="resume-library-list">${resumeLibraryList()}</div><label>Add a résumé variant<input id="resume-library-upload" type="file" accept=".pdf,.docx,.txt"></label></section>`;}
function roleResumePanel(){return `<section class="panel"><h2>Role-focused résumés</h2><p class="help">Choose the evidence to emphasize for each role family. Each job’s requirements determine the order of skills, bullets, and projects in its generated résumé.</p>${(work().resume_variants||[]).map(v=>`<div class="deadline-row"><div><strong>${e(v.name)}</strong><small>${e(v.target_roles)}</small></div>${wsButton('Edit','edit-variant','small',`data-id="${v.id}"`)}</div>`).join('')}${wsButton('+ Create role résumé','new-variant','primary')}</section>`;}
function variantForm(id){
 const v=(work().resume_variants||[]).find(v=>v.id===id)||{name:'',target_roles:'',headline:'',max_skills:20,max_experience:8,max_projects:4};
 const fields=[['name','Profile name','e.g. Backend engineering'],['target_roles','Target job titles (comma separated)','Backend Engineer, Python Developer'],['headline','Résumé headline','Your truthful professional headline']].map(([key,label,placeholder])=>`<label>${label}<input name="${key}" value="${e(v[key])}" placeholder="${placeholder}" ${key!=='headline'?'required':''} maxlength="500"></label>`).join('');
 const evidence=['skills','experience','projects'].map(key=>`<details open><summary>${titleCase(key)} · select evidence to include</summary><p class="help">If none are checked, use all saved ${key}.</p><div class="evidence-choices">${state.profile[key].map(value=>`<label class="checkbox-label"><input type="checkbox" name="${key}" value="${e(value)}" ${v[key]?.includes(value)?'checked':''}><span>${e(value)}</span></label>`).join('')||'<p>Add evidence to your career profile first.</p>'}</div></details>`).join('');
 wsDialog(id?'Edit role résumé':'Create a role-focused résumé',`<form id="variant-form" data-id="${id}">${fields}<p class="help">Use only your real experience. Matching a job never adds a skill you have not saved. Save career-profile edits before creating a role résumé.</p>${evidence}<div class="form-grid">${[['max_skills','Maximum skills'],['max_experience','Maximum experience bullets'],['max_projects','Maximum projects']].map(([key,label])=>`<label>${label}<input name="${key}" type="number" min="1" max="50" value="${v[key]}" required></label>`).join('')}</div><p class="help">Saving changes invalidates pending drafts and approvals. Submitted applications retain their history.</p><button class="button primary">Save role résumé</button></form>`);
}
document.addEventListener('DOMContentLoaded',()=>{
 $('#import-form .form-grid').insertAdjacentHTML('beforebegin','<p class="help">Paste a public job posting URL below, then preview an import with Firecrawl. You can also enter details manually.</p>');
 $('#import-form .form-grid').insertAdjacentHTML('afterend',wsButton('Import from URL with Firecrawl','extract-url')+'<p id="import-feedback" class="help" role="status"></p>');
});

let pendingRestoreId=null;
function transferPanel(){return `<section class="panel"><h2>Export and import your workspace</h2><p class="help">Move your profile, jobs, résumé library, application history, drafts, tasks, contacts, and email review history to another computer.</p>${wsButton('Export full backup ZIP','backup','primary')}<label>Import a JobPilot backup ZIP<input id="workspace-backup-upload" type="file" accept=".zip,application/zip"></label><p class="help">Install and run the same JobPilot version on the other computer, then import the ZIP here. You’ll review the backup before restoring it. This transfers a snapshot; computers do not sync automatically. Backups contain personal data but exclude Gmail credentials and the browser connection token.</p><details><summary>Other exports</summary><p class="help">JSON is for inspecting data; use the full ZIP to move your workspace.</p>${wsButton('Export JSON','export-json')}</details></section>`;}
