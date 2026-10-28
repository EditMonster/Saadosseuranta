/* Raportit: lakikohtainen analyysi ja johtoryhmäraportti Word- (.docx) ja PowerPoint-muodossa (.pptx).

   Ladataan vasta, kun käyttäjä painaa latausnappia (index.html: loadReports), yhdessä kirjaston kanssa:
   docx 9 (vendor/docx-*.min.js, window.docx) tai PptxGenJS 4 (vendor/pptxgen-*.bundle.js, window.PptxGenJS).
   Tiedosto kootaan kokonaan selaimessa sivulla jo olevasta aineistosta – ei palvelinta eikä tekoälykutsuja.
   Käyttää sivun globaaleja: DATA, CHANGES, RULINGS, META, TODAY, state, fmt, pd, statusOf, nextEvent,
   entryDate, openConsultation, phaseSteps, loadLausunnot, loadDiff, loadInfluence, folderById, SITE, ST_LABEL,
   ST_ORDER. Tekstit kulkevat sivun kääntäjän läpi (i18n.tr), joten raportti syntyy valitulla kielellä. */
(function(){
"use strict";
const T=s=>{ try{ return (window.i18n&&i18n.lang()!=="fi")?i18n.tr(String(s)):String(s); }catch(e){ return String(s); } };
const C={acc:"B4600A",ink:"2B241F",muted:"7A6E64",line:"E6DCD0",soft:"F6F0E8",green:"4E7A3A",red:"A8442A",blue:"1F5FA8"};
const FONT="Calibri", DAY=864e5;
const dstr=s=>s?fmt(pd(s)):"";
const clip=(s,n)=>{ s=String(s||"").replace(/\s+/g," ").trim(); return s.length>n?s.slice(0,n-1).replace(/\s+\S*$/,"")+" …":s; };
const asOf=()=>{ const g=(typeof META!=="undefined"&&META&&META.generated)||""; return g?fmt(new Date(g.slice(0,10)+"T00:00:00Z")):fmt(TODAY); };
const link=it=>SITE()+"#"+it.id;
const nameOf=it=>String(it.fullTitle||it.title||"").replace(/\s+/g," ").trim();
const short=it=>String(it.title||it.fullTitle||"").replace(/\s+/g," ").trim();
const safeName=s=>String(s||"").normalize("NFKD").replace(/[̀-ͯ]/g,"").replace(/[^\w.-]+/g,"_").replace(/_+/g,"_").replace(/^_|_$/g,"").slice(0,80)||"raportti";
const STANCE_COLOR={vastustaa:"A8442A",osin:"C2683A",varauksin:"D69A3C",muutoksia:"C9B458",kannattaa:"4E7A3A",kanta:"8C8278",esittely:"B5ADA5",ei:"D8D2CB"};
const KIND_TITLE={lausunto:"Lausuntokierros",he:"HE eduskunnalle",eduskunta:"Eduskuntakäsittely",hyvaksytty:"Hyväksytty",vahvistettu:"Vahvistettu",julkaistu:"Julkaistu",
  voimaan:"Voimaan",soveltaminen:"Soveltaminen",maaraaika:"Täytäntöönpano",ehdotus:"Komission ehdotus",kanta:"Suomen kanta",parlamentti:"Parlamentti",
  neuvosto:"Neuvosto",sopu:"Poliittinen sopu",ennuste:"Ennuste",muu:"Muu vaihe"};

/* ---------------- aineiston kokoaminen ---------------- */
async function lawData(it){
  const safe=p=>Promise.resolve(p).catch(()=>null);
  const [ls,diff,infl]=await Promise.all([
    safe(it.scope==="fi"?loadLausunnot(it.id):null),
    safe(it.diffN?loadDiff(it.id):null),
    safe(loadInfluence().then(m=>(m&&m[it.id])||null))]);
  const evs=(it.events||[]).slice().sort((a,b)=>a.date.localeCompare(b.date));
  const rulings=(typeof RULINGS!=="undefined"?RULINGS:[]).filter(r=>(r.related||[]).includes(it.id)).slice(0,12);
  return {it,ls,diff,infl,evs,rulings,steps:keySteps(it,evs),changes:CHANGES.filter(c=>c.id===it.id).slice(0,20),
    st:statusOf(it),next:nextEvent(it),entry:entryDate(it),oc:openConsultation(it)};
}
/* the drawer's stepper when the item has one; otherwise the first event of each key kind */
function keySteps(it,evs){
  const st=phaseSteps(it);
  if(st&&st.some(s=>s.d)) return st.map(s=>({t:String(s.t).replace(/­/g,""),d:s.d,end:s.end,label:s.label}));
  const ORDER=["lausunto","ehdotus","he","kanta","parlamentti","neuvosto","sopu","hyvaksytty","vahvistettu","julkaistu","voimaan","soveltaminen","maaraaika"];
  const seen=new Set(), out=[];
  evs.forEach(e=>{ if(ORDER.includes(e.kind)&&!seen.has(e.kind)){ seen.add(e.kind); out.push({t:KIND_TITLE[e.kind]||e.kind,d:pd(e.date),end:e.end?pd(e.end):null,label:e.label}); } });
  return out.sort((a,b)=>a.d-b.d).slice(0,8);
}
const stepState=(s,i,steps)=>{
  if(s.d&&s.d<=TODAY&&s.end&&s.end>=TODAY) return "now";
  if(s.d&&(s.end||s.d)<=TODAY) return "done";
  return "todo";
};
const stepWhen=s=>s.d?(s.end&&+s.end!==+s.d?`${fmt(s.d)}–${fmt(s.end)}`:fmt(s.d)):"–";

/* johtoryhmälle olennaiset tyypit: kansalliset lait ja asetukset sekä EU:n lainsäädäntöasiat (ei komission
   täytäntöönpanosäädöksiä, pakotteita, aloitteita, kirjelmiä, kuulemisia tai ohjeita) */
const CORE=new Set(["fi:laki","fi:asetus","eu:eu"]);
function scopePool(o){
  let pool=DATA.filter(it=>(it.scope==="fi"||it.scope==="eu")&&!(state.hidden&&state.hidden.has(it.id)));
  if(o.types!=="all") pool=pool.filter(it=>CORE.has(it.scope+":"+(it.laji||"laki")));
  let label=T("Kaikki säädökset ja EU-asiat");
  if(o.scope==="follow"){ pool=pool.filter(it=>state.follow.has(it.id)); label=T("Seuratut kohteet"); }
  else if(o.scope==="filters"){ pool=pool.filter(it=>matches(it)); label=T("Sivun nykyiset valinnat")+(state.topics.size?": "+[...state.topics].map(T).join(", "):""); }
  else if(String(o.scope||"").startsWith("folder:")){ const f=folderById(o.scope.slice(7)); const ids=new Set(f?f.items:[]); pool=pool.filter(it=>ids.has(it.id)); label=T("Kansio")+": "+(f?f.name:"–"); }
  label+=" · "+(o.types==="all"?T("kaikki tyypit"):T("lait, asetukset ja EU-säädökset"));
  return {pool,label};
}
async function reportData(o){
  const {pool,label}=scopePool(o);
  const from=new Date(+TODAY-o.days*DAY), to=new Date(+TODAY+o.ahead*DAY);
  const past=d=>{ const x=pd(d); return x>=from&&x<=TODAY; }, fut=d=>{ const x=pd(d); return x>TODAY&&x<=to; };
  const PAST_KINDS=new Set(["he","hyvaksytty","vahvistettu","voimaan","julkaistu","ehdotus","sopu","kanta","lausunto"]);
  const happened=[];
  pool.forEach(it=>(it.events||[]).forEach(e=>{ if(PAST_KINDS.has(e.kind)&&e.confirmed!==false&&past(e.date)&&!(e.kind==="julkaistu"&&it.scope==="fi")) happened.push({it,e}); }));
  happened.sort((a,b)=>b.e.date.localeCompare(a.e.date));
  const firstSig=it=>(it.events||[]).filter(e=>["lausunto","he","ehdotus"].includes(e.kind)).sort((a,b)=>a.date.localeCompare(b.date))[0];
  const fresh=pool.filter(it=>{ const f=firstSig(it); return f&&past(f.date); });
  const entering=[], euDeadlines=[], transitions=[];
  pool.forEach(it=>{
    const v=(it.events||[]).filter(e=>(e.kind==="voimaan"||e.kind==="soveltaminen")&&fut(e.date)).sort((a,b)=>a.date.localeCompare(b.date))[0];
    if(v) entering.push({it,e:v});
    (it.events||[]).filter(e=>e.kind==="maaraaika"&&fut(e.date)).slice(0,1).forEach(e=>euDeadlines.push({it,e}));
    (it.events||[]).filter(e=>e.kind==="siirtyma"&&fut(e.date)).forEach(e=>transitions.push({it,e}));
  });
  transitions.sort((a,b)=>a.e.date.localeCompare(b.e.date));
  entering.sort((a,b)=>a.e.date.localeCompare(b.e.date)); euDeadlines.sort((a,b)=>a.e.date.localeCompare(b.e.date));
  const open=pool.map(it=>({it,e:openConsultation(it)})).filter(x=>x.e).sort((a,b)=>a.e.end.localeCompare(b.e.end));
  const passed=happened.filter(x=>x.e.kind==="hyvaksytty"||x.e.kind==="vahvistettu"||x.e.kind==="sopu");
  const ids=new Set(pool.map(it=>it.id));
  let rulings=(typeof RULINGS!=="undefined"?RULINGS:[]).filter(r=>r.date&&past(r.date));
  if(o.scope==="follow"||String(o.scope).startsWith("folder:")) rulings=rulings.filter(r=>(r.related||[]).some(id=>ids.has(id)));
  else if(o.scope==="filters"&&state.topics.size) rulings=rulings.filter(r=>(r.topics||[]).some(t=>state.topics.has(t)));
  const COURT_W={KKO:3,KHO:3,EUT:3,MAO:2,TT:2};
  rulings=rulings.sort((a,b)=>(COURT_W[b.court]||1)-(COURT_W[a.court]||1)||b.date.localeCompare(a.date)).slice(0,15);
  /* nostot: watched items first, then the weightiest events of the period and the nearest entries into force */
  const W={vahvistettu:3,he:3,sopu:3,hyvaksytty:2,ehdotus:2,julkaistu:2,kanta:1,lausunto:1,voimaan:2};
  const score=new Map();
  const bump=(it,s,why)=>{ const cur=score.get(it.id)||{it,s:0,why:[]}; cur.s+=s; if(why) cur.why.push(why); score.set(it.id,cur); };
  happened.forEach(({it,e})=>bump(it,(W[e.kind]||1)+(it.laji==="laki"||it.laji==="eu"?1:0),{e,past:true}));
  entering.forEach(({it,e})=>bump(it,pd(e.date)-TODAY<=30*DAY?4:2,{e,past:false}));
  open.forEach(({it,e})=>bump(it,1.5,{e,open:true}));
  score.forEach(v=>{ if(state.follow.has(v.it.id)) v.s+=5; });
  const highlights=[...score.values()].sort((a,b)=>b.s-a.s).slice(0,6);
  return {o,label,from,to,pool,happened,fresh,entering,euDeadlines,transitions,open,passed,rulings,highlights};
}
const evText=e=>T(e.label||KIND_TITLE[e.kind]||e.kind)+(e.confirmed===false?` (${T("arvio")})`:"");
function highlightLine(h){
  const it=h.it, p=h.why.filter(w=>w.past).sort((a,b)=>b.e.date.localeCompare(a.e.date))[0];
  const n=nextEvent(it);
  const parts=[];
  if(p) parts.push(`${dstr(p.e.date)}: ${evText(p.e)}`);
  if(n) parts.push(`${T("Seuraavaksi")}: ${T(n.label||"")} ${fmt(n.date)}`);
  return parts.join(" · ");
}

/* ---------------- aikajanakuva (PNG Wordiin) ---------------- */
function timelinePng(steps){
  const W=1600, H=330, pad=150, cv=document.createElement("canvas"); cv.width=W; cv.height=H;
  const x=cv.getContext("2d"); x.fillStyle="#FFFFFF"; x.fillRect(0,0,W,H);
  const n=steps.length, y=140, gap=n>1?(W-2*pad)/(n-1):0;
  const X=i=>n>1?pad+i*gap:W/2;
  const lastDone=steps.reduce((a,s,i)=>stepState(s,i,steps)!=="todo"?i:a,-1);
  x.lineWidth=6; x.lineCap="round";
  x.strokeStyle="#E6DCD0"; x.beginPath(); x.moveTo(X(0),y); x.lineTo(X(n-1),y); x.stroke();
  if(lastDone>0){ x.strokeStyle="#"+C.acc; x.beginPath(); x.moveTo(X(0),y); x.lineTo(X(lastDone),y); x.stroke(); }
  const font=(w,s)=>`${w} ${s}px Calibri, Carlito, "Segoe UI", Arial, sans-serif`;
  const wrap=(t,maxW)=>{ const words=String(t).split(/\s+/), lines=[]; let cur=""; words.forEach(w=>{ const nx=cur?cur+" "+w:w; if(x.measureText(nx).width>maxW&&cur){ lines.push(cur); cur=w; } else cur=nx; }); if(cur) lines.push(cur); return lines.slice(0,2); };
  steps.forEach((s,i)=>{
    const st=stepState(s,i,steps), cx=X(i);
    x.beginPath(); x.arc(cx,y,st==="now"?17:14,0,Math.PI*2);
    if(st==="done"){ x.fillStyle="#"+C.acc; x.fill(); }
    else if(st==="now"){ x.fillStyle="#FFFFFF"; x.fill(); x.lineWidth=6; x.strokeStyle="#"+C.acc; x.stroke(); }
    else { x.fillStyle="#FFFFFF"; x.fill(); x.lineWidth=4; x.strokeStyle="#B5ADA5"; x.stroke(); }
    x.textAlign="center"; x.fillStyle="#"+C.ink; x.font=font(600,28);
    const maxW=Math.min(290,Math.max(150,gap-16));
    wrap(T(s.t),maxW).forEach((l,k,arr)=>x.fillText(l,cx,y-40-(arr.length-1-k)*32));
    x.font=font(400,25); x.fillStyle=st==="todo"?"#"+C.muted:"#"+C.ink;
    wrap(stepWhen(s),maxW).forEach((l,k)=>x.fillText(l,cx,y+52+k*30));
    if(st==="now"){ x.font=font(600,23); x.fillStyle="#"+C.acc; x.fillText(T("käynnissä"),cx,y+112); }
  });
  const today=steps.findIndex(s=>s.d&&s.d>TODAY);
  const bin=atob(cv.toDataURL("image/png").split(",")[1]); const u=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++) u[i]=bin.charCodeAt(i);
  return {data:u,w:W,h:H,today};
}

/* ---------------- Word ---------------- */
function W(){
  const X=window.docx;
  const run=(text,o={})=>new X.TextRun({text:String(text??""),font:FONT,...o});
  const P=(kids,o={})=>new X.Paragraph({spacing:{after:o.after??100,before:o.before??0,line:o.line},alignment:o.align,keepNext:o.keepNext,
    children:(Array.isArray(kids)?kids:[kids]).map(k=>typeof k==="string"?run(k,o.run||{}):k),bullet:o.bullet?{level:0}:undefined});
  const H1=t=>new X.Paragraph({heading:X.HeadingLevel.HEADING_1,keepNext:true,children:[run(t)]});
  const H2=t=>new X.Paragraph({heading:X.HeadingLevel.HEADING_2,keepNext:true,children:[run(t)]});
  const A=(text,url)=>new X.ExternalHyperlink({link:url,children:[run(text,{style:"Hyperlink"})]});
  const muted=(t,o={})=>P(run(t,{color:C.muted,size:18}),o);
  const border={style:X.BorderStyle.SINGLE,size:4,color:C.line};
  const cell=(kids,o={})=>new X.TableCell({width:o.w?{size:o.w,type:X.WidthType.PERCENTAGE}:undefined,
    shading:o.fill?{type:X.ShadingType.CLEAR,color:"auto",fill:o.fill}:undefined,margins:{top:60,bottom:60,left:100,right:100},
    verticalAlign:X.VerticalAlign.TOP,children:(Array.isArray(kids)?kids:[kids]).map(k=>k instanceof X.Paragraph?k:P(typeof k==="string"?run(k,{size:o.size||19,bold:o.bold,color:o.color}):k,{after:0}))});
  const table=(head,rows,widths)=>new X.Table({width:{size:100,type:X.WidthType.PERCENTAGE},
    borders:{top:border,bottom:border,left:border,right:border,insideHorizontal:border,insideVertical:{style:X.BorderStyle.NONE,size:0,color:"FFFFFF"}},
    rows:[new X.TableRow({tableHeader:true,children:head.map((h,i)=>cell(h,{w:widths&&widths[i],fill:C.soft,bold:true,size:18}))}),
      ...rows.map(r=>new X.TableRow({cantSplit:true,children:r.map((c,i)=>cell(c,{w:widths&&widths[i]}))}))]});
  const doc=(title,children)=>new X.Document({creator:"Säädösseuranta",title,description:title,
    styles:{default:{document:{run:{font:FONT,size:21,color:C.ink}}},
      paragraphStyles:[
        {id:"Title",name:"Title",basedOn:"Normal",next:"Normal",run:{size:40,bold:true,color:C.ink},paragraph:{spacing:{after:120}}},
        {id:"Heading1",name:"Heading 1",basedOn:"Normal",next:"Normal",quickFormat:true,run:{size:28,bold:true,color:C.ink},paragraph:{spacing:{before:360,after:120}}},
        {id:"Heading2",name:"Heading 2",basedOn:"Normal",next:"Normal",quickFormat:true,run:{size:23,bold:true,color:C.acc},paragraph:{spacing:{before:240,after:80}}}],
      characterStyles:[{id:"Hyperlink",name:"Hyperlink",basedOn:"DefaultParagraphFont",run:{color:C.blue,underline:{type:X.UnderlineType.SINGLE}}}]},
    numbering:{config:[]},
    sections:[{properties:{page:{margin:{top:1100,bottom:1100,left:1200,right:1200}}},
      footers:{default:new X.Footer({children:[new X.Paragraph({alignment:X.AlignmentType.RIGHT,children:[run(`Säädösseuranta · ${T("aineisto")} ${asOf()} · `,{size:16,color:C.muted}),new X.TextRun({children:[X.PageNumber.CURRENT],size:16,color:C.muted,font:FONT})]})]})},
      children}]});
  return {X,run,P,H1,H2,A,muted,table,doc,cell};
}
const linkRow=(w,it)=>w.P([w.A(short(it),link(it)),w.run(it.ref?"  ·  "+it.ref:"",{color:C.muted,size:18})],{after:0});

async function lawDocx(it){
  const d=await lawData(it), w=W(), X=w.X, ch=[];
  const ls=d.ls||{};
  ch.push(new X.Paragraph({style:"Title",children:[w.run(nameOf(it))]}));
  ch.push(w.P([w.run([T(it.kind||""),it.ref].filter(Boolean).join(" · "),{color:C.muted}),w.run("   "),w.run(T(d.st.text||""),{bold:true,color:C.acc})],{after:60}));
  ch.push(w.muted(`${T("Lakianalyysi")} · ${T("aineisto")} ${asOf()} · ${it.ministry?T(it.ministry)+" · ":""}${(it.topics||[]).map(T).join(", ")}`,{after:240}));

  /* avainluvut */
  const facts=[[T("Tila"),T(d.st.text||"–")],[T("Seuraava vaihe"),d.next?`${T(d.next.label||"")} ${fmt(d.next.date)}`:"–"],
    [T("Voimaantulo"),d.entry?`${fmt(d.entry.date)}${d.entry.label?" ("+T(d.entry.label)+")":""}`:"–"],
    [T("Vastuutaho"),[it.ministry,(it.committees||[]).join(", ")].filter(Boolean).map(T).join(" · ")||"–"]];
  ch.push(w.table([T("Tieto"),T("Arvo")],facts,[28,72]));
  if(it.summary&&it.summary!==it.title){ ch.push(w.H1(T("Tiivistelmä"))); ch.push(w.P(it.summary)); }

  /* aikajana */
  if(d.steps.length){
    ch.push(w.H1(T("Aikajana")));
    const img=timelinePng(d.steps);
    ch.push(new X.Paragraph({children:[new X.ImageRun({type:"png",data:img.data,transformation:{width:620,height:Math.round(620*img.h/img.w)}})],spacing:{after:120}}));
  }
  /* valiokuntien asiantuntijakuulemiset yhdeksi riviksi – muuten ne peittäisivät varsinaiset vaiheet */
  const HEAR=/^Asiantuntijakuuleminen/i, hear=d.evs.filter(e=>HEAR.test(e.label||""));
  const keyEv=d.evs.filter(e=>!HEAR.test(e.label||"")&&(e.kind!=="muu"||/mietintö|lausunto/i.test(e.label||"")));
  if(hear.length) keyEv.push({date:hear[0].date,end:hear[hear.length-1].date,kind:"eduskunta",label:`${T("Asiantuntijakuulemiset valiokunnissa")}: ${hear.length} ${T("kuulemispäivää")}`});
  keyEv.sort((a,b)=>a.date.localeCompare(b.date));
  if(keyEv.length){
    ch.push(w.H2(T("Vaiheet päivämäärineen")));
    ch.push(w.table([T("Päivä"),T("Vaihe")],keyEv.slice(-40).map(e=>[e.end&&e.end!==e.date?`${dstr(e.date)}–${dstr(e.end)}`:dstr(e.date),evText(e)]),[22,78]));
  }

  /* siirtymäsäännökset */
  const SK={voimaan:"Porrastettu voimaantulo",soveltaminen:"Soveltaminen alkaa",voimassa:"Määräaikainen säännös päättyy",velvoite:"Siirtymäajan määräaika",vanha:"Aiempiin sovelletaan vanhaa lakia",kumottu:"Kumottua säännöstä sovelletaan asti"};
  const sWhen=r=>r.d?dstr(r.d)+(r.calc?` (${r.r} ${T("voimaantulosta")})`:""):(r.r==="asetuksella"?T("valtioneuvoston asetuksella"):(r.r?`${r.r} ${T("voimaantulosta")}`:"–"));
  if((it.siirtymat||[]).length){
    ch.push(w.H1(T("Siirtymäsäännökset ja porrastettu voimaantulo")));
    if(it.siirtymat.some(r=>r.src!=="sk")) ch.push(w.muted(T("Hallituksen esityksen tai valiokunnan mietinnön mukaan – voi muuttua eduskunnassa.")));
    ch.push(w.table([T("Milloin"),T("Mitä"),T("Säännös")],it.siirtymat.map(r=>[sWhen(r),T(SK[r.k]||r.k)+(r.s?": "+r.s:""),clip(r.t,300)]),[18,30,52]));
  }
  /* sisältö ja säätämisjärjestys */
  if(ls.he&&(ls.he.sisalto||(ls.he.sj&&ls.he.sj.text))){
    ch.push(w.H1(T("Esityksen pääasiallinen sisältö")));
    if(ls.he.sisalto) ch.push(w.P(ls.he.sisalto));
    const sj=ls.he.sj||{};
    if(sj.order||sj.text){ ch.push(w.H2(T("Säätämisjärjestys")));
      const SJ={tavallinen:"Tavallinen lainsäätämisjärjestys",perustuslaki:"Perustuslain säätämisjärjestys",supistettu:"Supistettu perustuslain säätämisjärjestys"};
      if(sj.order) ch.push(w.P([w.run(T(SJ[sj.order]||sj.order),{bold:true}),w.run(sj.pev?" · "+T("PeV:n lausuntoa pidetään suotavana"):"")]));
      if(sj.text) ch.push(w.P(w.run(sj.text,{color:C.muted,size:19}))); }
  }
  if(it.arviointineuvosto&&it.arviointineuvosto.text){ ch.push(w.H2(T("Lainsäädännön arviointineuvosto"))); ch.push(w.P(clip(it.arviointineuvosto.text,1200))); }

  /* lausunnot */
  const stanceTable=sec=>{ const k=sec.kannat||{}; const rows=ST_ORDER.filter(s=>k[s]).map(s=>[T(ST_LABEL[s]||s),String(k[s])]); return rows.length?w.table([T("Kanta"),T("Lausuntoja")],rows,[70,30]):null; };
  const quotes=(sec,n)=>{ const pick=(sec.rivit||[]).filter(r=>r.gist).sort((a,b)=>ST_ORDER.indexOf(a.stance||a.kanta)-ST_ORDER.indexOf(b.stance||b.kanta)).slice(0,n);
    return pick.map(r=>w.P([w.run((r.org||"")+(r.stance||r.kanta?` (${T(ST_LABEL[r.stance||r.kanta]||r.stance||r.kanta)})`:"")+": ",{bold:true}),w.run(r.gist)],{bullet:true,after:60})); };
  if(ls.kierros&&ls.kierros.n){
    ch.push(w.H1(T("Lausuntokierros")));
    ch.push(w.P(`${ls.kierros.n} ${T("lausuntoa")}`));
    const t=stanceTable(ls.kierros); if(t) ch.push(t);
    ch.push(w.H2(T("Poimintoja lausunnoista"))); quotes(ls.kierros,8).forEach(p=>ch.push(p));
  }
  /* eduskunta */
  const vk=ls.valiokunnat||[], ts=ls.taysistunto||null, ed=ls.eduskunta||null;
  if(vk.length||ts||(ed&&ed.n)){
    ch.push(w.H1(T("Eduskuntakäsittely")));
    vk.forEach(v=>{
      ch.push(w.H2(`${v.tunnus||""} ${T(v.committeeName||v.committee||"")}`.trim()));
      ch.push(w.P([w.run(`${dstr(v.date)} · ${T(v.decision==="muutettuna"?"Hyväksytty muutettuna":(v.decision==="muuttamattomana"?"Hyväksytty muuttamattomana":(v.decision||"")))}`,{bold:true}),
        w.run(v.changedSections&&v.changedSections.length?` · ${T("muutetut pykälät")}: ${v.changedSections.join(", ")}`:"")]));
      if(v.view) ch.push(w.P(clip(v.view,900)));
      if(v.dissent) ch.push(w.muted(`${T("Vastalauseita")}: ${v.dissent}${v.dissentParties&&v.dissentParties.length?" ("+v.dissentParties.join(", ")+")":""}`));
      if(v.url) ch.push(w.P(w.A(T("Mietintö eduskunnan sivuilla"),v.url)));
    });
    if(ed&&ed.n){ ch.push(w.H2(T("Asiantuntijalausunnot valiokunnille"))); ch.push(w.P(`${ed.n} ${T("lausuntoa")}`)); const t=stanceTable(ed); if(t) ch.push(t); quotes(ed,5).forEach(p=>ch.push(p)); }
    if(ts){
      ch.push(w.H2(T("Täysistunto")));
      (ts.kasittelyt||[]).forEach(k=>ch.push(w.P(`${dstr(k.date)} · ${T(k.vaihe||"")} · ${k.puheenvuorot||0} ${T("puheenvuoroa")}`,{bullet:true,after:40})));
      (ts.aanestykset||[]).forEach(v=>{ const [j,e,t,p]=v.tulos||[0,0,0,0];
        ch.push(w.P([w.run(`${T(v.otsikko||"Äänestys")}: `,{bold:true}),w.run(`${T("jaa")} ${j} – ${T("ei")} ${e}${t?` · ${T("tyhjiä")} ${t}`:""}${p?` · ${T("poissa")} ${p}`:""}`),
          w.run(v.hallitus?` (${T("hallitus")} ${v.hallitus[0]}–${v.hallitus[1]}, ${T("oppositio")} ${v.oppositio?v.oppositio[0]+"–"+v.oppositio[1]:"–"})`:"",{color:C.muted})])); });
      if((ts.lausumat||[]).length){ ch.push(w.P(w.run(T("Eduskunnan lausumat")+(ts.ev?` (${ts.ev})`:""),{bold:true}),{after:40})); ts.lausumat.forEach(l=>ch.push(w.P(l,{bullet:true,after:40}))); }
    }
  }
  /* lakitekstin muutokset */
  if(d.diff&&(d.diff.steps||[]).length){
    const st=d.diff.steps[d.diff.steps.length-1];
    ch.push(w.H1(T("Mikä muuttuu lakitekstissä")));
    ch.push(w.muted(`${T(st.label||"")} · ${T("lisätty teksti alleviivattuna, poistettu yliviivattuna")}`));
    let left=60;
    (st.laws||[]).forEach(l=>{ if(left<=0) return;
      ch.push(w.H2(l.name));
      (l.sections||[]).forEach(s=>{ if(left--<=0) return;
        ch.push(w.P(w.run(`${s.id}${s.heading?" "+s.heading:""}${s.new?" · "+T("uusi pykälä"):""}${s.removed?" · "+T("kumotaan"):""}`,{bold:true}),{after:40,keepNext:true}));
        const runs=(s.ops||[]).map(([k,txt])=>k==="="?w.run(txt+" "):k==="+"?w.run(txt+" ",{color:C.green,underline:{}}):k==="-"?w.run(txt+" ",{color:C.red,strike:true}):w.run(`[… ${txt} …] `,{color:C.muted,italics:true}));
        if(runs.length) ch.push(w.P(runs,{after:120}));
      }); });
    if(left<=0) ch.push(w.muted(T("Lista katkaistu – koko vertailu sivulla.")));
  }
  /* vaikuttaminen */
  const inf=d.infl;
  if(inf&&((inf.kuulemiset||[]).length||(inf.lobbaus&&inf.lobbaus.n))){
    ch.push(w.H1(T("Vaikuttaminen")));
    if((inf.kuulemiset||[]).length){ const heard=inf.kuulemiset.reduce((n,k)=>n+(k.heard||[]).length,0); ch.push(w.P(`${T("Valiokuntakuulemiset")}: ${inf.kuulemiset.length} · ${T("kuultuja")} ${heard}`)); }
    const B=inf.lobbaus; if(B&&B.n) ch.push(w.P(`${T("Avoimuusrekisteri")}: ${B.n} ${T("toimintailmoitusta")}, ${B.contacts||0} ${T("yhteydenottoa")}${(B.orgs||[]).length?" · "+B.orgs.slice(0,12).join(", "):""}`));
  }
  if(d.rulings.length){ ch.push(w.H1(T("Liittyvä oikeuskäytäntö")));
    ch.push(w.table([T("Ratkaisu"),T("Päivä"),T("Asia")],d.rulings.map(r=>[w.P(r.url?w.A(r.ref,r.url):w.run(r.ref),{after:0}),dstr(r.date),clip(r.title||r.summary,140)]),[22,16,62])); }
  if(d.changes.length){ ch.push(w.H1(T("Seurannan muutoshistoria"))); d.changes.forEach(c=>ch.push(w.P(`${dstr(c.date)} · ${T(c.text)}`,{bullet:true,after:40}))); }
  /* lähteet */
  ch.push(w.H1(T("Lähteet")));
  const L=it.links||{}, names={hankeikkuna:"Hankeikkuna",finlex:"Finlex: hallituksen esitys",saadoskokoelma:"Finlex: säädöskokoelma",eurlex:"EUR-Lex",oeil:"EP Legislative Observatory"};
  Object.entries(L).filter(([k,v])=>v).forEach(([k,v])=>ch.push(w.P(w.A(T(names[k]||k),v),{bullet:true,after:40})));
  ch.push(w.P(w.A(T("Säädösseuranta: asian sivu"),link(it)),{bullet:true,after:40}));
  ch.push(w.muted(T("Koottu automaattisesti julkisista lähteistä. Tarkista määräajat ja pykäläviittaukset alkuperäisestä lähteestä ennen käyttöä."),{before:200}));
  const blob=await X.Packer.toBlob(w.doc(nameOf(it),ch));
  return {blob,filename:safeName(`Lakianalyysi_${it.ref||short(it)}`)+".docx"};
}

async function reportDocx(o){
  const r=await reportData(o), w=W(), X=w.X, ch=[];
  const period=`${fmt(r.from)}–${fmt(TODAY)}`;
  ch.push(new X.Paragraph({style:"Title",children:[w.run(T("Lainsäädäntökatsaus"))]}));
  ch.push(w.P(w.run(`${T("Johtoryhmäraportti")} · ${period}`,{bold:true,color:C.acc})));
  ch.push(w.muted(`${T("Rajaus")}: ${r.label} · ${T("katse eteenpäin")} ${fmt(r.to)} ${T("asti")} · ${T("aineisto")} ${asOf()}`,{after:240}));
  const kpi=[[T("Uudet hankkeet ja ehdotukset"),r.fresh.length],[T("Hyväksytyt ja vahvistetut"),r.passed.length],[T("Voimaan tulossa"),r.entering.length],[T("Avoimet lausuntokierrokset"),r.open.length],[T("EU-täytäntöönpanon määräajat"),r.euDeadlines.length]];
  ch.push(new X.Table({width:{size:100,type:X.WidthType.PERCENTAGE},borders:{top:{style:X.BorderStyle.NONE},bottom:{style:X.BorderStyle.NONE},left:{style:X.BorderStyle.NONE},right:{style:X.BorderStyle.NONE},insideHorizontal:{style:X.BorderStyle.NONE},insideVertical:{style:X.BorderStyle.SINGLE,size:4,color:"FFFFFF"}},
    rows:[new X.TableRow({children:kpi.map(([l,n])=>w.cell([w.P(w.run(String(n),{size:44,bold:true,color:C.acc}),{after:0}),w.P(w.run(l,{size:17,color:C.muted}),{after:0})],{w:20,fill:C.soft}))})]}));
  if(r.highlights.length){ ch.push(w.H1(T("Nostot")));
    r.highlights.forEach(h=>{ ch.push(w.P([w.A(short(h.it),link(h.it)),w.run(h.it.ref?"  ·  "+h.it.ref:"",{color:C.muted,size:18})],{after:20,keepNext:true})); ch.push(w.P(w.run(highlightLine(h),{size:19}),{after:140})); }); }
  const evRows=list=>list.map(({it,e})=>[dstr(e.end&&e.kind==="lausunto"?e.end:e.date),linkRow(w,it),evText(e)]);
  if(r.entering.length){ ch.push(w.H1(`${T("Tulevat voimaantulot")} (${fmt(TODAY)}–${fmt(r.to)})`)); ch.push(w.table([T("Päivä"),T("Säädös"),T("Vaihe")],evRows(r.entering.slice(0,60)),[14,60,26])); }
  if(r.transitions.length){ ch.push(w.H1(`${T("Siirtymäajat ja porrastetut voimaantulot")} (${fmt(TODAY)}–${fmt(r.to)})`));
    ch.push(w.table([T("Päivä"),T("Säädös"),T("Mitä tapahtuu")],evRows(r.transitions.slice(0,60)),[14,52,34])); }
  if(r.open.length){ ch.push(w.H1(T("Avoimet lausuntokierrokset")));
    ch.push(w.table([T("Päättyy"),T("Hanke"),T("Ministeriö")],r.open.slice(0,40).map(({it,e})=>[dstr(e.end),linkRow(w,it),T(it.ministry||"")]),[14,60,26])); }
  if(r.happened.length){ ch.push(w.H1(T("Jakson keskeiset tapahtumat")));
    const fw=r.happened.filter(x=>state.follow.has(x.it.id)), rest=r.happened.filter(x=>!state.follow.has(x.it.id));
    const list=fw.concat(rest).slice(0,80).sort((a,b)=>b.e.date.localeCompare(a.e.date));
    ch.push(w.table([T("Päivä"),T("Asia"),T("Tapahtuma")],evRows(list),[14,60,26]));
    if(r.happened.length>80) ch.push(w.muted(`+ ${r.happened.length-80} ${T("muuta tapahtumaa sivulla")}`)); }
  if(r.euDeadlines.length){ ch.push(w.H1(T("EU: täytäntöönpano- ja muut määräajat"))); ch.push(w.table([T("Päivä"),T("Säädös"),T("Määräaika")],evRows(r.euDeadlines.slice(0,40)),[14,60,26])); }
  if(r.rulings.length){ ch.push(w.H1(T("Oikeuskäytäntö jaksolla")));
    ch.push(w.table([T("Ratkaisu"),T("Päivä"),T("Asia")],r.rulings.map(x=>[w.P(x.url?w.A(x.ref,x.url):w.run(x.ref),{after:0}),dstr(x.date),clip(x.title||x.summary,160)]),[20,14,66])); }
  ch.push(w.H1(T("Menetelmä")));
  ch.push(w.P(w.run(T("Raportti on koottu Säädösseurannan aineistosta: Hankeikkuna, eduskunnan avoin data, Finlex, Euroopan parlamentin ja EU:n julkaisutoimiston avoin data sekä tuomioistuinten julkaisut. Tapahtumat ovat vahvistettuja päivämääriä; arviot on merkitty erikseen. Tarkista määräajat alkuperäisestä lähteestä ennen päätöksentekoa."),{size:19,color:C.muted})));
  const blob=await X.Packer.toBlob(w.doc(T("Lainsäädäntökatsaus"),ch));
  return {blob,filename:safeName(`Lainsaadantokatsaus_${fmt(TODAY)}`)+".docx"};
}

/* ---------------- PowerPoint ---------------- */
function deck(title){
  const p=new window.PptxGenJS(); p.layout="LAYOUT_WIDE"; p.title=title; p.company="Säädösseuranta"; p.theme={headFontFace:FONT,bodyFontFace:FONT};
  p.defineSlideMaster({title:"BASE",background:{color:"FFFFFF"},objects:[
    {rect:{x:0,y:7.1,w:13.333,h:0.4,fill:{color:C.soft}}},
    {text:{text:`Säädösseuranta · ${T("aineisto")} ${asOf()}`,options:{x:0.5,y:7.1,w:8,h:0.4,fontSize:10,color:C.muted,fontFace:FONT,valign:"middle"}}}],
    slideNumber:{x:12.3,y:7.14,w:0.6,h:0.3,fontSize:10,color:C.muted,fontFace:FONT}});
  return p;
}
function head(s,title,kicker){
  kicker=kicker?clip(kicker,120):"";
  if(kicker) s.addText(kicker,{x:0.5,y:0.35,w:12.3,h:0.35,fontSize:12,bold:true,color:C.acc,fontFace:FONT});
  s.addText(title,{x:0.5,y:kicker?0.68:0.45,w:12.3,h:0.8,fontSize:26,bold:true,color:C.ink,fontFace:FONT,valign:"top",fit:"shrink"});
}
function titleSlide(p,title,sub,meta){
  const s=p.addSlide(); s.background={color:C.soft};
  s.addShape(p.ShapeType.rect,{x:0.6,y:2.2,w:0.12,h:2.4,fill:{color:C.acc},line:{color:C.acc}});
  s.addText(title,{x:0.95,y:2.05,w:11.6,h:1.9,fontSize:34,bold:true,color:C.ink,fontFace:FONT,valign:"bottom",fit:"shrink"});
  s.addText(sub,{x:0.95,y:4.0,w:11.6,h:0.5,fontSize:18,color:C.acc,bold:true,fontFace:FONT});
  s.addText(meta,{x:0.95,y:4.55,w:11.6,h:0.5,fontSize:14,color:C.muted,fontFace:FONT});
  return s;
}
function tableSlide(p,title,kicker,head_,rows,colW,more){
  const s=p.addSlide({masterName:"BASE"}); head(s,title,kicker);
  const hdr=head_.map(h=>({text:h,options:{bold:true,fill:{color:C.soft},color:C.ink}}));
  s.addTable([hdr,...rows],{x:0.5,y:1.6,w:12.33,colW,fontSize:11,fontFace:FONT,color:C.ink,valign:"top",border:{type:"solid",pt:0.5,color:C.line},margin:[0.05,0.08,0.05,0.08],autoPage:false});
  if(more) s.addText(more,{x:0.5,y:6.65,w:12.3,h:0.35,fontSize:11,color:C.muted,fontFace:FONT});
  return s;
}
const fsFor=(t,big)=>{ const n=String(t||"").length; return n<500?(big?20:18):n<900?16:n<1300?14:12; };
const cellLink=(it)=>({text:clip(short(it),78)+(it.ref?"  ·  "+it.ref:""),options:{hyperlink:{url:link(it)},color:C.blue}});
function timelineShapes(p,s,steps,y){
  const n=steps.length, x0=0.9, x1=12.4, gap=n>1?(x1-x0)/(n-1):0, X=i=>n>1?x0+i*gap:(x0+x1)/2;
  const lastDone=steps.reduce((a,st,i)=>stepState(st,i,steps)!=="todo"?i:a,-1);
  s.addShape(p.ShapeType.line,{x:X(0),y,w:X(n-1)-X(0),h:0,line:{color:C.line,width:4}});
  if(lastDone>0) s.addShape(p.ShapeType.line,{x:X(0),y,w:X(lastDone)-X(0),h:0,line:{color:C.acc,width:4}});
  const bw=Math.min(2.2,Math.max(1.3,gap-0.1));
  steps.forEach((st,i)=>{ const state_=stepState(st,i,steps), r=state_==="now"?0.17:0.14;
    s.addShape(p.ShapeType.ellipse,{x:X(i)-r,y:y-r,w:2*r,h:2*r,fill:{color:state_==="done"?C.acc:"FFFFFF"},line:{color:state_==="todo"?"B5ADA5":C.acc,width:state_==="now"?3:2}});
    s.addText(T(st.t),{x:X(i)-bw/2,y:y-1.05,w:bw,h:0.8,fontSize:13,bold:true,color:C.ink,align:"center",valign:"bottom",fontFace:FONT,fit:"shrink"});
    s.addText(stepWhen(st)+(state_==="now"?"\n"+T("käynnissä"):""),{x:X(i)-bw/2,y:y+0.25,w:bw,h:0.75,fontSize:12,color:state_==="todo"?C.muted:C.ink,align:"center",valign:"top",fontFace:FONT,fit:"shrink"}); });
}
function bars(p,s,items,x,y,w,rowH){
  const max=Math.max(1,...items.map(i=>i.v)), lw=2.6;
  items.forEach((i,k)=>{ const yy=y+k*rowH;
    s.addText(i.l,{x,y:yy,w:lw,h:rowH*0.8,fontSize:12,color:C.ink,fontFace:FONT,valign:"middle"});
    s.addShape(p.ShapeType.rect,{x:x+lw,y:yy+rowH*0.15,w:Math.max(0.04,(w-lw-0.6)*i.v/max),h:rowH*0.5,fill:{color:i.c||C.acc},line:{color:i.c||C.acc}});
    s.addText(String(i.v),{x:x+lw+(w-lw-0.6)*i.v/max+0.08,y:yy,w:0.6,h:rowH*0.8,fontSize:12,bold:true,color:C.ink,fontFace:FONT,valign:"middle"}); });
}
async function lawPptx(it){
  const d=await lawData(it), ls=d.ls||{}, p=deck(nameOf(it));
  titleSlide(p,nameOf(it),[T(it.kind||""),it.ref].filter(Boolean).join(" · "),`${T(d.st.text||"")} · ${T("Lakianalyysi")} ${asOf()}`);
  /* yleiskuva */
  let s=p.addSlide({masterName:"BASE"}); head(s,T("Yleiskuva"),short(it));
  const facts=[[T("Tila"),T(d.st.text||"–")],[T("Seuraava vaihe"),d.next?`${T(d.next.label||"")} ${fmt(d.next.date)}`:"–"],
    [T("Voimaantulo"),d.entry?fmt(d.entry.date):"–"],[T("Vastuutaho"),[it.ministry,(it.committees||[]).join(", ")].filter(Boolean).map(T).join(" · ")||"–"],
    [T("Aihealueet"),(it.topics||[]).map(T).join(", ")||"–"]];
  s.addTable(facts.map(([k,v])=>[{text:k,options:{bold:true,color:C.muted}},{text:v}]),{x:0.5,y:1.6,w:5.4,colW:[1.7,3.7],fontSize:13,fontFace:FONT,color:C.ink,border:{type:"none"},margin:[0.06,0.06,0.06,0.0]});
  if(it.summary&&it.summary!==it.title) s.addText(clip(it.summary,900),{x:6.3,y:1.6,w:6.5,h:5.2,fontSize:fsFor(clip(it.summary,900)),color:C.ink,fontFace:FONT,valign:"top",fit:"shrink",paraSpaceAfter:6});
  /* aikajana */
  if(d.steps.length){ s=p.addSlide({masterName:"BASE"}); head(s,T("Aikajana"),short(it)); timelineShapes(p,s,d.steps,3.4);
    const nx=d.next?`${T("Seuraavaksi")}: ${T(d.next.label||"")} ${fmt(d.next.date)}`:""; if(nx) s.addText(nx,{x:0.5,y:5.6,w:12.3,h:0.5,fontSize:15,bold:true,color:C.acc,fontFace:FONT}); }
  /* siirtymäsäännökset */
  if((it.siirtymat||[]).length){ const SK={voimaan:"Porrastettu voimaantulo",soveltaminen:"Soveltaminen alkaa",voimassa:"Määräaikainen säännös päättyy",velvoite:"Siirtymäajan määräaika",vanha:"Aiempiin sovelletaan vanhaa lakia",kumottu:"Kumottua säännöstä sovelletaan asti"};
    const rows=it.siirtymat.slice(0,9).map(r=>[{text:r.d?dstr(r.d):(r.r==="asetuksella"?T("asetuksella"):(r.r?`${r.r} ${T("voimaantulosta")}`:"–"))},{text:T(SK[r.k]||r.k)+(r.s?": "+clip(r.s,60):"")},{text:clip(r.t,150)}]);
    tableSlide(p,T("Siirtymäsäännökset ja porrastettu voimaantulo"),it.siirtymat.some(r=>r.src!=="sk")?T("ehdotus – voi muuttua eduskunnassa"):T("vahvistettu laki"),[T("Milloin"),T("Mitä"),T("Säännös")],rows,[1.9,3.6,6.83],it.siirtymat.length>9?`+ ${it.siirtymat.length-9}`:""); }
  /* sisältö */
  if(ls.he&&ls.he.sisalto){ s=p.addSlide({masterName:"BASE"}); head(s,T("Esityksen pääasiallinen sisältö"),ls.he.tunnus||"");
    s.addText(clip(ls.he.sisalto,1400),{x:0.5,y:1.6,w:12.3,h:4.4,fontSize:fsFor(clip(ls.he.sisalto,1400),true),color:C.ink,fontFace:FONT,valign:"top",fit:"shrink"});
    const sj=ls.he.sj||{}; const SJ={tavallinen:"Tavallinen lainsäätämisjärjestys",perustuslaki:"Perustuslain säätämisjärjestys",supistettu:"Supistettu perustuslain säätämisjärjestys"};
    if(sj.order) s.addText(T(SJ[sj.order]||sj.order)+(sj.pev?" · "+T("PeV:n lausuntoa pidetään suotavana"):""),{x:0.5,y:6.15,w:12.3,h:0.45,fontSize:13,bold:true,color:sj.order==="tavallinen"?C.ink:C.red,fontFace:FONT}); }
  /* lausunnot */
  const stanceSlide=(sec,title)=>{ const k=sec.kannat||{}; const items=ST_ORDER.filter(x=>k[x]).map(x=>({l:T(ST_LABEL[x]||x),v:k[x],c:STANCE_COLOR[x]}));
    if(!items.length) return; const sl=p.addSlide({masterName:"BASE"}); head(sl,title,`${sec.n} ${T("lausuntoa")}`);
    bars(p,sl,items,0.5,1.7,5.8,Math.min(0.6,4.8/items.length));
    const q=(sec.rivit||[]).filter(r=>r.gist).sort((a,b)=>ST_ORDER.indexOf(a.stance||a.kanta)-ST_ORDER.indexOf(b.stance||b.kanta)).slice(0,4);
    if(q.length) sl.addText(q.map(r=>({text:`${r.org||""}: `,options:{bold:true,breakLine:false}})).flatMap((o,i)=>[o,{text:clip(q[i].gist,220),options:{breakLine:true}}]),{x:6.7,y:1.7,w:6.1,h:5.1,fontSize:12,color:C.ink,fontFace:FONT,valign:"top",fit:"shrink",paraSpaceAfter:8}); };
  if(ls.kierros&&ls.kierros.n) stanceSlide(ls.kierros,T("Lausuntokierros"));
  /* eduskunta */
  const vk=ls.valiokunnat||[], ts=ls.taysistunto;
  if(vk.length||ts){ s=p.addSlide({masterName:"BASE"}); head(s,T("Eduskuntakäsittely"),ts&&ts.ev?ts.ev:"");
    const lines=[];
    vk.forEach(v=>{ lines.push({text:`${v.tunnus||""} · ${dstr(v.date)}`,options:{bold:true,breakLine:true}});
      lines.push({text:`${T(v.decision==="muutettuna"?"Hyväksytty muutettuna":(v.decision==="muuttamattomana"?"Hyväksytty muuttamattomana":(v.decision||"")))}${v.changedSections&&v.changedSections.length?" · "+T("muutetut pykälät")+": "+v.changedSections.join(", "):""}`,options:{breakLine:true}});
      if(v.view) lines.push({text:clip(v.view,420),options:{color:C.muted,breakLine:true}}); });
    if(ts&&(ts.lausumat||[]).length){ lines.push({text:T("Eduskunnan lausumat"),options:{bold:true,breakLine:true}}); ts.lausumat.slice(0,3).forEach(l=>lines.push({text:clip(l,260),options:{bullet:true,breakLine:true}})); }
    s.addText(lines.length?lines:[{text:"–"}],{x:0.5,y:1.6,w:7.4,h:5.2,fontSize:13,color:C.ink,fontFace:FONT,valign:"top",fit:"shrink",paraSpaceAfter:6});
    const v=ts&&(ts.aanestykset||[]).slice(-1)[0];
    if(v){ const [j,e,t,pp]=v.tulos||[0,0,0,0];
      s.addText(T("Äänestys")+" "+dstr(v.date),{x:8.3,y:1.6,w:4.5,h:0.4,fontSize:13,bold:true,color:C.ink,fontFace:FONT});
      bars(p,s,[{l:T("jaa"),v:j,c:C.green},{l:T("ei"),v:e,c:C.red},{l:T("tyhjiä"),v:t,c:"B5ADA5"},{l:T("poissa"),v:pp,c:"D8D2CB"}],8.3,2.1,4.5,0.5);
      if(v.hallitus) s.addText(`${T("hallitus")} ${v.hallitus[0]}–${v.hallitus[1]} · ${T("oppositio")} ${v.oppositio?v.oppositio[0]+"–"+v.oppositio[1]:"–"}`,{x:8.3,y:4.3,w:4.5,h:0.4,fontSize:12,color:C.muted,fontFace:FONT}); } }
  /* lakitekstin muutokset */
  if(d.diff&&(d.diff.steps||[]).length){ const st=d.diff.steps[d.diff.steps.length-1];
    const rows=[]; (st.laws||[]).forEach(l=>(l.sections||[]).forEach(x=>rows.push([{text:clip(l.name,60)},{text:`${x.id}${x.heading?" "+x.heading:""}`},{text:x.new?T("uusi pykälä"):(x.removed?T("kumotaan"):T("muutetaan"))}])));
    if(rows.length) tableSlide(p,T("Mikä muuttuu lakitekstissä"),T(st.label||""),[T("Laki"),T("Pykälä"),T("Muutos")],rows.slice(0,13),[5.4,5.0,1.93],rows.length>13?`+ ${rows.length-13} ${T("pykälää – koko vertailu Word-raportissa ja sivulla")}`:""); }
  if(d.rulings.length) tableSlide(p,T("Liittyvä oikeuskäytäntö"),"",[T("Ratkaisu"),T("Päivä"),T("Asia")],d.rulings.slice(0,10).map(r=>[{text:r.ref,options:r.url?{hyperlink:{url:r.url},color:C.blue}:{}},{text:dstr(r.date)},{text:clip(r.title||r.summary,120)}]),[2.3,1.6,8.43]);
  /* lähteet */
  s=p.addSlide({masterName:"BASE"}); head(s,T("Lähteet"),"");
  const L=it.links||{}, names={hankeikkuna:"Hankeikkuna",finlex:"Finlex: hallituksen esitys",saadoskokoelma:"Finlex: säädöskokoelma",eurlex:"EUR-Lex",oeil:"EP Legislative Observatory"};
  const src=Object.entries(L).filter(([k,v])=>v).map(([k,v])=>({text:T(names[k]||k),options:{hyperlink:{url:v},bullet:true,breakLine:true,color:C.blue}}));
  src.push({text:T("Säädösseuranta: asian sivu"),options:{hyperlink:{url:link(it)},bullet:true,breakLine:true,color:C.blue}});
  s.addText(src,{x:0.5,y:1.6,w:12.3,h:3,fontSize:15,fontFace:FONT,valign:"top",paraSpaceAfter:8});
  s.addText(T("Koottu automaattisesti julkisista lähteistä. Tarkista määräajat ja pykäläviittaukset alkuperäisestä lähteestä ennen käyttöä."),{x:0.5,y:5.9,w:12.3,h:0.6,fontSize:12,color:C.muted,fontFace:FONT});
  const blob=await p.write({outputType:"blob"});
  return {blob,filename:safeName(`Lakianalyysi_${it.ref||short(it)}`)+".pptx"};
}

async function reportPptx(o){
  const r=await reportData(o), p=deck(T("Lainsäädäntökatsaus"));
  const period=`${fmt(r.from)}–${fmt(TODAY)}`;
  titleSlide(p,T("Lainsäädäntökatsaus"),`${T("Johtoryhmäraportti")} · ${period}`,`${T("Rajaus")}: ${r.label} · ${T("aineisto")} ${asOf()}`);
  /* luvut */
  let s=p.addSlide({masterName:"BASE"}); head(s,T("Jakso lukuina"),period);
  const kpi=[[T("Uudet hankkeet ja ehdotukset"),r.fresh.length],[T("Hyväksytyt ja vahvistetut"),r.passed.length],[T("Voimaan tulossa"),r.entering.length,`${T("asti")} ${fmt(r.to)}`],[T("Avoimet lausuntokierrokset"),r.open.length],[T("EU-täytäntöönpanon määräajat"),r.euDeadlines.length]];
  kpi.forEach(([l,n,sub],i)=>{ const x=0.5+i*2.5;
    s.addShape(p.ShapeType.roundRect,{x,y:2.0,w:2.3,h:2.6,fill:{color:C.soft},line:{color:C.soft},rectRadius:0.12});
    s.addText(String(n),{x,y:2.2,w:2.3,h:1.2,fontSize:48,bold:true,color:C.acc,align:"center",fontFace:FONT});
    s.addText(l+(sub?"\n"+sub:""),{x:x+0.15,y:3.4,w:2.0,h:1.0,fontSize:13,color:C.ink,align:"center",valign:"top",fontFace:FONT,fit:"shrink"}); });
  s.addText(r.label,{x:0.5,y:5.2,w:12.3,h:0.5,fontSize:13,color:C.muted,fontFace:FONT});
  /* nostot */
  if(r.highlights.length){ s=p.addSlide({masterName:"BASE"}); head(s,T("Nostot"),period);
    r.highlights.forEach((h,i)=>{ const col=i%2, row=Math.floor(i/2), x=0.5+col*6.25, y=1.6+row*1.75;
      s.addShape(p.ShapeType.rect,{x,y,w:6.0,h:1.6,fill:{color:"FFFFFF"},line:{color:C.line,width:1}});
      s.addShape(p.ShapeType.rect,{x,y,w:0.08,h:1.6,fill:{color:state.follow.has(h.it.id)?C.acc:C.line},line:{color:state.follow.has(h.it.id)?C.acc:C.line}});
      s.addText([{text:clip(short(h.it),110),options:{bold:true,hyperlink:{url:link(h.it)},color:C.ink,breakLine:true}},{text:h.it.ref||"",options:{color:C.muted,fontSize:11,breakLine:true}},{text:highlightLine(h),options:{fontSize:12}}],
        {x:x+0.2,y:y+0.08,w:5.7,h:1.45,fontSize:13,fontFace:FONT,valign:"top",fit:"shrink"}); }); }
  const evRows=(list)=>list.map(({it,e})=>[{text:dstr(e.kind==="lausunto"&&e.end?e.end:e.date)},cellLink(it),{text:clip(evText(e),34)}]);
  const more=(all,n)=>all.length>n?`+ ${all.length-n} ${T("muuta – koko lista Word-raportissa")}`:"";
  if(r.entering.length) tableSlide(p,T("Tulevat voimaantulot"),`${fmt(TODAY)}–${fmt(r.to)}`,[T("Päivä"),T("Säädös"),T("Vaihe")],evRows(r.entering.slice(0,10)),[1.5,8.0,2.83],more(r.entering,10));
  if(r.transitions.length) tableSlide(p,T("Siirtymäajat ja porrastetut voimaantulot"),`${fmt(TODAY)}–${fmt(r.to)}`,[T("Päivä"),T("Säädös"),T("Mitä tapahtuu")],evRows(r.transitions.slice(0,10)),[1.5,7.3,3.53],more(r.transitions,10));
  if(r.open.length) tableSlide(p,T("Avoimet lausuntokierrokset"),"",[T("Päättyy"),T("Hanke"),T("Ministeriö")],r.open.slice(0,10).map(({it,e})=>[{text:dstr(e.end)},cellLink(it),{text:clip(T(it.ministry||""),34)}]),[1.5,8.0,2.83],more(r.open,10));
  if(r.happened.length){ const fw=r.happened.filter(x=>state.follow.has(x.it.id)), rest=r.happened.filter(x=>!state.follow.has(x.it.id));
    const top=fw.concat(rest.filter(x=>x.e.kind!=="lausunto")).slice(0,10).sort((a,b)=>b.e.date.localeCompare(a.e.date));
    tableSlide(p,T("Jakson keskeiset tapahtumat"),period,[T("Päivä"),T("Asia"),T("Tapahtuma")],evRows(top),[1.5,8.0,2.83],more(r.happened,10)); }
  if(r.euDeadlines.length) tableSlide(p,T("EU: täytäntöönpano- ja muut määräajat"),"",[T("Päivä"),T("Säädös"),T("Määräaika")],evRows(r.euDeadlines.slice(0,10)),[1.5,8.0,2.83],more(r.euDeadlines,10));
  if(r.rulings.length) tableSlide(p,T("Oikeuskäytäntö jaksolla"),period,[T("Ratkaisu"),T("Päivä"),T("Asia")],r.rulings.slice(0,10).map(x=>[{text:x.ref,options:x.url?{hyperlink:{url:x.url},color:C.blue}:{}},{text:dstr(x.date)},{text:clip(x.title||x.summary,110)}]),[2.3,1.5,8.53],more(r.rulings,10));
  const blob=await p.write({outputType:"blob"});
  return {blob,filename:safeName(`Lainsaadantokatsaus_${fmt(TODAY)}`)+".pptx"};
}

window.Raportit={lawDocx,lawPptx,reportDocx,reportPptx,_reportData:reportData,_lawData:lawData};
})();
