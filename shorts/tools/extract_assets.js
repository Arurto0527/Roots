// index.html（アプリ本体）を「読むだけ」で、ショート動画に必要なデータを取り出す。
//   node shorts/tools/extract_assets.js
// 出力: shorts/data/words.json（単語・意味・語源パーツ・色の種類・ピクトグラム番号）
//       shorts/data/picto.json（ピクトグラムの SVG。48×48 の線画）
// 使う前に一度だけ: cd shorts/tools && npm install
const fs = require("fs");
const path = require("path");
const vm = require("vm");
let Babel;
try { Babel = require("@babel/standalone"); }
catch (e) { Babel = require(process.env.BABEL_PATH || "@babel/standalone"); }

const ROOT = path.resolve(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const m = html.match(/<script type="text\/x-roots-jsx" id="roots-app">([\s\S]*?)<\/script>/);
if (!m) throw new Error("roots-app が見つかりません");
let src = m[1];
const cut = src.indexOf("\nfunction App(){");
if (cut < 0) throw new Error("function App の目印が見つかりません");
src = src.slice(0, cut);

// JSX を「SVG の文字列を作る関数」に変換する
const code = Babel.transform(src, { presets: [["react", { runtime: "classic", pragma: "h", pragmaFrag: "FRAG" }]] }).code;
const FRAG = "__frag__";
const kebab = k => k === "className" ? "class" : k.replace(/[A-Z]/g, c => "-" + c.toLowerCase());
const flat = a => [a].flat(Infinity).filter(x => x !== null && x !== undefined && x !== false && x !== true);
// React の要素と同じく props.children を持たせる（アプリのコードが G.person.props.children のように使うため）
class El {
  constructor(tag, props, children) { this.tag = tag; this.props = { ...(props || {}), children: children.length === 1 ? children[0] : children }; }
  toString() {
    const inner = flat(this.props.children).map(String).join("");
    if (this.tag === FRAG) return inner;
    const attrs = Object.entries(this.props).filter(([k, v]) => v != null && k !== "key" && k !== "children" && typeof v !== "object" && typeof v !== "function")
      .map(([k, v]) => ` ${kebab(k)}="${String(v).replace(/"/g, "&quot;")}"`).join("");
    return `<${this.tag}${attrs}>${inner}</${this.tag}>`;
  }
}
function h(tag, props, ...children) {
  if (typeof tag === "function") { try { return tag({ ...(props || {}), children: children.length === 1 ? children[0] : children }); } catch (e) { return ""; } }
  return new El(tag, props, children);
}
const noop = () => {};
const store = {};
const sandbox = {
  h, FRAG, console,
  React: { createElement: h, Fragment: FRAG, useState: v => [v, noop], useEffect: noop, useLayoutEffect: noop, useMemo: f => f(), useCallback: f => f, useRef: v => ({ current: v }), memo: f => f },
  localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
  navigator: { userAgent: "node", language: "ja" },
  location: { search: "", hash: "", href: "http://localhost/", pathname: "/" },
  matchMedia: () => ({ matches: false, addEventListener: noop, addListener: noop }),
  addEventListener: noop, removeEventListener: noop, setTimeout, clearTimeout, setInterval, clearInterval,
  speechSynthesis: { getVoices: () => [], addEventListener: noop },
  Audio: function () {}, fetch: () => Promise.reject(new Error("offline")),
};
sandbox.document = { getElementById: () => ({ textContent: "{}" }), querySelector: () => null, addEventListener: noop, createElement: () => ({ style: {} }), documentElement: { style: {} }, body: { style: {} } };
sandbox.window = sandbox;
sandbox.self = sandbox;
const tail = `;__out={RAW_WORDS,parseRoots,morphType,pictoFor,canonRoot,imageryOf,LIGHT,ROOT_NOTES:typeof ROOT_NOTES!=="undefined"?ROOT_NOTES:{}};`;
vm.createContext(sandbox);
vm.runInContext(code.replace(/^"use strict";/, "") + tail, sandbox, { filename: "roots-app.js" });
const X = sandbox.__out;

const pictos = {}; const pictoIndex = new Map();
const pid = svg => { if (!pictoIndex.has(svg)) { const id = "p" + pictoIndex.size; pictoIndex.set(svg, id); pictos[id] = svg; } return pictoIndex.get(svg); };
const words = X.RAW_WORDS.map(w => {
  const parts = X.parseRoots(w);
  return {
    id: w.id, word: w.word, meaning: w.meaning, pos: w.partOfSpeech, pron: w.pronunciation || "", eiken: w.eikenLevel || "",
    imagery: X.imageryOf(w),
    parts: parts.map((p, i) => {
      const type = X.morphType(p.morph, i, parts.length, parts);
      const hit = X.pictoFor(p.morph, p.gloss, type);
      return { morph: p.morph, gloss: p.gloss, type, canon: X.canonRoot(p.morph), picto: hit ? pid(String(hit.g)) : null, isRoot: hit ? !!hit.isRoot : false };
    }),
    related: (w.relatedWords || []).filter(r => !r.synonym).map(r => ({ word: r.word, meaning: r.meaning, breakdown: r.breakdown || "" })),
  };
});
const out = path.join(ROOT, "shorts", "data");
fs.mkdirSync(out, { recursive: true });
const colors = { pre: X.LIGHT.pre, root: X.LIGHT.root, suf: X.LIGHT.suf };
fs.writeFileSync(path.join(out, "words.json"), JSON.stringify({ generatedFrom: "index.html", colors, words }));
fs.writeFileSync(path.join(out, "picto.json"), JSON.stringify(pictos));
console.log(`words: ${words.length}  pictograms: ${Object.keys(pictos).length}  colors:`, colors);
