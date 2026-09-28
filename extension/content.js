/* Runs only on a supported application page, after an approved job is claimed. */
// This state lives in the extension's isolated world, not the employer page.
globalThis.jobPilotPendingForm = null;
globalThis.jobPilotSnapshot = function(form){
  const fields=[...form.querySelectorAll('input,textarea,select')].filter(el=>el.type!=='hidden'&&!['submit','button','reset'].includes(el.type));
  return {fields,values:JSON.stringify(fields.map(el=>({
    name:el.name,type:el.type,required:el.required,disabled:el.disabled,
    ariaRequired:el.getAttribute('aria-required'),ariaLabel:el.getAttribute('aria-label'),labelledBy:el.getAttribute('aria-labelledby'),label:[...(el.labels||[])].map(x=>x.textContent).join(' '),
    visible:!!(el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden'),
    value:el.value,checked:el.checked,
    files:[...(el.files||[])].map(file=>[file.name,file.size,file.lastModified])
  })))};
};
globalThis.jobPilotFill = function(payload){
  globalThis.jobPilotPendingForm = null;
  const {profile,resume}=payload;
  const visible=el=>!!(el.getClientRects().length && getComputedStyle(el).visibility!=='hidden');
  const label=el=>{
    const explicit=[...(el.labels||[])].map(x=>x.textContent).join(' ').trim();
    if(explicit)return explicit;
    const labelled=(el.getAttribute('aria-labelledby')||'').split(' ').map(id=>document.getElementById(id)?.textContent||'').join(' ').trim();
    return labelled || el.getAttribute('aria-label') || el.closest('.application-question')?.querySelector('.application-label')?.textContent || el.getAttribute('placeholder') || el.name || '';
  };
  const forms=[...document.querySelectorAll('form')].filter(f=>f.querySelector('input[type=email],input[name=email],input[name="email"]'));
  const fallbacks=[...document.querySelectorAll('form.application-form,form#application_form')];
  const form=forms.length===1?forms[0]:forms.length===0&&fallbacks.length===1?fallbacks[0]:null;
  const result={filled:0,missing:[],challenges:[],hasResume:false,formFound:!!form,submitCount:0,url:location.href};
  if(!form){result.missing.push('No unique standard application form found');return result}
  if(document.querySelector('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare"],.g-recaptcha,.h-captcha,[data-sitekey]'))result.challenges.push('CAPTCHA or challenge requires review');
  if(form.querySelector('[role=combobox],[role=listbox]'))result.challenges.push('Custom dropdown requires review');
  const setValue=(el,value)=>{const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};
  const fields=[...form.querySelectorAll('input,textarea,select')].filter(el=>!el.disabled&&el.type!=='hidden'&&!['submit','button','reset'].includes(el.type));
  for(const el of fields){
    const text=label(el).replace(/\s+/g,' ').trim();
    if(el.type==='file'){
      if(/resume|résumé|cv\b/i.test(text+' '+el.name+' '+el.id)){
        if(resume){const bytes=Uint8Array.from(atob(resume.base64),c=>c.charCodeAt(0));const type=resume.name.toLowerCase().endsWith('.pdf')?'application/pdf':resume.name.toLowerCase().endsWith('.docx')?'application/vnd.openxmlformats-officedocument.wordprocessingml.document':'text/plain';const file=new File([bytes],resume.name,{type});const transfer=new DataTransfer();transfer.items.add(file);el.files=transfer.files;el.dispatchEvent(new Event('change',{bubbles:true}));result.hasResume=el.files.length===1&&el.files[0].name===resume.name&&el.files[0].size===bytes.length;if(result.hasResume)result.filled++;else result.missing.push('The form did not retain the résumé attachment');}
        else result.missing.push('Upload your original résumé in JobPilot');
      }else if(el.required&&!el.files.length)result.missing.push(text||'Required file');
      continue;
    }
    if(!visible(el))continue;
    if(['checkbox','radio','password','date','number'].includes(el.type)){
      // Numeric inputs can be filled by exact saved answers, but unchecked choices are manual.
      if(el.type==='number'){const value=JobPilotRules.answer(text,profile);if(value!==null){setValue(el,value);result.filled++}else if(el.required&&!el.value)result.missing.push(text);if(!el.checkValidity())result.missing.push(text+' (invalid number)');}
      else if((el.type==='checkbox'||el.type==='radio')&&el.required&&!el.checked)result.missing.push(text||'Required choice');
      else if(el.type==='password'||el.type==='date')result.missing.push(text||el.type);
      continue;
    }
    let value=JobPilotRules.answer(text,profile);
    if(/^(cover letter|coverletter)$/i.test(JobPilotRules.normalize(text)))value=payload.job.materials?.cover_letter||null;
    if(value!==null && value!==''){
      if(el.tagName==='SELECT'){
        const matches=[...el.options].filter(o=>JobPilotRules.normalize(o.text)===JobPilotRules.normalize(value)||o.value===value);
        if(matches.length===1){setValue(el,matches[0].value);result.filled++}else result.missing.push(text+' (no exact option)');
      }else{setValue(el,value);result.filled++}
    }else if(!el.value && (el.required || !/linkedin|website|portfolio|github|twitter|additional information|comments/i.test(text))){
      result.missing.push(text||'Unlabeled field');
    }
    if(!el.checkValidity() || el.getAttribute('aria-required')==='true'&&!el.value)result.missing.push(text+' (invalid or missing)');
  }
  for(const group of form.querySelectorAll('[role=radiogroup],[role=checkbox]'))if(visible(group))result.challenges.push('Custom choice requires review');
  const submits=[...form.querySelectorAll('button,input[type=submit]')].filter(el=>visible(el)&&!el.disabled&&/^submit application$/i.test((el.textContent||el.value||'').trim()));
  result.submitCount=submits.length;
  if(!form.checkValidity())result.missing.push('Form validation requires review');
  result.missing=[...new Set(result.missing)];result.challenges=[...new Set(result.challenges)];
  if(JobPilotRules.canSubmit(location.href,result)&&form.checkValidity()){
    globalThis.jobPilotPendingForm={form,button:submits[0],snapshot:globalThis.jobPilotSnapshot(form),url:location.href};
  }
  return result;
};

globalThis.jobPilotSubmit = function(){
  const pending=globalThis.jobPilotPendingForm;
  globalThis.jobPilotPendingForm=null; // One attempt; never send a duplicate click.
  if(!['jobs.lever.co','jobs.eu.lever.co'].includes(location.hostname))return {clicked:false,error:'Unsupported submit adapter'};
  if(!pending||!pending.form.isConnected||!JobPilotRules.sameApplication(pending.url,location.href))return {clicked:false,error:'No unchanged, complete application is ready for submission'};
  const current=globalThis.jobPilotSnapshot(pending.form);
  if(current.values!==pending.snapshot.values||current.fields.some((el,i)=>el!==pending.snapshot.fields[i]))return {clicked:false,error:'Application fields, answers, or attachment changed after autofill; review manually'};
  if(document.querySelector('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare"],.g-recaptcha,.h-captcha,[data-sitekey]')||pending.form.querySelector('[role=combobox],[role=listbox],[role=radiogroup],[role=checkbox]'))return {clicked:false,error:'New challenge or custom question requires review'};
  const matches=[...document.querySelectorAll('form button,form input[type=submit]')].filter(el=>el.getClientRects().length&&!el.disabled&&/^submit application$/i.test((el.textContent||el.value||'').trim()));
  if(matches.length!==1||matches[0]!==pending.button||matches[0].form!==pending.form||!pending.form.checkValidity())return {clicked:false,error:'Form changed or has invalid required fields'};
  matches[0].click();return {clicked:true};
};
