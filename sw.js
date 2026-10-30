/* Roots の保存係（Service Worker）
   ・音声ファイル：一度聞いたらスマホに保存 → 次からは一瞬で再生、オフラインでもOK
   ・アプリ本体：ネットにつながるときは最新版を取りに行き、つながらないときは保存版を使う
   アプリを更新したときは、下の VERSION の数字を1つ上げる（アプリ本体の保存だけ入れ替わる）

   音声の保存（AUDIO_CACHE）は VERSION を付けない。
   音声のファイル名は英文から計算した名前なので、英文を変えれば別の名前になる。
   つまり古い音声が残っていても、まちがった音が鳴ることはない。
   VERSION に付けてしまうと、番号を上げるたびに保存済みの音声が全部消えて、
   もう一度ダウンロードすることになるので、切り離しておく。
   ただし音声を同じファイル名のまま作り直したとき（2026-10 に Piper → Kokoro）は、
   AUDIO_CACHE の名前を変える。古い名前の保存は activate でまるごと消える。
   （roots-voice-kokoro は音声を入れ替える前に公開してしまい、Piper の音が入りうるので -2 にした）
   何本かだけ作り直したときは、名前は変えずに REDONE に「us/ハッシュ」を足す。
   保存済みの中からその音声だけを消して取り直すので、ほかの音声はダウンロードし直さなくてよい */
const VERSION = "v107";
const AUDIO_CACHE = "roots-voice-kokoro-2";
const APP_CACHE = "roots-app-" + VERSION;
/* 2026-10-19 聞き取りチェックで聞きまちがえられた短い音声を作り直した56本 */
const REDONE = ["uk/0c0b271c","uk/1c7bfef8","uk/2288b25b","uk/281ba64e","uk/28fcb92f","uk/2e48d9ed","uk/348f1364","uk/3e6d42ef","uk/43e36503","uk/45afe178","uk/49473311","uk/5045bcac","uk/50cac900","uk/62b2d6da","uk/6a0f559a","uk/702ecbd1","uk/78f4b947","uk/864f3222","uk/8827595f","uk/88ad264a","uk/89b29c10","uk/8f09b003","uk/9b76c143","uk/a694e261","uk/aa25504e","uk/aad0a14e","uk/ae7f4d1c","uk/af1eb592","uk/b26fac7d","uk/c487c2fe","uk/c5f847a1","uk/c77ae4a0","uk/caeda9d9","uk/d608551f","uk/d81a37a2","uk/d8dfb383","uk/dc7b77f2","uk/de776945","uk/e52b80e0","uk/e8311335","uk/eda17c15","uk/ef92fe2b","uk/fb6f4827","uk/fed68570","us/019fb038","us/2669fe9e","us/49504791","us/56cad272","us/676712b6","us/6bfbd198","us/6c97732c","us/985fcc5f","us/a947e23c","us/b3dcff8f","us/b8736ad5","us/d81a37a2","us/074c76c2","us/11bd3353","us/2cb41ebc","us/3197f49c","us/599b0f6d","us/61da8eed","us/666cfa4d","us/6a0f559a","us/6dda4e1a","us/763e0219","us/852dc331","us/a17256c6","us/b7188846","us/c20c8395","us/c242f5b7","us/d5021bfa","us/d596d9e1","us/e052c162","us/ec0486f5","us/f73e1580","uk/074c76c2","uk/11bd3353","uk/2cb41ebc","uk/3197f49c","uk/599b0f6d","uk/61da8eed","uk/666cfa4d","uk/6dda4e1a","uk/763e0219","uk/852dc331","uk/a17256c6","uk/b7188846","uk/c20c8395","uk/c242f5b7","uk/d5021bfa","uk/d596d9e1","uk/e052c162","uk/ec0486f5","uk/f73e1580"];

/* はじめて開いたときに、アプリを動かすのに必要なものをまとめて保存しておく。
   こうすると、一度ネットにつないで開けば、次からはネットなしでも起動できる。
   （1つ取れなくても残りは保存する。取れなかったものは、使ったときに保存される） */
const PRECACHE = [
  "./",
  "https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js",
  "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js",
  "https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.26.4/babel.min.js",
  "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.57.4/dist/umd/supabase.min.js",
  "https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&display=swap",
  "chara/normal.png", "chara/cheer.png", "chara/teach.png", "chara/think.png",
  "manga/chara.jpg",
];

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil((async () => {
    const cache = await caches.open(APP_CACHE);
    await Promise.all(PRECACHE.map(async (u) => {
      try {
        const cross = u.startsWith("http");
        // 外の部品は、まず中身が見える形（cors）で取る。見えない形（opaque）は
        // iPhone で1個につき数MBぶんの容量として数えられ、保存があふれる原因になるため
        let res = null;
        if (cross) { try { res = await fetch(u, { mode: "cors" }); } catch (err) {} }
        if (!res || !(res.ok || res.type === "opaque"))
          res = await fetch(new Request(u, cross ? { mode: "no-cors" } : { cache: "no-store" }));
        if (res.ok || res.type === "opaque") await cache.put(u, res);
      } catch (err) {}
    }));
  })());
});
self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    /* 前の声（Piper）の保存 roots-audio などは引き継がずに消す（下の削除でまとめて消える） */
    // roots-compiled はアプリ本体を変換した結果（index.html が自分で管理する）。消さない
    for (const k of keys)
      if (k !== AUDIO_CACHE && k !== APP_CACHE && k !== "roots-compiled") await caches.delete(k);
    await self.clients.claim();
    // 作り直した音声だけ、保存してあれば消して新しい音を取り直す（ネットがなければ消すだけ。次に鳴らすとき取りに行く）
    try {
      const audio = await caches.open(AUDIO_CACHE);
      const redo = new Set(REDONE.map((x) => "/audio/" + x + ".m4a"));
      for (const r of await audio.keys()) {
        const p = new URL(r.url).pathname;
        if (!redo.has(p.slice(p.lastIndexOf("/audio/")))) continue;
        await audio.delete(r);
        try { const res = await fetch(p, { cache: "reload" }); if (res.ok) await audio.put(p, res); } catch (err) {}
      }
    } catch (err) {}
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // 授業用ページ（class/）と教育実習の予定表（jisshu/）は保存しない。いつも最新版を出す
  if (url.pathname.includes("/class/") || url.pathname.includes("/jisshu/")) return;

  // ログインや学習データの通信（Supabase）は保存しない
  if (url.hostname.endsWith("supabase.co")) return;

  // 音声：保存してあればそれを使う。なければ取りに行って保存
  // iPhone（Safari）は音声を「○バイト目から○バイト目まで」と少しずつ要求してくる（Range）。
  // 丸ごと返すと再生してくれないので、要求された部分だけを切り出して返す
  if (url.pathname.includes("/audio/")) {
    e.respondWith((async () => {
      const cache = await caches.open(AUDIO_CACHE);
      let res = await cache.match(url.pathname);
      if (!res) {
        res = await fetch(url.pathname);
        if (!res.ok) return res;
        await cache.put(url.pathname, res.clone());
      }
      return partial(req, res);
    })());
    return;
  }

  // アプリ本体と React などの部品：保存版があればすぐ返し、新しい版は裏で取っておく。
  // こうすると、アプリが大きくなっても起動を待たされない（次に開いたときに新しい版になる）。
  e.respondWith((async () => {
    const cache = await caches.open(APP_CACHE);
    const hit = await cache.match(req, { ignoreSearch: true });

    // 裏で最新版を取りに行って保存する
    const update = (async () => {
      try {
        // ページ本体は HTTP キャッシュを使わずに取得する。
        // 保存版の「版の目じるし」（ETag）を添えて聞き、変わっていなければ中身を送ってこない（304）。
        // こうしないと、開くたびに約5MBの本体を丸ごとダウンロードして比べることになり、起動が重くなる
        let res;
        if (req.mode === "navigate") {
          const tag = hit && hit.headers.get("ETag");
          res = await fetch(new Request(req.url, {
            cache: "no-store", credentials: "same-origin",
            headers: tag ? { "If-None-Match": tag } : {},
          }));
          if (res.status === 304) return hit;
        } else {
          res = await fetch(req);
        }
        if (res.ok || res.type === "opaque") {
          // 中身が変わっていたら、開いている画面に「新しい版がある」と知らせる
          if (hit && req.mode === "navigate") {
            const a = hit.headers.get("ETag"), b = res.headers.get("ETag");
            const changed = a && b ? a !== b
              : (await hit.clone().text()) !== (await res.clone().text());
            if (changed) {
              const list = await self.clients.matchAll({ type: "window" });
              for (const c of list) c.postMessage({ type: "update-ready" });
            }
          }
          await cache.put(req, res.clone());
        }
        return res;
      } catch (err) {
        return null;
      }
    })();

    if (hit) { e.waitUntil(update); return hit; }   // 保存版があれば待たせない
    const res = await update;                       // 初回だけネットを待つ
    if (res) return res;
    // ネットがなく、「/Roots」「/Roots/index.html」など別の書き方で開いたときも、保存版の本体を出す
    if (req.mode === "navigate") {
      const home = await cache.match("./");
      if (home) return home;
    }
    return new Response("", { status: 504, statusText: "offline" });
  })());
});

/* Range（部分の要求）があれば、その部分だけを 206 で返す。なければそのまま返す */
async function partial(req, res) {
  const range = req.headers.get("range");
  const m = range && /bytes=(\d*)-(\d*)/.exec(range);
  if (!m) return res;
  const buf = await res.arrayBuffer();
  const size = buf.byteLength;
  let start = m[1] === "" ? size - Number(m[2]) : Number(m[1]);
  let end = m[1] !== "" && m[2] !== "" ? Number(m[2]) : size - 1;
  start = Math.max(0, start); end = Math.min(end, size - 1);
  if (start > end) return new Response("", { status: 416, headers: { "Content-Range": "bytes */" + size } });
  return new Response(buf.slice(start, end + 1), {
    status: 206,
    headers: {
      "Content-Type": res.headers.get("Content-Type") || "audio/mp4",
      "Content-Range": "bytes " + start + "-" + end + "/" + size,
      "Content-Length": String(end - start + 1),
      "Accept-Ranges": "bytes",
    },
  });
}
