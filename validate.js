#!/usr/bin/env node
/* ============================================================
   Roots 単語データの検査プログラム
   仕様書: claude/word-data-spec.md
   判定には index.html の parseRoots() / clozeOf() / buildRootIndex() を
   そのまま切り出して使う（検査用に書き直さない）。

   使い方:
     node validate.js                         … index.html の全語を検査
     node validate.js --only 1-100            … 1〜100 番だけを検査（重複チェックは全語が相手）
     node validate.js --add words_101-150.js  … 追加予定の語を足して検査
                                                （α は自動で後ろにずらした形で調べる）
   違反0件なら「ALL PASS (N words checked)」で終了コード0、違反があれば表を出して終了コード1。
   「警告」は合格・不合格に関係しない（人が見て判断する項目）。
   ============================================================ */
const fs=require("fs");
const path=require("path");
const vm=require("vm");
const {execSync}=require("child_process");

const DIR=__dirname;
const args=process.argv.slice(2);
const opt=k=>{const i=args.indexOf(k);return i>=0?args[i+1]:null;};

/* ---------- index.html を読む ---------- */
const html=fs.readFileSync(path.join(DIR,"index.html"),"utf8");

function sliceBetween(src,start,end){
  const a=src.indexOf(start);
  if(a<0) throw new Error("見つからない: "+start);
  const b=src.indexOf(end,a);
  if(b<0) throw new Error("見つからない: "+end);
  return src.slice(a,b);
}
function rawWordsOf(src){
  const a=src.indexOf("const RAW_WORDS=[");
  const b=src.indexOf("\n];",a);
  return vm.runInNewContext(src.slice(a+"const RAW_WORDS=".length,b+2));
}
function alphaFromOf(src){
  const m=src.match(/const ALPHA_FROM=(\d+);/);
  return m?Number(m[1]):Infinity;
}

/* アプリの関数をそのまま切り出す */
const appCode=[
  html.match(/const esc=s=>.*\n/)[0],
  sliceBetween(html,"function clozeOf(w){","\n/* ====="),
  sliceBetween(html,"const rootCache={};","/* ============================================================\n   AUDIO"),
].join("\n");
const app={};
vm.runInNewContext(appCode+"\n;Object.assign(OUT,{clozeOf,parseRoots,splitMorphs,buildRootIndex,canonRoot,SUFFIX_STOP});",{OUT:app});

/* ---------- 検査する単語の集合をつくる ---------- */
let ALL=rawWordsOf(html);
const ALPHA_FROM=alphaFromOf(html);
let checkIds=null;          // null なら全語
const addFile=opt("--add");
if(addFile){
  const text=fs.readFileSync(path.resolve(addFile),"utf8");
  const added=vm.runInNewContext("["+text+"]");
  const addedWords=new Set(added.map(w=>w.word));
  const main=ALL.filter(w=>w.id<ALPHA_FROM&&!addedWords.has(w.word));
  const alpha=ALL.filter(w=>w.id>=ALPHA_FROM).sort((a,b)=>a.id-b.id);
  const merged=[...main,...added].sort((a,b)=>a.id-b.id);
  const lastMain=merged.reduce((m,w)=>Math.max(m,w.id),0);
  /* α は本編のすぐ後ろへ（アプリに差し込むときと同じずらし方） */
  alpha.forEach((w,i)=>{w.id=lastMain+1+i;});
  ALL=[...merged,...alpha];
  checkIds=new Set(added.map(w=>w.id));
  global.__ALPHA_FROM__=lastMain+1;
}else global.__ALPHA_FROM__=ALPHA_FROM;
const AF=global.__ALPHA_FROM__;
const only=opt("--only");
if(only){
  const [a,b]=only.split("-").map(Number);
  checkIds=new Set(ALL.filter(w=>w.id>=a&&w.id<=(b||a)).map(w=>w.id));
}
const TARGET=ALL.filter(w=>!checkIds||checkIds.has(w.id));
const isAlpha=w=>w.id>=AF;

/* ---------- 記録用 ---------- */
const errors=[], warns=[];
const bad=(w,item,why,val)=>errors.push({id:w.id,word:w.word,item,why,val:String(val??"")});
const warn=(w,item,why,val)=>warns.push({id:w.id,word:w.word,item,why,val:String(val??"")});
const len=s=>[...String(s||"")].length;   // 全角も1字として数える

const HEAD_RE=/^\s*[^\s（(＋+→]+（[^）]*）(\s*＋\s*[^\s（(＋+→]+（[^）]*）)*\s*$/;
const MORPH_RE=/^[A-Za-z][A-Za-z-]*$/;
const FORBIDDEN={posit:"pos",gree:"grat",grac:"grat",a:"ad"};
const POS_OK=["名詞","他動詞","自動詞","他動詞・自動詞","形容詞","副詞","前置詞","熟語"];
const morphsIn=head=>[...String(head).matchAll(/([^\s（(＋+→]+)（([^）]*)）/g)].map(m=>({morph:m[1],gloss:m[2]}));

/* 語根の左側（語根（意味）＋ …）をまとめて調べる。breakdown にも使う */
function checkHead(w,item,text,{maxRight,needEq}){
  const s=String(text||"");
  const arrows=(s.match(/→/g)||[]).length;
  if(arrows!==1){bad(w,item+"：→の数","→ はちょうど1回（今 "+arrows+" 回）",s);return;}
  const [head,right]=s.split("→");
  if(!HEAD_RE.test(head)) bad(w,item+"：左側の形","→ の左は「語根（意味）＋ 語根（意味）」の並びだけにする",head);
  if(/\+/.test(head)) bad(w,item+"：＋の統一","半角 + ではなく全角 ＋ を使う",head);
  morphsIn(head).forEach(({morph})=>{
    if(!MORPH_RE.test(morph)) bad(w,item+"：語根の文字","語根はラテン文字のみ",morph);
    if(morph.length>14) bad(w,item+"：語根の長さ","語根は14文字以内",morph);
    if(FORBIDDEN[morph.toLowerCase()]) bad(w,item+"：語根の綴り","統一形 "+FORBIDDEN[morph.toLowerCase()]+" を使う",morph);
  });
  const r=right.trim();
  if(needEq&&!/＝[^＝]+$/.test(r)) bad(w,item+"：＝で締める","→ の右は「…＝意味」で終える",r);
  if(len(r)>maxRight) bad(w,item+"：右側の長さ","→ の右は"+maxRight+"字以内（今 "+len(r)+" 字）",r);
}

/* 既存データの語根（綴り→意味）。追加語のチェックに使う */
const baseWords=ALL.filter(w=>!(checkIds&&checkIds.has(w.id)));
const knownRoots={};
baseWords.forEach(w=>{
  const all=[...app.parseRoots(w)];
  (w.relatedWords||[]).forEach(rw=>{if(!rw.synonym) all.push(...app.splitMorphs(rw.breakdown));});
  all.forEach(r=>{const k=app.canonRoot(r.morph);(knownRoots[k]=knownRoots[k]||new Set()).add(r.gloss);});
});
const newRoots=new Map();

/* ---------- 1語ずつの検査 ---------- */
TARGET.forEach(w=>{
  if(isAlpha(w)) return;   // α は中身を検査しない（書き換えない約束なので）
  /* 1〜4 語源の結論 */
  checkHead(w,"語源の結論",w.etymologyConclusion,{maxRight:50,needEq:true});
  /* 5 アプリの parseRoots で1つ以上のチップ */
  const chips=app.parseRoots(w);
  if(!chips.length) bad(w,"語源チップ","parseRoots() がチップを1つも返さない",w.etymologyConclusion);
  /* 6 語源のヒント */
  const p=String(w.etymologyProcess||"");
  const pa=(p.match(/→/g)||[]).length;
  if(pa!==1) bad(w,"語源のヒント：→の数","→ はちょうど1回（今 "+pa+" 回）",p);
  else{
    const tail=p.split("→")[1].trim();
    if(!/？$/.test(tail)) bad(w,"語源のヒント：？で終える","→ の右は「…？」で終える",tail);
    if(len(tail)>30) bad(w,"語源のヒント：長さ","→ の右は30字以内（今 "+len(tail)+" 字）",tail);
    if(tail.toLowerCase().includes(String(w.word).toLowerCase())) bad(w,"語源のヒント：答え","ヒントに見出し語そのものが出ている",tail);
  }
  /* 7〜10 関連語 */
  const rel=w.relatedWords||[];
  if(rel.length<3||rel.length>4) bad(w,"関連語の数","3〜4語にする（今 "+rel.length+" 語）",rel.map(r=>r.word).join(", "));
  rel.forEach(rw=>{
    const tag="関連語 "+rw.word;
    if(!rw.breakdown){bad(w,tag,"breakdown がない","");return;}
    if(!rw.meaning) bad(w,tag,"meaning がない","");
    if(len(rw.breakdown)>45) bad(w,tag+"：長さ","breakdown は45字以内（今 "+len(rw.breakdown)+" 字）",rw.breakdown);
    if(rw.synonym) return;
    checkHead(w,tag,rw.breakdown,{maxRight:45,needEq:false});
    if(!app.splitMorphs(rw.breakdown).length) bad(w,tag+"：語根マップ","splitMorphs() が語根を拾えない",rw.breakdown);
  });
  if(rel.length&&rel.every(r=>r.synonym)&&!w.hook&&!w.memory) warn(w,"hook","関連語が全部同意語なのに hook がない","");
  /* 10 既存の語根との綴り・語義のずれ */
  if(addFile){
    const all=[...chips];
    rel.forEach(rw=>{if(!rw.synonym) all.push(...app.splitMorphs(rw.breakdown));});
    all.forEach(r=>{
      const k=app.canonRoot(r.morph);
      if(app.SUFFIX_STOP.has(k)) return;
      if(!knownRoots[k]){newRoots.set(k,(newRoots.get(k)||new Set()).add(r.gloss));return;}
      if(r.gloss&&!knownRoots[k].has(r.gloss)) warn(w,"語根の語義",r.morph+"（"+r.gloss+"）: 既存では「"+[...knownRoots[k]].join("／")+"」",r.morph);
    });
  }
  /* 11〜13 例文 */
  [["example","exampleJa"],["example2","exampleJa2"]].forEach(([en,ja])=>{
    if(!w[en]){bad(w,en,"例文がない","");return;}
    const n=String(w[en]).trim().split(/\s+/).length;
    if(n<8||n>14) bad(w,en+"：語数","8〜14語にする（今 "+n+" 語）",w[en]);
    if(!String(w[ja]||"").trim()) bad(w,ja,"和訳がない","");
  });
  if(!/\s/.test(w.word)){
    const c=app.clozeOf(w);
    if(!c) bad(w,"空所補充","clozeOf() がどちらの例文でも空所を作れない",w.example);
    else if(c.en!==w.example) warn(w,"空所補充","1文目で空所が作れず、2文目が使われる",w.example);
  }
  /* 15 品詞 16 発音 18 hook */
  if(!POS_OK.includes(w.partOfSpeech)) bad(w,"品詞","許可された8種類から選ぶ",w.partOfSpeech);
  if(!/^\/.+\/$/.test(String(w.pronunciation||""))) bad(w,"発音","/ で始まり / で終える",w.pronunciation);
  if(w.hook&&len(w.hook)>60) bad(w,"hook：長さ","60字以内（今 "+len(w.hook)+" 字）",w.hook);
  if(w.hook&&chips.length>=2) warn(w,"hook","語源で分解できる語に hook がある（仕様では分解できない語だけ）",w.hook);
  /* 語源の結論の＝の後ろと meaning */
  const eq=String(w.etymologyConclusion||"").split("＝").pop();
  const core=s=>String(s||"").split("；")[0].replace(/[～〜（）()]/g,"").replace(/[をにがとへで]/g,"");
  if(eq&&core(w.meaning)&&!core(w.meaning).includes(core(eq))&&!core(eq).includes(core(w.meaning)))
    warn(w,"＝の後ろ","＝の後ろ「"+eq+"」が meaning「"+w.meaning+"」とそろっていない",eq);
});

/* ---------- 全体の検査 ---------- */
/* 14 番号・パート・α */
const sorted=[...ALL].sort((a,b)=>a.id-b.id);
const seen=new Map();
sorted.forEach((w,i)=>{
  if(seen.has(w.id)) bad(w,"id：重複","id "+w.id+" が "+seen.get(w.id)+" と重複",w.id);
  seen.set(w.id,w.word);
  if(i>0&&w.id!==sorted[i-1].id+1&&w.id!==sorted[i-1].id) bad(w,"id：欠番",sorted[i-1].id+" の次が "+w.id,w.id);
});
if(sorted.length&&sorted[0].id!==1) bad(sorted[0],"id：先頭","id は 1 から始める",sorted[0].id);
TARGET.forEach(w=>{
  if(isAlpha(w)) return;
  if(addFile&&w.part!==Math.ceil(w.id/10)) bad(w,"part","id÷10 の切り上げ＝"+Math.ceil(w.id/10)+" にする",w.part);
});
const mainIds=ALL.filter(w=>!isAlpha(w)).map(w=>w.id);
const alphaIds=ALL.filter(isAlpha).map(w=>w.id);
if(alphaIds.length&&Math.min(...alphaIds)<Math.max(...mainIds))
  bad({id:Math.min(...alphaIds),word:"(α)"},"Part α の位置","α が本編より前にある","");
/* α の中身が HEAD（最後のコミット）と同じか。id と part 以外を比べる */
try{
  const headHtml=execSync("git show HEAD:index.html",{cwd:DIR,maxBuffer:1<<26}).toString();
  const headAF=alphaFromOf(headHtml);
  const strip=w=>{const {id,part,...rest}=w;return JSON.stringify(rest);};
  const before=new Map(rawWordsOf(headHtml).filter(w=>w.id>=headAF).map(w=>[w.word,strip(w)]));
  const now=new Map(ALL.filter(isAlpha).map(w=>[w.word,strip(w)]));
  before.forEach((v,k)=>{
    if(!now.has(k)) bad({id:"α",word:k},"Part α の中身","α の語がなくなっている",k);
    else if(now.get(k)!==v) bad({id:"α",word:k},"Part α の中身","α の中身が書き換わっている",k);
  });
  now.forEach((v,k)=>{if(!before.has(k)) bad({id:"α",word:k},"Part α の中身","α に語が増えている",k);});
}catch(e){warns.push({id:"-",word:"-",item:"Part α","why":"git で比べられなかった: "+e.message.split("\n")[0],val:""});}

/* 17 meaning の先頭語義の重複（全語が相手） */
const headMeaning=w=>String(w.meaning||"").split("；")[0].replace(/[～〜\s]/g,"");
const byMeaning=new Map();
ALL.filter(w=>!isAlpha(w)).forEach(w=>{const k=headMeaning(w);(byMeaning.get(k)||byMeaning.set(k,[]).get(k)).push(w);});
TARGET.forEach(w=>{
  if(isAlpha(w)) return;
  const others=(byMeaning.get(headMeaning(w))||[]).filter(x=>x!==w);
  if(others.length) bad(w,"meaning：重複","先頭語義が "+others.map(x=>x.id+" "+x.word).join("、")+" と同じ",w.meaning);
});

/* ---------- 出力 ---------- */
const pad=(s,n)=>{s=String(s);let w=0;for(const ch of s)w+=/[ -~]/.test(ch)?1:2;return s+" ".repeat(Math.max(0,n-w));};
const table=list=>list.forEach(e=>console.log(pad(e.id,5)+pad(e.word,14)+pad(e.item,26)+pad(e.why,48)+e.val));

const checked=TARGET.filter(w=>!isAlpha(w));
const index=app.buildRootIndex(ALL);
const four=checked.filter(w=>w.example&&app.clozeOf(w)).length;
const stats=()=>{
  console.log("\n--- 統計 ---");
  console.log("語根マップの語根数（全語）: "+index.length);
  console.log("4方向すべてで出題できる語: "+four+" / "+checked.length+"（"+Math.round(four/Math.max(1,checked.length)*100)+"%）");
  if(addFile) console.log("新しく生えた語根: "+([...newRoots].map(([k,g])=>k+"（"+[...g].join("／")+"）").join("、")||"なし"));
};

if(!errors.length){
  console.log("ALL PASS ("+checked.length+" words checked)");
}else{
  const failed=new Set(errors.map(e=>e.id+" "+e.word));
  console.log("違反 "+errors.length+" 件（"+failed.size+" 語） / 検査した語 "+checked.length);
  console.log(pad("id",5)+pad("単語",14)+pad("項目",26)+pad("理由",48)+"実際の値");
  table(errors);
}
if(warns.length&&!args.includes("--quiet")){
  console.log("\n--- 警告（合否には関係しない。人が判断する） "+warns.length+" 件 ---");
  table(warns);
}
stats();
process.exit(errors.length?1:0);
