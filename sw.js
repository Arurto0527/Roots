/* Roots の保存係（Service Worker）
   ・音声ファイル：一度聞いたらスマホに保存 → 次からは一瞬で再生、オフラインでもOK
   ・アプリ本体：ネットにつながるときは最新版を取りに行き、つながらないときは保存版を使う
   アプリを更新したときは、下の VERSION の数字を1つ上げる（アプリ本体の保存だけ入れ替わる）

   音声の保存（AUDIO_CACHE）は VERSION を付けない。
   音声のファイル名は英文から計算した名前なので、英文を変えれば別の名前になる。
   つまり古い音声が残っていても、まちがった音が鳴ることはない。
   VERSION に付けてしまうと、番号を上げるたびに保存済みの音声が全部消えて、
   もう一度ダウンロードすることになるので、切り離しておく。 */
const VERSION = "v8";
const AUDIO_CACHE = "roots-audio";
const APP_CACHE = "roots-app-" + VERSION;

self.addEventListener("install", () => self.skipWaiting());
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
    for (const k of keys)
      if (k !== AUDIO_CACHE && k !== APP_CACHE) await caches.delete(k);
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
  if (url.pathname.includes("/audio/")) {
    e.respondWith((async () => {
      const cache = await caches.open(AUDIO_CACHE);
      const hit = await cache.match(url.pathname);
      if (hit) return hit;
      const res = await fetch(url.pathname);
      if (res.ok) cache.put(url.pathname, res.clone());
      return res;
    })());
    return;
  }

  // アプリ本体と React などの部品：まずネット、だめなら保存版
  e.respondWith((async () => {
    const cache = await caches.open(APP_CACHE);
    try {
      // ページを開き直すときは HTTP キャッシュを使わず最新版を取得する。
      const res = await fetch(req, req.mode === "navigate" ? { cache: "no-store" } : undefined);
      if (res.ok || res.type === "opaque") cache.put(req, res.clone());
      return res;
    } catch (err) {
      const hit = await cache.match(req, { ignoreSearch: true });
      if (hit) return hit;
      throw err;
    }
  })());
});
