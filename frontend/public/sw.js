/* Horizon Services Immobiliers — PWA service worker.
 *
 * Strategy:
 * - Network-first for /api/* (fresh data always preferred, cache is a
 *   fallback only when we're offline so the app doesn't break cold).
 * - Cache-first for Next.js _next/static assets (they're content-hashed,
 *   so once cached they never go stale).
 * - Stale-while-revalidate for every navigation to /m/* so the app shell
 *   comes up instantly even offline, with the latest HTML replacing it
 *   in the background when the network returns.
 */

const VERSION = "hsi-v5";
const RUNTIME_CACHE = `${VERSION}-runtime`;
const SHELL_CACHE = `${VERSION}-shell`;

const SHELL_URLS = [
  "/m",
  "/m/agenda",
  "/m/punch",
  "/m/profil",
  "/m/clients",
  "/telephonie",
  "/manifest.webmanifest",
  "/telephonie/manifest.webmanifest",
  "/pwa/icon-192.png",
  "/pwa/icon-512.png",
  "/pwa/apple-touch-icon.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // Best-effort — don't fail install if one URL 404s.
      await Promise.all(
        SHELL_URLS.map((u) =>
          cache.add(u).catch(() => undefined)
        )
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Clean old versioned caches
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => !k.startsWith(VERSION))
          .map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

function isApi(url) {
  return url.pathname.startsWith("/api/");
}

function isStatic(url) {
  return (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/pwa/") ||
    url.pathname === "/manifest.webmanifest"
  );
}

function isNavigation(request) {
  return (
    request.mode === "navigate" ||
    (request.method === "GET" &&
      request.headers.get("accept")?.includes("text/html"))
  );
}

async function networkFirst(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  try {
    const fresh = await fetch(request);
    // Only cache successful same-origin GETs; skip opaque/redirect.
    if (request.method === "GET" && fresh.ok && fresh.type === "basic") {
      cache.put(request, fresh.clone());
    }
    return fresh;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const fresh = await fetch(request);
  if (fresh.ok) cache.put(request, fresh.clone());
  return fresh;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  const fetchAndUpdate = fetch(request)
    .then((resp) => {
      if (resp.ok) cache.put(request, resp.clone());
      return resp;
    })
    .catch(() => cached);
  return cached || fetchAndUpdate;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (isApi(url)) {
    event.respondWith(networkFirst(request));
    return;
  }
  if (isStatic(url)) {
    event.respondWith(cacheFirst(request));
    return;
  }
  if (isNavigation(request) && (url.pathname.startsWith("/m") || url.pathname.startsWith("/telephonie"))) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }
  // Let everything else hit the network normally.
});

// Allow the page to ask the SW to skip waiting (used when a new
// version is available and the user clicks "Recharger").
self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

// ─── WebPush — réveille l'app pour les urgences, SMS, appels ───
//
// Payload attendu (JSON) :
//   { title, body, href, tag, icon }
//
// `tag` permet de regrouper / remplacer les notifications similaires
// (ex. plusieurs SMS du même contact → on remplace au lieu d'empiler).
self.addEventListener("push", (event) => {
  if (!event.data) return;
  let data = {};
  try {
    data = event.data.json();
  } catch {
    data = { title: "Horizon", body: event.data.text() };
  }
  const title = data.title || "Horizon Services Immobiliers";
  const options = {
    body: data.body || "",
    icon: data.icon || "/pwa/icon-192.png",
    badge: "/pwa/icon-192.png",
    tag: data.tag || "horizon",
    renotify: true,
    data: { href: data.href || "/" }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// Clic sur une notification → focus une fenêtre Horizon existante OU
// en ouvre une nouvelle sur l'URL fournie.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetHref = (event.notification.data && event.notification.data.href) || "/";
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true
      });
      for (const c of all) {
        try {
          await c.focus();
          if ("navigate" in c) {
            await c.navigate(targetHref);
          }
          return;
        } catch {
          /* keep trying */
        }
      }
      await self.clients.openWindow(targetHref);
    })()
  );
});
