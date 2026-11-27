"use strict";
/* Synthetic reviewer prototype: walkthrough scenarios from the redesign handoff (run by tests/test_reviewer_prototype.py). */
const fs=require('fs');
const html=fs.readFileSync(process.argv[2],'utf8');
const fm=html.match(/<script id="field-map" type="application\/json">([\s\S]*?)<\/script>/)[1];
const js=html.match(/<script>\r?\n([\s\S]*?)<\/script>/)[1];
const el=()=>({innerHTML:'',textContent:'',set onclick(f){},querySelectorAll:()=>[],addEventListener(){},setAttribute(){},dataset:{}});
const app=el();
global.document={getElementById:id=>id==='field-map'?{textContent:fm}:id==='app'?app:el(),querySelectorAll:()=>[]};
global.window={addEventListener(){},scrollTo(){},scrollY:0};global.history={length:1,back(){}};
global.location={hash:'#overview'};
const exportNames='DATA,P,worthALook,groupStat,signals,baseline,coverageIssues,covGroup,renderOverview,renderProfile,renderDetail,renderWorkout,renderSources,renderPeople,renderUnavailable,route,SHARED,nightDetail,dayMinutes,daytimeHR,hm,state,NOW,FIELD_MAP';
const f=new Function(js+`\nreturn {${exportNames}};`);
const t=f();
const out=[];const ok=(c,m)=>{out.push((c?'PASS ':'FAIL ')+m);if(!c)process.exitCode=1};
const look=t.worthALook();
const show=look.map(o=>`${o.p.id} ${o.d} ${o.sig.metric} ${o.value} usual ${o.usual} ${o.lvl}/${o.state}`);
console.log('Worth a look:\n  '+show.join('\n  '));
const p03=look.find(o=>o.p.id==='p03');
ok(p03&&p03.d==='2026-11-25'&&t.hm(p03.value)==='4 h 12 min'&&t.hm(p03.usual)==='6 h 50 min','p03 night 25 Nov: 4 h 12 min vs usual 6 h 50 min');
ok(look.some(o=>o.p.id==='p09'&&o.sig.metric==='rhr'),'p09 resting HR observation');
ok(look.some(o=>o.p.id==='p12'&&o.sig.metric==='hrv'),'p12 HRV observation');
ok(look.every(o=>['p02','p03','p09','p12'].includes(o.p.id)),'no unscripted observations from noise');
ok(!look.some(o=>t.P[o.p.id].share!=='individual'),'group-only people never listed individually');
const ws=t.groupStat('WHOOP','sleep','2026-11-13');ok(ws.value===null&&ws.n===4,'WHOOP sleep 13 Nov hidden with 4 of 5');
for(const [dev,m,d] of [['Fitbit','sleep','2026-11-25'],['WHOOP','sleep','2026-11-25'],['Fitbit','steps','2026-11-24'],['Fitbit','rhr','2026-11-24'],['WHOOP','rhr','2026-11-24'],['Fitbit','dayhr','2026-11-24']]){const g=t.groupStat(dev,m,d);ok(g.value!=null&&g.n>=5,`${dev} ${m} ${d} shown with ${g.n}`)}
ok(t.groupStat('WHOOP','steps','2026-11-24').value===null,'WHOOP steps unavailable');
const p05=t.P.p05.byDay['2026-11-22'];ok(p05.sleep==null&&p05.rhr!=null&&p05.steps!=null,'p05 22 Nov: no sleep, heart rate and steps present');
ok(t.P.p07.byDay['2026-11-24'].cov.sleep==='delayed'&&t.P.p07.byDay['2026-11-23'].rhr!=null,'p07 delayed from 24 Nov');
ok(t.P.p11.byDay['2026-10-10'].cov.rhr==='preissue'&&t.P.p11.byDay['2026-10-21'].rhr!=null,'p11 before device issued until 20 Oct');
ok(t.P.p08.byDay['2026-11-13'].cov.sleep==='none','p08 unverified gap');
ok(t.P.p06.byDay['2026-11-03'].cov.hrv==='failed'&&t.P.p06.byDay['2026-11-03'].rhr!=null,'p06 HRV request failed');
ok(t.P.p02.byDay['2026-10-12'].cov.steps==='notworn','p02 not worn 12 Oct');
const n=t.nightDetail(t.P.p03,'2026-11-25');const asleep=n.hr.filter(x=>x.stage!=='awake').length;
ok(Math.abs(n.hr.length-t.P.p03.byDay['2026-11-25'].inbed)<=3,`p03 night minutes ${n.hr.length} ~ in bed ${t.P.p03.byDay['2026-11-25'].inbed}`);
const today=t.dayMinutes(t.P.p03,'2026-11-25');ok(today.length===15*60+32&&Math.abs(today.reduce((a,b)=>a+b.steps,0)-t.P.p03.byDay['2026-11-25'].steps)<=60,'p03 today partial minutes sum to partial steps');
for(const [name,fn] of [['overview',()=>t.renderOverview()],['people',()=>t.renderPeople()],['sources',()=>t.renderSources()],['p03',()=>t.renderProfile(t.P.p03)],['p09',()=>{t.state.range='all';t.renderProfile(t.P.p09);t.state.range=30}],['p03 night',()=>t.renderDetail(t.P.p03,'night','2026-11-25')],['p03 today',()=>t.renderDetail(t.P.p03,'day','2026-11-25')],['p05 missing night',()=>t.renderDetail(t.P.p05,'night','2026-11-22')],['p09 WHOOP night',()=>t.renderDetail(t.P.p09,'night','2026-11-24')],['p09 cycle',()=>t.renderDetail(t.P.p09,'day','2026-11-24')],['p07 delayed day',()=>t.renderDetail(t.P.p07,'day','2026-11-24')]]){
  try{fn();ok(app.innerHTML.length>200&&!/undefined|NaN/.test(app.innerHTML),`render ${name} (${app.innerHTML.length} chars)`)}catch(e){ok(false,`render ${name}: ${e.message}`)}}
/* Officer scope: group-only codes never appear outside group statistics. */
const GROUP_ONLY=t.DATA.filter(p=>p.share!=='individual').map(p=>p.id);
ok(GROUP_ONLY.join()==='p04,p10'&&t.SHARED.length===11,'p04 and p10 share group figures only');
ok(GROUP_ONLY.every(id=>!t.P[id].name),'group-only people carry no name in the page');
const leaks=html=>GROUP_ONLY.filter(id=>new RegExp(String.raw`\b${id}\b`).test(html));
ok(leaks('<td data-cell="p04|2026-11-20">').join()==='p04'&&leaks('<a>p041</a>').length===0,'leak check detects a group-only code');
t.renderPeople();ok(leaks(app.innerHTML).length===0&&t.SHARED.every(p=>app.innerHTML.includes('>'+p.id+'<')),'directory lists every individual code and no group-only code');
for(const tr of ['rhr','dayhr','sleep','steps']){t.state.trend=tr;t.state.covNote='';t.renderOverview();ok(leaks(app.innerHTML).length===0,`overview (${tr} trend) has no group-only code in coverage, issues or observations`)}
ok(t.coverageIssues().every(c=>t.SHARED.some(p=>p.id===c.id)),'coverage issues list individual people only');
t.renderUnavailable();const unavailable=app.innerHTML;
for(const h of ['p04','p10','p99','p04-night-2026-11-20','p10-day-2026-11-20','p10-wo-2026-11-20','p04-ex-2026-11-20']){location.hash='#'+h;t.route();ok(app.innerHTML===unavailable,`#${h} shows the same page as an unknown code`)}
for(const fn of [()=>t.renderProfile(t.P.p04),()=>t.renderDetail(t.P.p10,'night','2026-11-20'),()=>t.renderWorkout(t.P.p04,'2026-11-20')]){fn();ok(app.innerHTML===unavailable,'direct render of a group-only person is refused')}
location.hash='#p03';t.route();ok(app.innerHTML.includes('Rami Saade'),'#p03 still opens its profile');
for(const id of ['p09','p13','p08','p01','p03']){const r=t.P[id];const w=r.days.find(d=>d.workouts.length);if(w){try{t.renderWorkout(r,w.d);ok(!/undefined|NaN/.test(app.innerHTML),`workout ${id} ${w.d}`)}catch(e){ok(false,'workout '+id+': '+e.message)}}}
t.state.trend='dayhr';try{t.renderOverview();ok(!/NaN/.test(app.innerHTML),'overview daytime HR trend')}catch(e){ok(false,'dayhr '+e.message)}
t.state.trend='sleep';t.renderOverview();
const caption=(app.innerHTML.match(/<p class="note">([^<]*left out[^<]*)<\/p>/)||[])[1]||'';
ok(caption.includes('fewer than 5 people have an eligible value'),'sleep trend explains the minimum once');
ok(!/\b[1-4]\b/.test(caption)&&!caption.includes('13 Nov')&&!/\bof 5\b/.test(caption),'caption reveals no suppressed count or date: '+caption);
ok(!/\b4 of\b|\(\d+ of \d+/.test(app.innerHTML),'no "n of 5" count anywhere on the overview');
console.log(out.join('\n'));
