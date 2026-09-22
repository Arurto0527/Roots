/* index.html のテーブルに、同じキーが2回書かれていないかを調べる。
   JavaScript は後ろのキーが勝つので、重複すると前のほうが「表示されない死んだ記述」になる。 */
const fs=require("fs");const s=fs.readFileSync("index.html","utf8");
let ng=0;
for(const n of ["PICTO_ROOT","PICTO_PREFIX","PICTO_BY_GLOSS","ROOT_NOTES","ROOT_ALIAS","EIKEN_LEVELS"]){
  const a=s.indexOf("const "+n+"={"); if(a<0){console.log("?? "+n+": 見つからない");continue;}
  let d=0,st=a+("const "+n+"=").length,e=st;
  for(let i=st;i<s.length;i++){const c=s[i];if(c==="{")d++;else if(c==="}"){d--;if(!d){e=i+1;break;}}}
  const blk=s.slice(st,e);
  const keys=[];let dep=0,q=null,tag=0,want=false;
  for(let i=0;i<blk.length;i++){
    const c=blk[i];
    if(q){ if(c==="\\"){i++;continue;} if(c===q)q=null; continue; }
    if(c==="/"&&blk[i+1]==="*"){const k=blk.indexOf("*/",i);i=(k<0?blk.length:k+1);continue;}
    if(c==="/"&&blk[i+1]==="/"){const k=blk.indexOf("\n",i);i=(k<0?blk.length:k);continue;}
    if(!tag&&dep===1&&want&&!/\s/.test(c)){
      const m=/^("?)([A-Za-z][A-Za-z0-9_|｜ぁ-ヶ一-龥〜～]*)\1\s*:/.exec(blk.slice(i,i+80));
      if(m){keys.push(m[2]);i+=m[0].length-1;want=false;continue;}
    }
    if(c==='"'||c==="'"){q=c;continue;}
    if(c==="<")tag++; else if(c===">"&&tag)tag--;
    if(tag)continue;
    if(c==="{"){dep++;want=(dep===1);continue;}
    if(c==="}"){dep--;continue;}
    if(c===","&&dep===1)want=true;
  }
  const cnt={};keys.forEach(k=>cnt[k]=(cnt[k]||0)+1);
  const dup=Object.keys(cnt).filter(k=>cnt[k]>1);
  if(dup.length)ng++;
  console.log((dup.length?"NG ":"ok ")+n.padEnd(15)+"キー "+String(keys.length).padStart(4)+" / 重複 "+dup.length+(dup.length?"  → "+dup.join(" "):""));
}
console.log(ng?"\n重複あり。後ろのほうだけが使われているので、前のほうを消すこと。":"\n重複はありません。");
