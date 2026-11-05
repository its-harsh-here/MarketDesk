/* MarketDesk service worker (M14).
 * Caches only the application shell (index.html, icons, manifest) and the build's hashed /assets files, so the app
 * can open without a network. It never touches /api: no authentication response, quote or private data is cached
 * here. The read-only offline copy of watchlists and holdings is a separate, opt-in, per-device snapshot written by
 * the page and erased on sign-out. */
const SHELL = "md-shell-v1";
const ASSETS = "md-assets-v1";
const SHELL_FILES = ["/", "/manifest.webmanifest", "/favicon.svg", "/icon-192.png"];
const MAX_ASSETS = 80;

// Precache the shell and the hashed scripts/styles it references, so a reload without a network can start the app.
async function precache() {
  const shell = await caches.open(SHELL);
  await shell.addAll(SHELL_FILES);
  const html = await (await shell.match("/")).text();
  const assets = Array.from(new Set(html.match(/\/assets\/[A-Za-z0-9._-]+/g) || []));
  if (assets.length) await (await caches.open(ASSETS)).addAll(assets);
}

self.addEventListener("install", (event) => {
  event.waitUntil(precache().then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== ASSETS).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function trimAssets() {
  const cache = await caches.open(ASSETS);
  const keys = await cache.keys();
  for (const k of keys.slice(0, Math.max(0, keys.length - MAX_ASSETS))) await cache.delete(k);
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (req.mode === "navigate") {
    // Network first, so a deploy is picked up at once; the cached shell only when the server cannot be reached.
    event.respondWith(
      fetch(req)
        .then((res) => {
          const type = res.headers.get("content-type") || "";
          if (res.ok && type.includes("text/html")) {
            const copy = res.clone();
            caches.open(SHELL).then((c) => c.put("/", copy));
          }
          return res;
        })
        .catch(() => caches.match("/").then((r) => r || Response.error())),
    );
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    // Hashed file names never change content: cache first.
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(ASSETS).then((c) => c.put(req, copy)).then(trimAssets);
            }
            return res;
          }),
      ),
    );
    return;
  }
  if (SHELL_FILES.includes(url.pathname)) {
    event.respondWith(fetch(req).catch(() => caches.match(req).then((r) => r || Response.error())));
  }
});

self.addEventListener("message", (event) => {
  if (event.data === "md-clear") {
    event.waitUntil(caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k)))));
  }
});
