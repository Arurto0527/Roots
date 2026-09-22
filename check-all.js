#!/usr/bin/env node
/* ============================================================
   Roots 仕上げチェック
   単語を追加したあと、抜けがないかをまとめて調べる。

     node check-all.js

   node validate.js が「単語データそのもの」を見るのに対して、
   こちらは「ピクトグラム・語源コラム・英検レベル・音声・番号」の
   つけ忘れを見つける。最後に表を出す。
   ============================================================ */
const fs=require("fs"),path=require("path"),vm=require("vm");
const DIR=__dirname;
const h=fs.readFileSync(path.join(DIR,"index.html"),"utf8");
const slice=(s,st,en)=>{const a=s.indexOf(st);const b=s.indexOf(en,a);return s.slice(a,b);};

/* ---------- アプリの関数をそのまま借りる ---------- */
const RAW=vm.runInNewContext(h.slice(h.indexOf("const RAW_WORDS=[")+"const RAW_WORDS=".length,
  h.indexOf("\n];",h.indexOf("const RAW_WORDS=["))+2));
const appCode=[h.match(/const esc=s=>.*\n/)[0],
  slice(h,"function clozeOf(w){","\n/* ====="),
  slice(h,"const rootCache={};","/* ============================================================\n   AUDIO")].join("\n");
const app={};
vm.runInNewContext(appCode+"\n;Object.assign(OUT,{parseRoots,canonRoot,morphType,SUFFIX_STOP});",{OUT:app});

/* ---------- トップ階層のキーを拾う（1行複数キー・引用符つきキーの両方に対応） ---------- */
function topKeys(name){
  const st="const "+name+"={";
  let i=h.indexOf(st)+st.length,d=1,str=null,buf="",keys=[];
  while(d>0&&i<h.length){
    const c=h[i];
    if(str){ if(c==="\\"){i+=2;continue;} if(c===str){str=null;i++;continue;} if(d===1)buf+=c; i++; continue; }
    if(c==='"'||c==="'"){ if(d===1)buf=""; str=c; i++; continue; }
    if(c==="/"&&h[i+1]==="*"){ i=h.indexOf("*/",i)+2; continue; }
    if(c==="{")d++; else if(c==="}")d--;
    if(d===1){
      if(c===":"&&buf.trim()){keys.push(buf.trim());buf="";}
      else if(c===","||c==="\n")buf="";
      else if(c!=="{"&&c!=="}")buf+=c;
    }
    i++;
  }
  return new Set(keys.filter(k=>/^[A-Za-z-]+$/.test(k)));
}
/* 文法的な語尾だが、その語の最後のパーツなので morphType が「語根」と判定してしまうもの。
   コラムも絵も作らなくてよいので、抜けチェックから外す。
   新しくこの手の語尾が出たら、ここに足すのではなく、
   まず「本当に語根ではないか」を確かめること */
const SUFFIX_EXTRA=new Set(["ior","ature","tude","istic","ture","ella","ledge"]);
const PICTO=topKeys("PICTO_ROOT");
const NOTES=topKeys("ROOT_NOTES");
const BY_GLOSS=new Set([...slice(h,"const PICTO_BY_GLOSS={","\n};").matchAll(/"([^"]+)"\s*:/g)].map(m=>m[1]));
const EIKEN=vm.runInNewContext("("+slice(h,"const EIKEN_LEVELS={","};").slice("const EIKEN_LEVELS=".length)+"})");
const ALPHA_FROM=Number((h.match(/const ALPHA_FROM=(\d+);/)||[])[1]||Infinity);
const LAYOUT=(h.match(/const WORDS_LAYOUT=(\d+);/)||[])[1];
const RECALL_KEY=(h.match(/lsGet\("(roots\.listRecall\.v\d+)"\)/)||[])[1];
const SW=(fs.existsSync(path.join(DIR,"sw.js"))?fs.readFileSync(path.join(DIR,"sw.js"),"utf8"):"").match(/const VERSION\s*=\s*"([^"]+)"/);

const rows=[];const detail=[];
const add=(k,v,ng)=>rows.push([k,v,!!ng]);

/* ---------- 1. 見出し語の重複・id のとび ---------- */
const byWord={};RAW.forEach(w=>{(byWord[w.word]=byWord[w.word]||[]).push(w.id);});
const dupWord=Object.entries(byWord).filter(([,v])=>v.length>1);
add("見出し語の重複",dupWord.length+"件",dupWord.length);
if(dupWord.length) detail.push("【見出し語の重複】\n"+dupWord.map(([k,v])=>"  "+k+" → No."+v.join(", No.")).join("\n"));

const ids=RAW.map(w=>w.id).sort((a,b)=>a-b);
const gaps=[];for(let i=1;i<ids.length;i++) if(ids[i]!==ids[i-1]+1) gaps.push(ids[i-1]+"→"+ids[i]);
add("id のとび",gaps.length+"件"+(gaps.length?"（"+gaps.join(", ")+"）":""),gaps.length);

/* ---------- 2. meaning の先頭語義の重複 ---------- */
const head=s=>String(s||"").split("；")[0].trim();
const byMean={};RAW.filter(w=>w.id<ALPHA_FROM).forEach(w=>{(byMean[head(w.meaning)]=byMean[head(w.meaning)]||[]).push(w.id+" "+w.word);});
const dupMean=Object.entries(byMean).filter(([,v])=>v.length>1);
add("meaning の先頭語義の重複",dupMean.length+"件",dupMean.length);
if(dupMean.length) detail.push("【meaning の重複】\n"+dupMean.map(([k,v])=>"  「"+k+"」 … "+v.join(" / ")).join("\n"));

/* ---------- 3. 語根まわり（コラム・ピクトグラム） ---------- */
const missNote={},missPic={},noPic=[];
for(const w of RAW){
  if(w.id>=ALPHA_FROM) continue;
  const parts=app.parseRoots(w)||[];
  let hasPic=false;
  parts.forEach((p,i)=>{
    const k=app.canonRoot(p.morph), t=app.morphType(p.morph,i,parts.length,parts);
    if(PICTO.has(k)||BY_GLOSS.has(k+"|"+(p.gloss||""))) hasPic=true;
    if(t!=="root"||app.SUFFIX_STOP.has(k)||SUFFIX_EXTRA.has(k)) return;   /* 文法的な接尾辞は対象外 */
    if(!NOTES.has(k)) (missNote[k]=missNote[k]||[]).push(w.id+" "+w.word+"（"+p.gloss+"）");
    if(!PICTO.has(k)) (missPic[k]=missPic[k]||[]).push(w.id+" "+w.word+"（"+p.gloss+"）");
  });
  if(!hasPic) noPic.push(w.id+" "+w.word);
}
add("語源コラムが無い語根",Object.keys(missNote).length+"件",Object.keys(missNote).length);
add("ピクトグラムが無い語根",Object.keys(missPic).length+"件",Object.keys(missPic).length);
add("絵が1つも出ない単語",noPic.length+"件",noPic.length);
const fmt=o=>Object.entries(o).map(([k,v])=>"  "+k+": "+v.join(" / ")).join("\n");
if(Object.keys(missNote).length) detail.push("【語源コラムなし】\n"+fmt(missNote));
if(Object.keys(missPic).length)  detail.push("【ピクトグラムなし】\n"+fmt(missPic));
if(noPic.length)                 detail.push("【絵が1つも出ない単語】\n  "+noPic.join(" / "));

/* ---------- 4. 英検レベル ---------- */
const OKLV=["5級","4級","3級","準2級","2級","準1級","1級"];
const noEiken=RAW.filter(w=>!EIKEN[w.word]);
const badEiken=Object.entries(EIKEN).filter(([,v])=>!OKLV.includes(v));
add("英検レベル未設定",noEiken.length+"件",noEiken.length);
add("英検レベルの表記ゆれ",badEiken.length+"件",badEiken.length);
if(noEiken.length) detail.push("【英検レベル未設定】\n  "+noEiken.map(w=>w.id+" "+w.word).join(" / "));
if(badEiken.length) detail.push("【英検レベルの表記ゆれ】\n  "+badEiken.map(x=>x[0]+"→"+x[1]).join(" / "));

/* ---------- 5. 音声 ---------- */
const fnv=s=>{let x=0x811c9dc5;s=String(s).trim();for(let i=0;i<s.length;i++){x^=s.charCodeAt(i);x=Math.imul(x,0x01000193)>>>0;}return x.toString(16).padStart(8,"0");};
const PREVIEW=["Hello. This is American English.","Hello. This is British English."];
const need=new Map();
PREVIEW.forEach(t=>need.set(fnv(t),"（アクセント見本）"+t));
for(const w of RAW){
  const texts=[w.word,w.example,w.example2];
  (w.relatedWords||[]).forEach(r=>texts.push(r.word));
  for(const t of texts){const v=String(t||"").trim();if(v)need.set(fnv(v),w.id+" "+w.word+" : "+v);}
}
let idx=null;
try{ idx=JSON.parse(h.match(/id="roots-audio-index"[^>]*>([\s\S]*?)<\/script>/)[1]); }catch(e){}
const missAudio=[],orphan=[];
for(const acc of ["us","uk"]){
  const dir=path.join(DIR,"audio",acc);
  const have=fs.existsSync(dir)?new Set(fs.readdirSync(dir).filter(f=>/^[0-9a-f]{8}\.m4a$/.test(f)).map(f=>f.slice(0,-4))):new Set();
  const inIdx=idx&&Array.isArray(idx[acc])?new Set(idx[acc]):null;
  for(const [k,label] of need){
    if(!have.has(k)) missAudio.push(acc+" ファイルなし "+label);
    else if(inIdx&&!inIdx.has(k)) missAudio.push(acc+" 索引にない "+label);
  }
  for(const k of have) if(!need.has(k)) orphan.push("audio/"+acc+"/"+k+".m4a");
}
add("音声の欠け（米・英）",missAudio.length+"件",missAudio.length);
add("使われていない音声",orphan.length+"件",0);   /* 残っていても動作には支障なし */
if(missAudio.length) detail.push("【音声の欠け】\n  "+missAudio.slice(0,40).join("\n  "));
if(orphan.length) detail.push("【使われていない音声（消してよい）】\n  "+orphan.length+"件。先頭: "+orphan.slice(0,6).join(" / "));

/* ---------- 6. 番号まわり ---------- */
const alphaIds=RAW.filter(w=>w.id>=ALPHA_FROM).map(w=>w.id);
const alphaLast=alphaIds.length&&Math.max(...alphaIds)===Math.max(...ids);
add("Part α が末尾にあるか",alphaLast?"はい（No."+ALPHA_FROM+"〜"+Math.max(...ids)+"）":"いいえ",!alphaLast);
add("ALPHA_FROM / WORDS_LAYOUT",ALPHA_FROM+" / "+LAYOUT,0);
add("○×の保存キー / sw.js VERSION",(RECALL_KEY||"?")+" / "+(SW?SW[1]:"?"),0);
add("本編の語数 / 全体",(ids.filter(i=>i<ALPHA_FROM).length)+" / "+RAW.length,0);

/* ---------- 出力 ---------- */
const pad=(s,n)=>{let w=0;for(const c of String(s))w+=/[\x00-\xff]/.test(c)?1:2;return String(s)+" ".repeat(Math.max(0,n-w));};
console.log("\n=== Roots 仕上げチェック ===\n");
for(const [k,v,ng] of rows) console.log("  "+(ng?"NG ":"ok ")+pad(k,34)+v);
if(detail.length) console.log("\n"+detail.join("\n\n"));
const ngCount=rows.filter(r=>r[2]).length;
console.log("\n"+(ngCount?"NG が "+ngCount+" 件あります。直してから完了と報告してください。":"すべて問題ありません。")+"\n");
console.log("※ ピクトグラムの「絵が何に見えるか」は機械では分かりません。必ず目で見て確認すること。\n");
process.exit(ngCount?1:0);
