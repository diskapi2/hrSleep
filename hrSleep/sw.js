// Service worker: keeps a local copy of everything hrSleep needs to play, so music and
// piano samples load from the phone instead of the network (and work offline).
//  - This app's own files (index.html, music/*): network first so updates arrive,
//    falling back to the cached copy when the network is slow or missing.
//  - Libraries and piano samples (versioned, never change): cache first.
const CACHE = "hrSleep-v1";
const NETWORK_TIMEOUT_MS = 3000;

const LIBS = [
  "https://cdn.jsdelivr.net/npm/tone@14.8.49/build/Tone.js",
  "https://cdn.jsdelivr.net/npm/@tonejs/midi@2.0.28/build/Midi.js",
];
// Same sample set as the Tone.Sampler in index.html.
const SAMPLES = ["A1", "C2", "Ds2", "Fs2", "A2", "C3", "Ds3", "Fs3", "A3", "C4", "Ds4", "Fs4",
  "A4", "C5", "Ds5", "Fs5", "A5", "C6"].map(n => "https://tonejs.github.io/audio/salamander/" + n + ".mp3");

async function precache() {
  const cache = await caches.open(CACHE);
  const urls = ["./", "index.html", "music/manifest.json"].concat(LIBS, SAMPLES);
  try {
    const manifest = await (await fetch("music/manifest.json", { cache: "no-cache" })).json();
    for (const m of manifest) urls.push("music/" + m.file);
  } catch (e) { /* offline during install: the pieces get cached when first played */ }
  // One at a time and failure-tolerant, so one missing file doesn't block the rest.
  for (const url of urls) {
    try { await cache.add(new Request(url, { cache: "reload" })); } catch (e) { /* skip */ }
  }
}

self.addEventListener("install", (ev) => {
  ev.waitUntil(precache().then(() => self.skipWaiting()));
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

async function cacheFirst(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok || res.type === "opaque") (await caches.open(CACHE)).put(req, res.clone());
  return res;
}

async function networkFirst(req) {
  const cache = await caches.open(CACHE);
  const network = fetch(req).then((res) => {
    if (res.ok) cache.put(req, res.clone());
    return res;
  });
  network.catch(() => {});   // a late failure after we answered from the cache is fine
  const timeout = new Promise((resolve) => setTimeout(resolve, NETWORK_TIMEOUT_MS));
  try {
    const res = await Promise.race([network, timeout]);
    if (res) return res;
  } catch (e) { /* offline: use the cache */ }
  const hit = await cache.match(req, { ignoreSearch: true });
  return hit || network;   // nothing cached yet: keep waiting for the network
}

self.addEventListener("fetch", (ev) => {
  const req = ev.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === self.location.origin) ev.respondWith(networkFirst(req));
  else if (LIBS.includes(req.url) || url.hostname === "tonejs.github.io") ev.respondWith(cacheFirst(req));
});
