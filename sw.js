/* Roots の保存係（Service Worker）
   ・音声ファイル：一度聞いたらスマホに保存 → 次からは一瞬で再生、オフラインでもOK
   ・アプリ本体：ネットにつながるときは最新版を取りに行き、つながらないときは保存版を使う
   アプリを更新して音声を作り直したときは、下の VERSION の数字を1つ上げる */
const VERSION = "v1";
const AUDIO_CACHE = "roots-audio-" + VERSION;
const APP_CACHE = "roots-app-" + VERSION;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys())
      if (k !== AUDIO_CACHE && k !== APP_CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

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
      const res = await fetch(req);
      if (res.ok || res.type === "opaque") cache.put(req, res.clone());
      return res;
    } catch (err) {
      const hit = await cache.match(req, { ignoreSearch: true });
      if (hit) return hit;
      throw err;
    }
  })());
});
