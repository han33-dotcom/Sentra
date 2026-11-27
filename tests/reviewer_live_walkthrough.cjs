"use strict";
/* Reviewer page in live mode, rendered by sentra.reviewer.live from synthetic rows (run by tests/test_reviewer_live.py). */
const {t,app,labels,out,ok}=require('./reviewer_page_harness.cjs')(process.argv[2]);
ok(t.LIVE&&t.LIVE.mode==='live','page runs in live mode');
ok(t.DATA.map(p=>p.id).join()==='p101,p91','only the individually shared people are rows: '+t.DATA.map(p=>p.id).join());
ok(labels['mode-chip']&&labels['mode-chip'].textContent==='Live data · private','label says live and private');
ok(!/Lina Haddad|Rami Saade|Cedar/.test(JSON.stringify(t.DATA)),'no demo people or names in live rows');
const look=t.worthALook();
ok(look.length===1&&look[0].p.id==='p91'&&look[0].sig.metric==='sleep'&&look[0].value===300&&look[0].usual===420,'worth a look comes from the board flag and baseline');
ok(t.baseline(t.P.p91,'rhr','2026-11-24').med===58,'usual value is the published baseline');
const s=t.signals(t.P.p91,'2026-11-24');ok(s.lvl==='amber'&&s.state==='complete','signal level and state from the board');
const leaks=html=>/\bp9[2-6]\b/.test(html);
for(const tr of ['rhr','sleep','steps']){t.state.trend=tr;t.renderOverview();
  ok(!leaks(app.innerHTML),`overview (${tr}) names no group-only or other-organization person`);
  ok(!/NaN|undefined/.test(app.innerHTML),`overview (${tr}) renders cleanly`)}
t.state.trend='rhr';t.renderOverview();
ok(app.innerHTML.includes('Board published')&&app.innerHTML.includes('Median of 5 people'),'status and server group median shown');
ok(!app.innerHTML.includes('data-trend="dayhr"'),'daytime HR is not offered in live mode');
ok(!/\(\d+ of \d+|\b[1-4] people\b/.test(app.innerHTML),'no small group count appears');
const g=t.groupStat('Fitbit','steps',t.LIVE.group.end);ok(g.value===null,'a statistic below five stays hidden');
t.renderPeople();ok(app.innerHTML.includes('>p91<')&&app.innerHTML.includes('>p101<')&&!leaks(app.innerHTML),'people list shows the two shared codes only');
for(const [h,expect] of [['p91',/Pseudonymous code/],['p101',/Pseudonymous code/],['p91-night-2026-11-24',/Asleep/],['p91-day-2026-11-20',/No processed values/],['p91-wo-2026-11-24',/not processed yet/]]){
  t.go(h);ok(expect.test(app.innerHTML)&&!/NaN|undefined/.test(app.innerHTML),'#'+h+' renders')}
t.go('p92');const hidden=app.innerHTML;t.go('p999');
ok(hidden===app.innerHTML&&hidden.includes('No individual profile'),'a group-only code looks like an unknown code');
t.go('p91-night-2026-11-24');
ok(app.innerHTML.includes('usual 7 h 00 min')&&app.innerHTML.includes('Slept less than 6 hours'),'night shows value, usual and signal');
ok(app.innerHTML.includes('Load selected data'),'minute detail is offered on request');
ok(global.location.hash==='#overview','live navigation never changes the address');
console.log(out.join('\n'));
