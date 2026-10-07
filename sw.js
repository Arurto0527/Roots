/* Roots の保存係（Service Worker）
   ・音声ファイル：一度聞いたらスマホに保存 → 次からは一瞬で再生、オフラインでもOK
   ・アプリ本体：ネットにつながるときは最新版を取りに行き、つながらないときは保存版を使う
   アプリを更新したときは、下の VERSION の数字を1つ上げる（アプリ本体の保存だけ入れ替わる）

   音声の保存（AUDIO_CACHE）は VERSION を付けない。
   音声のファイル名は英文から計算した名前なので、英文を変えれば別の名前になる。
   つまり古い音声が残っていても、まちがった音が鳴ることはない。
   VERSION に付けてしまうと、番号を上げるたびに保存済みの音声が全部消えて、
   もう一度ダウンロードすることになるので、切り離しておく。 */
const VERSION = "v81";
const AUDIO_CACHE = "roots-audio";
const APP_CACHE = "roots-app-" + VERSION;

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
    /* 古い版で作った音声の保存（roots-audio-v6 など）が残っていれば、
       中身を新しい保存場所へ引き継いでから消す（もう一度ダウンロードしなくてよくする） */
    const audio = await caches.open(AUDIO_CACHE);
    for (const k of keys) {
      if (k === AUDIO_CACHE || !k.startsWith("roots-audio-")) continue;
      const old = await caches.open(k);
      for (const req of await old.keys()) {
        if (await audio.match(req)) continue;
        const res = await old.match(req);
        if (res) await audio.put(req, res);
      }
    }
    // roots-compiled はアプリ本体を変換した結果（index.html が自分で管理する）。消さない
    for (const k of keys)
      if (k !== AUDIO_CACHE && k !== APP_CACHE && k !== "roots-compiled") await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

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
