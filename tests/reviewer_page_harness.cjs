"use strict";
/* Loads the reviewer page's script in Node with a minimal DOM stand-in; shared by the walkthrough tests. */
const fs=require('fs');
module.exports=function load(path, transformData){
  const html=fs.readFileSync(path,'utf8');
  const fm=html.match(/<script id="field-map" type="application\/json">([\s\S]*?)<\/script>/)[1];
  const source=html.match(/<script id="reviewer-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
  const data=transformData?JSON.stringify(transformData(JSON.parse(source))):source;
  const js=html.match(/<script>\r?\n([\s\S]*?)<\/script>/)[1];
  const el=()=>({innerHTML:'',textContent:'',classList:{add(){}},set onclick(f){},querySelectorAll:()=>[],addEventListener(){},setAttribute(){},dataset:{}});
  const app=el();const labels={};
  global.document={addEventListener(){},getElementById:id=>id==='field-map'?{textContent:fm}:id==='reviewer-data'?{textContent:data}:id==='app'?app:(labels[id]=labels[id]||el()),querySelectorAll:()=>[]};
  global.window={addEventListener(){},scrollTo(){},scrollY:0};global.history={length:1,back(){}};
  global.location={hash:'#overview'};
  const names='go,LIVE,DATA,P,worthALook,groupStat,signals,baseline,coverageIssues,covGroup,renderOverview,renderProfile,renderDetail,renderWorkout,renderSources,renderPeople,renderUnavailable,route,SHARED,nightDetail,dayMinutes,daytimeHR,hm,state,NOW,FIELD_MAP,FLAG_TEXT';
  const t=new Function(js+`\nreturn {${names}};`)();
  const out=[];const ok=(c,m)=>{out.push((c?'PASS ':'FAIL ')+m);if(!c)process.exitCode=1};
  return {t,app,labels,out,ok,html};
};
