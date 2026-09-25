/* Shared by the content adapter and Node's built-in test runner. */
(function(root){
  const normalize = text => String(text||'').replace(/\*/g,'').replace(/\s+/g,' ').replace(/\s*\(required\)\s*$/i,'').trim().toLowerCase();
  const aliases = {
    name:['full name','name','your name','full legal name'], email:['email','email address','your email'],
    phone:['phone','phone number','mobile phone','mobile phone number'],
    location:['current location','location','current city'],
    linkedin:['linkedin','linkedin url','linkedin profile','linkedin profile url'],
    website:['website','portfolio','portfolio url','personal website','website url']
  };
  function answer(label, profile){
    const key=normalize(label);
    for(const [q,a] of Object.entries(profile.answers||{}))if(normalize(q)===key)return a;
    for(const [field,names] of Object.entries(aliases))if(names.includes(key))return profile[field]||null;
    // Do not infer legal first/last names, authorization, demographic data, dates, or salary.
    return null;
  }
  function supported(url){try{const u=new URL(url);return !u.username&&!u.password&&!u.port&&['jobs.lever.co','jobs.eu.lever.co','boards.greenhouse.io','job-boards.greenhouse.io','jobs.ashbyhq.com'].includes(u.hostname)&&u.protocol==='https:'}catch{return false}}
  function sameApplication(expected,actual){try{const a=new URL(expected),b=new URL(actual);const path=u=>u.pathname.replace(/\/(apply|application)\/?$/,'').replace(/\/$/,'');return supported(actual)&&a.hostname===b.hostname&&path(a)===path(b)}catch{return false}}
  function canSubmit(url, report){return supported(url)&&['jobs.lever.co','jobs.eu.lever.co'].includes(new URL(url).hostname)&&report.filled>0&&report.hasResume&&report.formFound&&!report.missing.length&&!report.challenges.length&&report.submitCount===1;}
  const rules={normalize,answer,supported,sameApplication,canSubmit};root.JobPilotRules=rules;if(typeof module!=='undefined')module.exports=rules;
})(globalThis);
