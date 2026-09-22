#!/usr/bin/env node
/* ============================================================
   ピクトグラムを画像にして目で確かめるための道具

     node preview-picto.js man prov creat        … 語根を指定して並べる
     node preview-picto.js --since "コメントの一部"  … そのコメント以降の語根をまとめて

   /tmp/roots-picto.svg を作る。macOS なら続けて
     qlmanage -t -s 1000 -o /tmp /tmp/roots-picto.svg
   を実行すると /tmp/roots-picto.svg.png ができるので、それを画像として見る。
   ============================================================ */
const fs=require("fs"),path=require("path");
const h=fs.readFileSync(path.join(__dirname,"index.html"),"utf8");
const args=process.argv.slice(2);

let src=h;
if(args[0]==="--since"){
  const a=h.indexOf(args[1]);
  if(a<0){console.error("そのコメントが見つかりません: "+args[1]);process.exit(1);}
  const b=h.indexOf("\n  /*",a+10);
  src=h.slice(a,b<0?h.length:b);
  args.length=0;
}
const all=[...src.matchAll(/^  ([A-Za-z-]+):<>([\s\S]*?)<\/>,$/gm)].map(m=>[m[1],m[2]]);
const want=args.length?all.filter(([k])=>args.includes(k)):all;
if(!want.length){console.error("絵が1つも見つかりません");process.exit(1);}

const COL=8, CELL=56, LABEL=14;
const cols=Math.min(COL,want.length), rows=Math.ceil(want.length/cols);
const W=cols*CELL+8, H=rows*(CELL+LABEL)+6;
const parts=want.map(([k,v],i)=>{
  const x=(i%cols)*CELL+4, y=Math.floor(i/cols)*(CELL+LABEL)+4;
  return `<g transform="translate(${x},${y})">${v}</g>`
    +`<text x="${x+24}" y="${y+CELL+4}" font-size="9" text-anchor="middle" fill="#111" stroke="none">${k}</text>`;
});
/* qlmanage は正方形に収めて描くので、viewBox も正方形にしておく（右端が切れるのを防ぐ） */
const S=Math.max(W,H);
const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${S*3}" height="${S*3}" viewBox="0 0 ${S} ${S}" `
 +`fill="none" stroke="#111" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">`
 +`<rect width="${S}" height="${S}" fill="#fff" stroke="none"/>${parts.join("")}</svg>`;
fs.writeFileSync("/tmp/roots-picto.svg",svg);
console.log(want.length+"個を /tmp/roots-picto.svg に書き出しました: "+want.map(x=>x[0]).join(", "));
console.log("次を実行して PNG にし、画像として見てください:");
console.log("  qlmanage -t -s 1000 -o /tmp /tmp/roots-picto.svg && open /tmp/roots-picto.svg.png");
