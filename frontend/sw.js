const CACHE = "ubetra-v71";
const ASSETS = [
  "/",
  "/assets/styles.css",
  "/assets/app.js",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET" || request.url.includes("/api/")) {
    return;
  }
  // Network-first for app shell so nav/UI fixes apply without a stuck History tab.
  event.respondWith(
    fetch(request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy));
        return response;
      })
      .catch(() => caches.match(request))
  );
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "New message" };
  }
  const title = payload.title || "UBETRA";
  const body = payload.body || "New chat message";
  const url = payload.url || "/";
  const tag = payload.tag || "ubetra-chat";
  const dynamicId = payload.dynamic_id || "";
  event.waitUntil(
    Promise.all([
      self.registration.showNotification(title, {
        body,
        tag,
        data: { url, dynamicId },
        renotify: true,
      }),
      self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
        list.forEach((client) => {
          client.postMessage({
            type: "ubetra-chat-push",
            dynamicId,
            url,
          });
        });
      }),
    ])
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/#/home";
  const href = new URL(target, self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("focus" in client) {
          client.postMessage({ type: "ubetra-navigate", url: target });
          return client.focus();
        }
      }
      return self.clients.openWindow(href);
    })
  );
});
